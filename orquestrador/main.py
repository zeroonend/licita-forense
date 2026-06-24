"""
Orquestrador principal — pipeline determinístico de investigação.
Recebe caminho de documento (PDF) e retorna grafo de vínculos + laudo.
"""
import os
import sys
import json
import uuid
import hashlib
import datetime

# Permite rodar como script (`python orquestrador/main.py`) garantindo que a
# raiz do repositório esteja no sys.path para os imports de pacote abaixo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from extrator.extrator import extrair_licitantes, MAX_CHARS, EXTRACTOR_PROMPT_VERSION
from skills.consulta_cnpj.skill import consultar_cnpj
from skills.busca_reversa_socios.skill import buscar_empresas_do_socio
from skills.consulta_dominio.skill import consultar_dono_dominio
from skills.scoring_conluio.skill import (
    calcular_score, _dominio_email, PROVEDORES_GENERICOS, _e_administrador,
)
from skills.gera_laudo.skill import gerar_laudo, LAUDO_PROMPT_VERSION
from skills.laudo_pdf.skill import gerar_pdf
from llm import reset_telemetria, telemetria
import cache
import db

# Empresa cacheada há mais de N dias é reconsultada (equilíbrio crédito × frescor).
CACHE_MAX_IDADE_DIAS = 90

SCHEMA_VERSION = "investigation_result.v1"


