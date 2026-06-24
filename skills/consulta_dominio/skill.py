"""
Skill: consulta_dominio
Descobre o titular (owner) de um domínio via RDAP do registro.br.

Cobre apenas domínios .br (registro.br). Para outros TLDs, retorna None.
A consulta passa pela camada `cache` (record/replay) e é best-effort: em
qualquer falha ou redação (LGPD), retorna None sem quebrar o pipeline.
"""
import cache

RDAP_BASE = "https://rdap.registro.br"


def consultar_dono_dominio(dominio: str) -> dict:
    """
    Retorna o titular do domínio como {"id", "nome"} ou None.
    - id: CNPJ/CPF (mascarado p/ pessoa física por LGPD) normalizado, p/ agrupar.
    - nome: nome do titular (quando disponível no RDAP).
    """
    dominio = (dominio or "").strip().lower()
    if not dominio.endswith(".br"):
        return None  # registro.br cobre apenas .br
    try:
        data, _ = cache.http_get(f"{RDAP_BASE}/domain/{dominio}")
    except Exception as e:
        print(f"      [RDAP registro.br falhou para {dominio}: {e}]")
        return None
    return _extrair_titular(data)


def _extrair_titular(data: dict) -> dict:
    """Extrai {id, nome} do titular: id de publicIds/handle, nome do vcard 'fn'."""
    for ent in (data or {}).get("entities", []) or []:
        roles = ent.get("roles") or []
        if "registrant" in roles or "owner" in roles:
            ident = ""
            for pid in ent.get("publicIds") or []:
                if pid.get("identifier"):
                    ident = _norm(pid["identifier"])
                    break
            if not ident and ent.get("handle"):
                ident = _norm(ent["handle"])
            nome = _vcard_fn(ent)
            if ident or nome:
                return {"id": ident or None, "nome": nome or None}
    return None


def _vcard_fn(ent: dict) -> str:
    """Extrai o nome completo ('fn') do vcardArray de uma entidade RDAP."""
    va = ent.get("vcardArray")
    if va and len(va) > 1:
        for item in va[1]:
            if item and item[0] == "fn":
                return item[3]
    return None


def _norm(valor: str) -> str:
    """Normaliza o identificador para comparação (alfanumérico, maiúsculo)."""
    return "".join(c for c in (valor or "") if c.isalnum()).upper()
