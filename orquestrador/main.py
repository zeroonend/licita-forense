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


def investigar(caminho_pdf: str) -> dict:
    """
    Pipeline completo de investigação.
    Retorna dict com grafo, alertas e laudo.
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
        dados = consultar_cnpj(cnpj)
        dados["lance"] = empresa.get("lance")
        dados["resultado"] = empresa.get("resultado")
        dados_empresas.append(dados)
        print(f"      → {cnpj} — {dados.get('razao_social', 'N/A')}")

    print("\n[3/5] Investigando sócios (busca reversa)...")
    expansao_socios = investigar_socios(dados_empresas)
    grafo = construir_grafo(dados_empresas, expansao_socios)

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


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python orquestrador/main.py <caminho_do_pdf>")
        sys.exit(1)
    resultado = investigar(sys.argv[1])
    print("\n=== LAUDO ===")
    print(resultado["laudo"])
