"""
Orquestrador principal — pipeline determinístico de investigação.
Recebe caminho de documento (PDF) e retorna grafo de vínculos + laudo.
"""
import json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from extrator.extrator import extrair_licitantes
from skills.consulta_cnpj.skill import consultar_cnpj
from skills.busca_reversa_socios.skill import buscar_empresas_do_socio
from skills.scoring_conluio.skill import calcular_score
from skills.gera_laudo.skill import gerar_laudo


def investigar(caminho_pdf: str, aprofundar: bool = False,
               limite_aprofundamento: int = 30) -> dict:
    """
    Pipeline completo de investigação.
    Retorna dict com grafo, alertas e laudo.

    aprofundar: se True, executa o 2º nível (consulta o QSA das empresas
        externas da busca reversa; SCPs via BrasilAPI grátis). Opt-in porque
        faz dezenas de chamadas adicionais.
    limite_aprofundamento: teto de empresas externas a aprofundar.
    """
    warnings = []

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
        dados = consultar_cnpj(cnpj, razao_social=empresa.get("razao_social"))
        dados["lance"] = empresa.get("lance")
        dados["resultado"] = empresa.get("resultado")
        dados_empresas.append(dados)
        print(f"      → {cnpj} — {dados.get('razao_social', 'N/A')}")

    print("\n[3/5] Investigando sócios (busca reversa)...")
    expansao_socios = investigar_socios(dados_empresas)
    grafo = construir_grafo(dados_empresas, expansao_socios)

    if aprofundar:
        print("\n[3.5] Aprofundando rede externa (SCPs via BrasilAPI grátis)...")
        grafo["aprofundamento"] = aprofundar_rede(grafo, limite=limite_aprofundamento)

    print("\n[4/5] Calculando score de conluio...")
    score = calcular_score(grafo)
    print(f"      → Score: {score['score_geral']} | Alertas: {len(score['alertas'])}")

    print("\n[5/5] Gerando laudo...")
    laudo = gerar_laudo(grafo, score, licitantes["meta"])

    return {
        "meta": licitantes["meta"],
        "grafo": grafo,
        "score": score,
        "laudo": laudo,
        "warnings": warnings
    }


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


def construir_grafo(dados_empresas: list, expansao_socios: dict = None) -> dict:
    """
    Monta o grafo de vínculos entre empresas e sócios.
    Detecta sócios em comum entre licitantes e anexa a expansão da busca
    reversa (empresas externas por sócio), quando disponível.
    """
    expansao_socios = expansao_socios or {}
    socios_index = {}  # cpf_parcial+nome → [cnpjs]

    for empresa in dados_empresas:
        cnpj = empresa.get("cnpj", "")
        if not cnpj:
            continue
        for socio in empresa.get("qsa", []):
            chave = f"{socio.get('cpf_cnpj_socio', '')}|{socio.get('nome_socio', '').upper()}"
            if chave not in socios_index:
                socios_index[chave] = []
            socios_index[chave].append(cnpj)

    vinculos_suspeitos = [
        {"socio": chave.split("|")[1], "cpf": chave.split("|")[0], "empresas": cnpjs}
        for chave, cnpjs in socios_index.items()
        if len(cnpjs) > 1
    ]

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


def aprofundar_rede(grafo: dict, limite: int = 30, apenas_scp: bool = True) -> dict:
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
    n_free = n_cnpja = 0
    for raiz, nome in itens:
        cnpj = _cnpj_matriz(raiz)
        if not cnpj:
            continue
        try:
            d = consultar_cnpj(cnpj, razao_social=nome)
        except Exception as ex:
            print(f"        [falha ao aprofundar {raiz} {nome[:30]}: {ex}]")
            continue
        if d.get("fonte") == "brasilapi":
            n_free += 1
        else:
            n_cnpja += 1
        aprofundamento[cnpj] = {
            "razao_social": d.get("razao_social") or nome,
            "qsa": d.get("qsa", []),
            "fonte": d.get("fonte"),
            "raiz": raiz,
        }
    print(f"      → aprofundamento: {n_free} via BrasilAPI (grátis), {n_cnpja} via CNPJá (crédito)")
    return aprofundamento


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    aprofundar = "--aprofundar" in sys.argv
    if not args:
        print("Uso: python orquestrador/main.py <caminho_do_pdf> [--aprofundar]")
        sys.exit(1)
    resultado = investigar(args[0], aprofundar=aprofundar)
    print("\n=== LAUDO ===")
    print(resultado["laudo"])
