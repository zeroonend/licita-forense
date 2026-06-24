"""Testes da consulta de titular de domínio (RDAP registro.br), sem rede."""
import cache
from skills.consulta_dominio.skill import consultar_dono_dominio, _extrair_titular


def test_extrair_titular_por_public_id():
    data = {"entities": [
        {"roles": ["administrative"], "handle": "AAA"},
        {"roles": ["registrant"], "handle": "BR-123",
         "publicIds": [{"type": "cnpj", "identifier": "12.345.678/0001-99"}]},
    ]}
    assert _extrair_titular(data) == "12345678000199"


def test_extrair_titular_fallback_handle():
    data = {"entities": [{"roles": ["registrant"], "handle": "FULANO-BR"}]}
    assert _extrair_titular(data) == "FULANOBR"


def test_extrair_titular_ausente():
    assert _extrair_titular({"entities": []}) is None
    assert _extrair_titular({}) is None


def test_nao_consulta_dominio_nao_br():
    # .com não é registro.br → None sem nenhuma chamada
    assert consultar_dono_dominio("empresa.com") is None


def test_consultar_dono_dominio_br(monkeypatch):
    rdap = {"entities": [{"roles": ["registrant"],
                          "publicIds": [{"type": "cnpj", "identifier": "99.888.777/0001-66"}]}]}
    monkeypatch.setattr(cache, "http_get", lambda url, **kw: (rdap, 200))
    assert consultar_dono_dominio("grupox.com.br") == "99888777000166"
