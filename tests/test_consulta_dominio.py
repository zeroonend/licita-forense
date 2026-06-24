"""Testes da consulta de titular de domínio (RDAP registro.br), sem rede."""
import cache
from skills.consulta_dominio.skill import consultar_dono_dominio, _extrair_titular


def _vcard(nome):
    return ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", nome]]]


def test_extrair_titular_id_e_nome():
    data = {"entities": [
        {"roles": ["administrative"], "handle": "AAA"},
        {"roles": ["registrant"],
         "publicIds": [{"type": "cpf", "identifier": "***.997.861-**"}],
         "vcardArray": _vcard("JOSE DOMINGOS ALVES DE OLIVEIRA")},
    ]}
    assert _extrair_titular(data) == {"id": "997861", "nome": "JOSE DOMINGOS ALVES DE OLIVEIRA"}


def test_extrair_titular_fallback_handle_sem_nome():
    data = {"entities": [{"roles": ["registrant"], "handle": "FULANO-BR"}]}
    assert _extrair_titular(data) == {"id": "FULANOBR", "nome": None}


def test_extrair_titular_ausente():
    assert _extrair_titular({"entities": []}) is None
    assert _extrair_titular({}) is None


def test_nao_consulta_dominio_nao_br():
    # .com não é registro.br → None sem nenhuma chamada
    assert consultar_dono_dominio("empresa.com") is None


def test_consultar_dono_dominio_br(monkeypatch):
    rdap = {"entities": [{"roles": ["registrant"],
                          "publicIds": [{"type": "cnpj", "identifier": "99.888.777/0001-66"}],
                          "vcardArray": _vcard("GRUPO X LTDA")}]}
    monkeypatch.setattr(cache, "http_get", lambda url, **kw: (rdap, 200))
    assert consultar_dono_dominio("grupox.com.br") == {"id": "99888777000166", "nome": "GRUPO X LTDA"}
