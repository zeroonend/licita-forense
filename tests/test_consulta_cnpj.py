"""Testes da consulta de CNPJ: limpeza, detecção SCP e roteamento de fonte."""
import skills.consulta_cnpj.skill as cc


def test_limpar_cnpj():
    assert cc._limpar_cnpj("37.083.255/0001-75") == "37083255000175"
    assert cc._limpar_cnpj(None) == ""


def test_e_scp():
    assert cc._e_scp("SEMPREVIDA MEDICINA INTENSIVA - SCP - HEJA")
    assert cc._e_scp("empresa scp teste")        # case-insensitive
    assert not cc._e_scp("ESCP CONSULTORIA LTDA")  # não casa dentro de palavra
    assert not cc._e_scp("BRAIN CARE S.A.")
    assert not cc._e_scp(None)


def test_roteamento_scp_usa_brasilapi_primeiro(monkeypatch):
    ordem = []
    monkeypatch.setattr(cc, "_consultar_cnpja", lambda c: (ordem.append("cnpja"), {"fonte": "cnpja"})[1])
    monkeypatch.setattr(cc, "_consultar_brasilapi", lambda c: (ordem.append("brasilapi"), {"fonte": "brasilapi"})[1])

    cc.consultar_cnpj("00000000000191", razao_social="X SCP Y")
    assert ordem == ["brasilapi"]


def test_roteamento_normal_usa_cnpja_primeiro(monkeypatch):
    ordem = []
    monkeypatch.setattr(cc, "_consultar_cnpja", lambda c: (ordem.append("cnpja"), {"fonte": "cnpja"})[1])
    monkeypatch.setattr(cc, "_consultar_brasilapi", lambda c: (ordem.append("brasilapi"), {"fonte": "brasilapi"})[1])

    cc.consultar_cnpj("00000000000191", razao_social="EMPRESA NORMAL LTDA")
    assert ordem == ["cnpja"]


def test_roteamento_normal_cai_para_brasilapi_em_falha(monkeypatch):
    ordem = []
    def cnpja_falha(c):
        ordem.append("cnpja")
        raise RuntimeError("erro")
    monkeypatch.setattr(cc, "_consultar_cnpja", cnpja_falha)
    monkeypatch.setattr(cc, "_consultar_brasilapi", lambda c: (ordem.append("brasilapi"), {"fonte": "brasilapi"})[1])

    r = cc.consultar_cnpj("00000000000191", razao_social="NORMAL")
    assert ordem == ["cnpja", "brasilapi"]
    assert r["fonte"] == "brasilapi"
