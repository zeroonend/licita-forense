"""
Skill: consulta_dominio
Descobre o titular (owner) de um domínio via RDAP do registro.br.

Cobre apenas domínios .br (registro.br). Para outros TLDs, retorna None.
A consulta passa pela camada `cache` (record/replay) e é best-effort: em
qualquer falha ou redação (LGPD), retorna None sem quebrar o pipeline.
"""
import cache

RDAP_BASE = "https://rdap.registro.br"


def consultar_dono_dominio(dominio: str) -> str:
    """Retorna o identificador do titular (CNPJ/CPF/handle) ou None."""
    dominio = (dominio or "").strip().lower()
    if not dominio.endswith(".br"):
        return None  # registro.br cobre apenas .br
    try:
        data, _ = cache.http_get(f"{RDAP_BASE}/domain/{dominio}")
    except Exception as e:
        print(f"      [RDAP registro.br falhou para {dominio}: {e}]")
        return None
    return _extrair_titular(data)


def _extrair_titular(data: dict) -> str:
    """Extrai o titular do RDAP: prioriza publicIds (CNPJ/CPF), senão handle."""
    for ent in (data or {}).get("entities", []) or []:
        roles = ent.get("roles") or []
        if "registrant" in roles or "owner" in roles:
            for pid in ent.get("publicIds") or []:
                ident = pid.get("identifier")
                if ident:
                    return _norm(ident)
            if ent.get("handle"):
                return _norm(ent["handle"])
    return None


def _norm(valor: str) -> str:
    """Normaliza o identificador para comparação (alfanumérico, maiúsculo)."""
    return "".join(c for c in (valor or "") if c.isalnum()).upper()
