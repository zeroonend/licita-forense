"""
Skill: busca_reversa_socios
Dado um sócio (nome + CPF parcial), retorna todas as empresas onde aparece.
Usa CNPJá API — endpoint de pesquisa reversa.
"""
import os
import httpx
from dotenv import load_dotenv
load_dotenv()

CNPJA_KEY = os.getenv("CNPJA_API_KEY")
CNPJA_BASE = "https://api.cnpja.com"


def buscar_empresas_do_socio(nome: str, cpf_parcial: str = None) -> list:
    """
    Busca todas as empresas onde o sócio aparece no QSA.
    cpf_parcial: 6 dígitos centrais do CPF (mascarado pela Receita)
    Retorna lista de CNPJs.
    """
    headers = {"Authorization": CNPJA_KEY}
    params = {"name": nome}
    if cpf_parcial:
        params["taxId"] = cpf_parcial

    try:
        r = httpx.get(f"{CNPJA_BASE}/person", headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        return _extrair_cnpjs(data)
    except Exception as e:
        print(f"      [busca reversa falhou para {nome}: {e}]")
        return []


def _extrair_cnpjs(data: dict) -> list:
    """Extrai lista de CNPJs das empresas onde o sócio participa."""
    empresas = []
    for item in data.get("data", []):
        for company in item.get("companies", []):
            empresas.append({
                "cnpj": company.get("taxId", ""),
                "razao_social": company.get("name", ""),
                "qualificacao": company.get("role", {}).get("text", ""),
                "data_entrada": company.get("since", ""),
                "situacao": company.get("status", {}).get("text", "")
            })
    return empresas