def investigar(caminho_pdf: str, aprofundar: bool = False,
               limite_aprofundamento: int = 30, persistir: bool = True,
               gravar_cache: bool = False, replay_store: dict = None,
               usar_banco: bool = False) -> dict:
    """
    Pipeline completo de investigação.
    Retorna um artefato `investigation_result.v1` (schema versionado, com
    metadados de execução para rastreabilidade/auditoria forense).

    aprofundar: se True, executa o 2º nível (consulta o QSA das empresas
        externas da busca reversa; SCPs via BrasilAPI grátis). Opt-in porque
        faz dezenas de chamadas adicionais.
    limite_aprofundamento: teto de empresas externas a aprofundar.
    persistir: se True, grava o artefato em execucoes/<id>.json.
    gravar_cache: se True, grava no artefato o store de chamadas (cache_store)
        para permitir replay determinístico depois.
    replay_store: se fornecido, roda em modo replay (nenhuma chamada externa
        nova; respostas vêm deste store).
    usar_banco: se True, usa o SQLite como cache persistente de consultas
        (economia de crédito entre execuções) e indexa a execução para
        cruzamento entre editais. Desligado nos modos record/replay para não
        interferir na captura/reprodução determinística da trilha.
    """
    reset_telemetria()
    if replay_store is not None:
        cache.configurar("replay", store=replay_store)
    elif gravar_cache:
        cache.configurar("record")
    else:
        cache.configurar("off")
    # O cache de banco só atua no modo "off": em record perderíamos a chamada na
    # trilha; em replay a resposta tem de vir do store gravado.
    conn = db.conectar() if (usar_banco and replay_store is None and not gravar_cache) else None
    warnings = []
    execucao_id = str(uuid.uuid4())
    started_at = _agora()
    pdf_sha256, pdf_bytes = _hash_arquivo(caminho_pdf)

    print(f"\n[1/5] Extraindo licitantes de {caminho_pdf}...")
    licitantes = extrair_licitantes(caminho_pdf)
    print(f"      → {len(licitantes['empresas'])} empresas encontradas")

    print("\n[2/5] Consultando CNPJá para cada licitante...")
    dados_empresas = []
    for empresa in licitantes["empresas"]:
        cnpj = empresa.get("cnpj")
        # Documentos de "resultado" muitas vezes trazem só o nome, sem CNPJ.
        # Sem CNPJ não há como puxar o QSA — registra a empresa, avisa e segue.
        if not "".join(c for c in (cnpj or "") if c.isdigit()):
            aviso = f"Empresa '{empresa.get('razao_social', 'N/A')}' sem CNPJ no documento — enriquecimento e busca de sócios pulados."
            warnings.append(aviso)
            dados_empresas.append({
                "cnpj": cnpj or "",
                "razao_social": empresa.get("razao_social", ""),
                "qsa": [],
                "endereco": "",
                "fonte": "sem_cnpj",
                "lance": empresa.get("lance"),
                "resultado": empresa.get("resultado"),
            })
            print(f"      → [sem CNPJ] {empresa.get('razao_social', 'N/A')}")
            continue
        dados, do_cache = _cnpj_com_cache(conn, cnpj, empresa.get("razao_social"))
        dados["lance"] = empresa.get("lance")
        dados["resultado"] = empresa.get("resultado")
        dados_empresas.append(dados)
        print(f"      → {cnpj} — {dados.get('razao_social', 'N/A')}"
              + (" [cache]" if do_cache else ""))

    print("\n[2.5] Enriquecendo domínios de e-mail (registro.br)...")
    _enriquecer_dominios(dados_empresas, conn)

    print("\n[3/5] Investigando sócios (busca reversa)...")
    expansao_socios = investigar_socios(dados_empresas)
    grafo = construir_grafo(dados_empresas, expansao_socios)

    if aprofundar:
        print("\n[3.5] Aprofundando rede externa (SCPs via BrasilAPI grátis)...")
        grafo["aprofundamento"] = aprofundar_rede(grafo, limite=limite_aprofundamento, conn=conn)

    print("\n[4/5] Calculando score de conluio...")
    score = calcular_score(grafo)
    print(f"      → Score: {score['score_geral']} | Alertas: {len(score['alertas'])}")

    print("\n[5/5] Gerando laudo...")
    laudo_texto = gerar_laudo(grafo, score, licitantes["meta"])

    # Monta o artefato versionado com a trilha de execução.
    chamadas_llm = telemetria()
    por_finalidade = {c["purpose"]: c for c in chamadas_llm}
    call_extr = por_finalidade.get("extracao")
    call_laudo = por_finalidade.get("laudo")

    artefato = {
        "schema_version": SCHEMA_VERSION,
        "execution": {
            "id": execucao_id,
            "started_at": started_at,
            "finished_at": _agora(),
            "status": "partial" if warnings else "success",
            "input_pdf_sha256": pdf_sha256,
            "input_pdf_bytes": pdf_bytes,
            "source_file_name": os.path.basename(caminho_pdf),
            "parameters": {
                "extractor_max_chars": MAX_CHARS,
                "aprofundar": aprofundar,
                "limite_aprofundamento": limite_aprofundamento,
                "replay": replay_store is not None,
            },
            "external_calls": cache.registros(),
            "components": {
                "extractor_model": call_extr["model"] if call_extr else None,
                "laudo_model": call_laudo["model"] if call_laudo else None,
                "prompt_versions": {
                    "extractor": EXTRACTOR_PROMPT_VERSION,
                    "laudo": LAUDO_PROMPT_VERSION,
                },
                "ruleset_version": score.get("ruleset_version"),
                "llm_calls": chamadas_llm,
            },
        },
        "licitacao": licitantes["meta"],
        "grafo": grafo,
        "score": score,
        "laudo": {
            "mode": "llm" if call_laudo else "template",
            "text": laudo_texto,
            "provider": call_laudo["provider"] if call_laudo else None,
            "model": call_laudo["model"] if call_laudo else None,
            "generated_at": _agora(),
        },
        "warnings": warnings,
    }

    # Em modo record, anexa o store de chamadas para permitir replay posterior.
    if gravar_cache:
        artefato["cache_store"] = cache.store()

    if persistir:
        artefato["execution"]["artifact_path"] = _persistir_artefato(artefato)
        print(f"      [artefato salvo: {artefato['execution']['artifact_path']}]")

    if conn is not None:
        db.registrar_execucao(conn, artefato)
        print("      [execução indexada no banco para cruzamento entre editais]")
        conn.close()

    return artefato


