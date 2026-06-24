"""
Skill: busca_reversa_socios
Dado um sócio (nome + CPF mascarado), retorna todas as empresas onde ele aparece.

Usa a CNPJá API, endpoint /person com filtro `name.in`. A resposta traz, para
cada pessoa, a lista `membership[]` com as empresas (raiz de CNPJ de 8 dígitos).
O CPF mascarado da Receita (6 dígitos centrais visíveis) é usado para
desambiguar homônimos sem precisar do CPF completo.
"""
import os
import httpx
from dotenv import load_dotenv
load_dotenv()

CNPJA_KEY = os.getenv("CNPJA_API_KEY")
CNPJA_BASE = "https://api.cnpja.com"


def buscar_empresas_do_socio(nome: str, cpf_parcial: str = None) -> list:
    """
    Busca todas as empresas onde o sócio aparece (raiz de CNPJ de 8 dígitos).
    cpf_parcial: CPF mascarado do QSA (ex.: "***620791**") — usado para filtrar
    homônimos pelos 6 dígitos centrais. Opcional.
    Retorna lista de dicts {cnpj (raiz), razao_social, qualificacao, data_entrada}.
    """
    if not CNPJA_KEY:
        print("      [busca reversa indisponível: CNPJA_API_KEY não configurada]")
        return []

    headers = {"Authorization": CNPJA_KEY}
    params = {"name.in": nome}

    try:
        r = httpx.get(f"{CNPJA_BASE}/person", headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"      [busca reversa falhou para {nome}: {e}]")
        return []

    return _extrair_empresas(data, cpf_parcial)


def _cpf_meio(valor: str) -> str:
    """
    Reduz um CPF (mascarado ou completo) aos 6 dígitos centrais, que são os
    visíveis na máscara da Receita. Permite comparar QSA × busca reversa.
    """
    d = "".join(c for c in (valor or "") if c.isdigit())
    if len(d) == 11:   # CPF completo → posições 4-9
        return d[3:9]
    if len(d) == 6:    # já são os 6 centrais
        return d
    return ""


def _extrair_empresas(data: dict, cpf_parcial: str = None) -> list:
    """Extrai empresas das memberships, filtrando homônimos pelo CPF mascarado."""
    alvo = _cpf_meio(cpf_parcial)
    empresas = []
    vistos = set()
    for rec in data.get("records", []):
        # Desambiguação: se temos os 6 dígitos do alvo e do registro, exigir match.
        rec_meio = _cpf_meio(rec.get("taxId"))
        if alvo and rec_meio and alvo != rec_meio:
            continue
        for m in rec.get("membership", []):
            comp = m.get("company", {})
            cnpj_raiz = comp.get("id", "")  # 8 dígitos (raiz do CNPJ)
            if not cnpj_raiz or cnpj_raiz in vistos:
                continue
            vistos.add(cnpj_raiz)
            empresas.append({
                "cnpj": cnpj_raiz,
                "razao_social": comp.get("name", ""),
                "qualificacao": m.get("role", {}).get("text", ""),
                "data_entrada": m.get("since", ""),
            })
    return empresas
