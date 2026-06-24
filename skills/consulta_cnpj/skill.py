"""
Skill: consulta_cnpj
Wrapper da CNPJá API — retorna dados completos da empresa + QSA.
Fallback para BrasilAPI se CNPJá falhar.

Roteamento por economia: empresas SCP (Sociedade em Conta de Participação)
consultam primeiro a BrasilAPI (gratuita), economizando créditos da CNPJá.
"""
import os
import re
from dotenv import load_dotenv
load_dotenv()

import cache

CNPJA_KEY = os.getenv("CNPJA_API_KEY")
CNPJA_BASE = "https://api.cnpja.com"
BRASILAPI_BASE = "https://brasilapi.com.br/api/cnpj/v1"

_RE_SCP = re.compile(r"\bSCP\b", re.IGNORECASE)


def consultar_cnpj(cnpj: str, razao_social: str = None) -> dict:
    """
    Consulta dados de uma empresa pelo CNPJ.

    Por padrão tenta CNPJá primeiro (QSA mais rico) e cai para BrasilAPI.
    Se a razão social indicar SCP, inverte a ordem: BrasilAPI (grátis) primeiro,
    CNPJá apenas como fallback — para não gastar crédito com esse tipo de empresa.
    """
    cnpj_limpo = _limpar_cnpj(cnpj)

    if _e_scp(razao_social):
        print("      [SCP detectada — priorizando BrasilAPI (grátis)]")
        try:
            return _consultar_brasilapi(cnpj_limpo)
        except Exception as e:
            print(f"      [BrasilAPI falhou para SCP: {e}] — tentando CNPJá...")
            return _consultar_cnpja(cnpj_limpo)

    try:
        return _consultar_cnpja(cnpj_limpo)
    except Exception as e:
        print(f"      [CNPJá falhou: {e}] — tentando BrasilAPI...")
        return _consultar_brasilapi(cnpj_limpo)


def _e_scp(razao_social: str) -> bool:
    """True se a razão social contém o marcador 'SCP' como palavra isolada."""
    return bool(_RE_SCP.search(razao_social or ""))


def _limpar_cnpj(cnpj: str) -> str:
    return "".join(c for c in (cnpj or "") if c.isdigit())


def _consultar_cnpja(cnpj: str) -> dict:
    if not CNPJA_KEY:
        raise RuntimeError("CNPJA_API_KEY não configurada (verifique o .env)")
    headers = {"Authorization": CNPJA_KEY}
    data, _ = cache.http_get(f"{CNPJA_BASE}/office/{cnpj}", headers=headers)
    return _normalizar_cnpja(data)


def _consultar_brasilapi(cnpj: str) -> dict:
    data, _ = cache.http_get(f"{BRASILAPI_BASE}/{cnpj}")
    return _normalizar_brasilapi(data)


def _normalizar_cnpja(data: dict) -> dict:
    """Normaliza resposta CNPJá para formato interno."""
    company = data.get("company", {})
    return {
        "cnpj": data.get("taxId", ""),
        "razao_social": company.get("name", ""),
        "nome_fantasia": data.get("alias", ""),
        "situacao": data.get("status", {}).get("text", ""),
        "data_abertura": data.get("founded", ""),
        "natureza_juridica": company.get("nature", {}).get("text", ""),
        "capital_social": company.get("equity", 0),
        "cnae_principal": data.get("mainActivity", {}).get("text", ""),
        "endereco": _montar_endereco(data.get("address", {})),
        "telefone": _extrair_telefone(data.get("phones", [])),
        "email": _extrair_email(data.get("emails", [])),
        "qsa": _extrair_qsa_cnpja(company.get("members", [])),
        "fonte": "cnpja"
    }


def _normalizar_brasilapi(data: dict) -> dict:
    """Normaliza resposta BrasilAPI para formato interno."""
    return {
        "cnpj": data.get("cnpj", ""),
        "razao_social": data.get("razao_social", ""),
        "nome_fantasia": data.get("nome_fantasia", ""),
        "situacao": data.get("descricao_situacao_cadastral", ""),
        "data_abertura": data.get("data_inicio_atividade", ""),
        "natureza_juridica": data.get("descricao_natureza_juridica", ""),
        "capital_social": data.get("capital_social", 0),
        "cnae_principal": data.get("cnae_fiscal_descricao", ""),
        "endereco": f"{data.get('logradouro','')}, {data.get('numero','')}, {data.get('municipio','')}/{data.get('uf','')}",
        "telefone": data.get("ddd_telefone_1", ""),
        "email": None,
        "qsa": _extrair_qsa_brasilapi(data.get("qsa", [])),
        "fonte": "brasilapi"
    }


def _montar_endereco(addr: dict) -> str:
    partes = [addr.get("street",""), addr.get("number",""), addr.get("city",""), addr.get("state","")]
    return ", ".join(p for p in partes if p)


def _extrair_telefone(phones: list) -> str:
    return phones[0].get("number","") if phones else ""


def _extrair_email(emails: list) -> str:
    return emails[0].get("address","") if emails else ""


def _extrair_qsa_cnpja(members: list) -> list:
    return [
        {
            "nome_socio": m.get("person", {}).get("name", ""),
            "cpf_cnpj_socio": m.get("person", {}).get("taxId", ""),
            "qualificacao": m.get("role", {}).get("text", ""),
            "data_entrada": m.get("since", "")
        }
        for m in members
    ]


def _extrair_qsa_brasilapi(qsa: list) -> list:
    return [
        {
            "nome_socio": s.get("nome_socio", ""),
            "cpf_cnpj_socio": s.get("cnpj_cpf_do_socio", ""),
            "qualificacao": s.get("qualificacao_socio", ""),
            "data_entrada": s.get("data_entrada_sociedade", "")
        }
        for s in qsa
    ]