def _cnpj_com_cache(conn, cnpj: str, razao_social: str):
    """
    Consulta a empresa usando o banco como cache persistente quando disponível.
    Retorna (dados, veio_do_cache). Dados de empresa são fatos estáveis; lance e
    resultado (específicos do edital) são anexados pelo chamador, fora do cache.
    """
    if conn is not None:
        cacheado = db.empresa_cacheada(conn, cnpj, CACHE_MAX_IDADE_DIAS)
        if cacheado is not None:
            return dict(cacheado), True
    dados = consultar_cnpj(cnpj, razao_social=razao_social)
    if conn is not None:
        db.salvar_empresa(conn, cnpj, dados)
    return dados, False


def reexecutar_replay(caminho_artefato: str, caminho_pdf: str,
                      aprofundar: bool = False, persistir: bool = False) -> dict:
    """
    Reexecuta uma investigação em modo replay a partir de um artefato gravado
    com `gravar_cache=True` — nenhuma chamada externa nova ocorre. Útil para
    reproduzir um laudo de forma determinística (valor probatório).
    """
    with open(caminho_artefato, encoding="utf-8") as f:
        artefato = json.load(f)
    store = artefato.get("cache_store")
    if not store:
        raise ValueError("Artefato não contém cache_store (grave com gravar_cache=True).")
    return investigar(caminho_pdf, aprofundar=aprofundar, persistir=persistir,
                      replay_store=store)


