"""
Camada de cache/replay das chamadas externas (HTTP e LLM).

Três modos:
- "off"    : chama normalmente; registra a trilha (sem guardar corpos).
- "record" : chama, guarda request-key → resposta para replay posterior, e registra.
- "replay" : NÃO faz chamada externa; serve do store gravado (determinismo).

A trilha (registros()) entra no artefato como `external_calls` para auditoria.
Headers (que contêm a API key) nunca são gravados nem registrados.
"""
import json
import hashlib

import httpx

_modo = "off"          # off | record | replay
_store = {}            # chave_sha256 → valor serializável
_registros = []        # trilha compacta {tipo, rotulo, fonte, status}


class ReplayMiss(RuntimeError):
    """Chamada externa exigida em replay mas ausente no store."""


def configurar(modo: str = "off", store: dict = None):
    """Inicia uma sessão de cache. Chamar no começo de cada execução."""
    global _modo, _store, _registros
    if modo not in ("off", "record", "replay"):
        raise ValueError(f"modo inválido: {modo}")
    _modo = modo
    _store = dict(store) if store else {}
    _registros = []


def modo() -> str:
    return _modo


def registros() -> list:
    """Trilha compacta das chamadas (para a coluna external_calls do artefato)."""
    return list(_registros)


def store() -> dict:
    """Store acumulado (para persistir e permitir replay posterior)."""
    return dict(_store)


def _chave(tipo: str, chave_params: dict) -> str:
    base = json.dumps({"t": tipo, "p": chave_params}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def executar(tipo: str, chave_params: dict, fn, rotulo: str = None, status=None):
    """
    Executa `fn` (uma chamada externa) sob a política do modo corrente.
    `chave_params` define a identidade da chamada (NÃO inclua segredos).
    `fn` deve retornar um valor JSON-serializável.
    """
    k = _chave(tipo, chave_params)
    if _modo == "replay":
        if k not in _store:
            raise ReplayMiss(f"replay: chamada ausente no store ({tipo} {rotulo or ''})")
        _registros.append({"tipo": tipo, "rotulo": rotulo, "fonte": "replay"})
        return _store[k]

    valor = fn()
    if _modo == "record":
        _store[k] = valor
    _registros.append({"tipo": tipo, "rotulo": rotulo, "fonte": "rede"})
    return valor


def http_get(url: str, headers: dict = None, params: dict = None, timeout: int = 15):
    """
    GET com cache/replay. Retorna (json, status_code).
    Headers ficam fora da chave e da trilha (segredo). Levanta em erro HTTP
    (record/off) ou ReplayMiss (replay) — os chamadores tratam o fallback.
    """
    def _chamar():
        r = httpx.get(url, headers=headers, params=params, timeout=timeout)
        r.raise_for_status()
        try:
            corpo = r.json()
        except Exception:
            corpo = None
        return {"status": r.status_code, "json": corpo}

    res = executar("http_get", {"url": url, "params": params or {}}, _chamar,
                   rotulo=f"GET {url}")
    return res["json"], res["status"]