def _agora() -> str:
    """Timestamp UTC em ISO-8601 (para a trilha de execução)."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _hash_arquivo(caminho: str):
    """SHA-256 e tamanho em bytes do arquivo de entrada (integridade do input)."""
    h = hashlib.sha256()
    total = 0
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(8192), b""):
            h.update(bloco)
            total += len(bloco)
    return h.hexdigest(), total


def _persistir_artefato(artefato: dict, dir_saida: str = "execucoes") -> str:
    """Grava o artefato versionado em execucoes/<id>.json e retorna o caminho."""
    os.makedirs(dir_saida, exist_ok=True)
    caminho = os.path.join(dir_saida, f"investigacao_{artefato['execution']['id']}.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(artefato, f, ensure_ascii=False, indent=2)
    return caminho


def _exportar_frontend(artefato: dict, base_dir: str = None) -> str:
    """
    Exporta o artefato para o organograma consumir automaticamente
    (frontend/resultado-ultimo.json — carregado por padrão pela página).
    """
    base = base_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    os.makedirs(base, exist_ok=True)
    caminho = os.path.join(base, "resultado-ultimo.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(artefato, f, ensure_ascii=False, indent=2)
    return caminho


def investigar_socios(dados_empresas: list) -> dict:
    """
    Busca reversa: para cada sócio único dos licitantes, consulta a CNPJá
    todas as outras empresas onde ele aparece (fora do edital corrente).
    Retorna { chave_socio → [empresas externas] }.
    """
    expansao = {}
    for empresa in dados_empresas:
        for socio in empresa.get("qsa", []):
            nome = socio.get("nome_socio", "")
            cpf = socio.get("cpf_cnpj_socio", "")
            chave = f"{cpf}|{nome.upper()}"
            if not nome or chave in expansao:
                continue
            externas = buscar_empresas_do_socio(nome=nome, cpf_parcial=cpf)
            expansao[chave] = externas
            print(f"      → {nome}: {len(externas)} empresa(s) vinculada(s)")
    return expansao


def _enriquecer_dominios(dados_empresas: list, conn=None) -> None:
    """
    Anexa a cada empresa o domínio do e-mail e o titular do domínio (registro.br),
    para as regras mesmo_email_dominio e mesmo_dono_dominio. Ignora provedores
    genéricos; consulta cada domínio uma única vez. Mutação in-place.
    Usa o banco como cache persistente do titular quando `conn` é fornecido.
    """
    donos = {}  # domínio → titular (memoização por execução)
    for emp in dados_empresas:
        dom = _dominio_email(emp.get("email", ""))
        if not dom or dom in PROVEDORES_GENERICOS:
            continue
        emp["email_dominio"] = dom
        if dom not in donos:
            cacheado = db.dominio_cacheado(conn, dom, CACHE_MAX_IDADE_DIAS) if conn else None
            if cacheado is not None:
                donos[dom] = cacheado if (cacheado.get("id") or cacheado.get("nome")) else None
            else:
                donos[dom] = consultar_dono_dominio(dom)
                if conn is not None:
                    db.salvar_dominio(conn, dom, donos[dom] or {})
            d = donos[dom] or {}
            print(f"      → {dom}: titular {d.get('nome') or d.get('id') or '—'}")
        dono = donos[dom]
        if dono:
            emp["dominio_dono"] = dono.get("id") or dono.get("nome")
            if dono.get("nome"):
                emp["dominio_dono_nome"] = dono["nome"]


def construir_grafo(dados_empresas: list, expansao_socios: dict = None) -> dict:
    """
    Monta o grafo de vínculos entre empresas e sócios.
    Detecta sócios em comum entre licitantes e anexa a expansão da busca
    reversa (empresas externas por sócio), quando disponível.
    """
    expansao_socios = expansao_socios or {}
    socios_index = {}   # chave (cpf|nome) → [cnpjs]
    qualif_index = {}   # chave → {cnpj: qualificação do sócio naquela empresa}

    for empresa in dados_empresas:
        cnpj = empresa.get("cnpj", "")
        if not cnpj:
            continue
        for socio in empresa.get("qsa", []):
            chave = f"{socio.get('cpf_cnpj_socio', '')}|{socio.get('nome_socio', '').upper()}"
            socios_index.setdefault(chave, [])
            if cnpj not in socios_index[chave]:
                socios_index[chave].append(cnpj)
            qualif_index.setdefault(chave, {})[cnpj] = socio.get("qualificacao", "")

    vinculos_suspeitos = []
    for chave, cnpjs in socios_index.items():
        if len(cnpjs) <= 1:
            continue
        quals = qualif_index.get(chave, {})
        admins = [c for c in cnpjs if _e_administrador(quals.get(c, ""))]
        vinculos_suspeitos.append({
            "socio": chave.split("|")[1],
            "cpf": chave.split("|")[0],
            "empresas": cnpjs,
            "qualificacoes": quals,
            # administrador em TODAS as licitantes ligadas → vínculo de controle.
            "admin_em_todas": len(admins) == len(cnpjs),
            "admin_em_alguma": bool(admins),
        })

    # CNPJ completo (14 dígitos) das externas: a busca reversa só devolve a raiz
    # de 8 dígitos; reconstruímos a matriz para exibir o número inteiro no grafo.
    for lst in expansao_socios.values():
        for ext in lst:
            raiz = "".join(c for c in (ext.get("cnpj") or "") if c.isdigit())[:8]
            if raiz and not ext.get("cnpj_completo"):
                ext["cnpj_completo"] = _cnpj_matriz(raiz)

    return {
        "empresas": dados_empresas,
        "socios_index": socios_index,
        "vinculos_suspeitos": vinculos_suspeitos,
        "expansao_socios": expansao_socios
    }


def _cnpj_matriz(raiz: str) -> str:
    """
    Constrói o CNPJ da matriz (raiz + 0001 + 2 dígitos verificadores) a partir
    da raiz de 8 dígitos que a busca reversa devolve. Necessário porque CNPJá e
    BrasilAPI consultam pelo CNPJ completo, não pela raiz.
    """
    base = "".join(c for c in (raiz or "") if c.isdigit())[:8]
    if len(base) != 8:
        return ""
    base += "0001"

    def _dv(nums, pesos):
        soma = sum(int(n) * p for n, p in zip(nums, pesos))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    d1 = _dv(base, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _dv(base + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base + d1 + d2


def aprofundar_rede(grafo: dict, limite: int = 30, apenas_scp: bool = True, conn=None) -> dict:
    """
    2º nível de investigação: consulta o QSA das empresas externas encontradas
    na busca reversa. SCPs são roteadas para a BrasilAPI (grátis); as demais
    para a CNPJá. Limitado por `limite` para não disparar centenas de chamadas.

    Retorna { cnpj_externo_matriz: {razao_social, qsa, fonte, raiz} }.
    """
    # Coleta externas únicas por raiz (e ignora as que já são licitantes).
    raizes_licitantes = {
        "".join(c for c in e.get("cnpj", "") if c.isdigit())[:8]
        for e in grafo.get("empresas", [])
    }
    externas = {}
    for lst in grafo.get("expansao_socios", {}).values():
        for e in lst:
            raiz = "".join(c for c in e.get("cnpj", "") if c.isdigit())[:8]
            if raiz and raiz not in raizes_licitantes and raiz not in externas:
                externas[raiz] = e.get("razao_social", "")

    itens = list(externas.items())
    if apenas_scp:
        itens = [(r, n) for r, n in itens if "SCP" in (n or "").upper().split()]
    total_candidatas = len(itens)
    itens = itens[:limite]
    if total_candidatas > limite:
        print(f"      [aprofundamento limitado a {limite} de {total_candidatas} candidatas]")
    print(f"      → aprofundando {len(itens)} externa(s)" + (" (apenas SCP)" if apenas_scp else ""))

    aprofundamento = {}
    n_free = n_cnpja = n_cache = 0
    for raiz, nome in itens:
        cnpj = _cnpj_matriz(raiz)
        if not cnpj:
            continue
        try:
            d, do_cache = _cnpj_com_cache(conn, cnpj, nome)
        except Exception as ex:
            print(f"        [falha ao aprofundar {raiz} {nome[:30]}: {ex}]")
            continue
        if do_cache:
            n_cache += 1
        elif d.get("fonte") == "brasilapi":
            n_free += 1
        else:
            n_cnpja += 1
        aprofundamento[cnpj] = {
            "razao_social": d.get("razao_social") or nome,
            "qsa": d.get("qsa", []),
            "fonte": d.get("fonte"),
            "raiz": raiz,
        }
    print(f"      → aprofundamento: {n_cache} do cache (banco), "
          f"{n_free} via BrasilAPI (grátis), {n_cnpja} via CNPJá (crédito)")
    return aprofundamento


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    aprofundar = "--aprofundar" in sys.argv
    frontend = "--frontend" in sys.argv
    gravar_cache = "--gravar-cache" in sys.argv
    pdf = "--pdf" in sys.argv
    usar_banco = "--banco" in sys.argv
    if not args:
        print("Uso: python orquestrador/main.py <caminho_do_pdf> "
              "[--aprofundar] [--frontend] [--gravar-cache] [--pdf] [--banco]")
        sys.exit(1)
    resultado = investigar(args[0], aprofundar=aprofundar, gravar_cache=gravar_cache,
                           usar_banco=usar_banco)
    ex = resultado["execution"]
    print(f"\n=== EXECUÇÃO {ex['id']} ({ex['status']}) ===")
    print(f"PDF sha256: {ex['input_pdf_sha256'][:16]}... | extrator: {ex['components']['extractor_model']}"
          f" | laudo: {resultado['laudo']['mode']}/{ex['components']['laudo_model']}")
    if frontend:
        cam = _exportar_frontend(resultado)
        print(f"\n[frontend] Exportado para {cam}")
        print("Abra http://localhost:8000/organograma.html — o resultado carrega automaticamente.")
    if pdf:
        cam_pdf = gerar_pdf(resultado)
        print(f"\n[pdf] Laudo gerado em {cam_pdf}")
    print("\n=== LAUDO ===")
    print(resultado["laudo"]["text"])
