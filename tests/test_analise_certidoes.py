"""Testes da skill de análise de certidões (LLM mockado, sem rede)."""
import json
import types

import pytest

from skills.analise_certidoes import skill as cert


def _mock_llm(monkeypatch, payload):
    def fake(prompt, max_tokens=600, purpose=None):
        texto = payload if isinstance(payload, str) else json.dumps(payload)
        return types.SimpleNamespace(text=texto, provider="mock", model="mock")
    monkeypatch.setattr(cert, "gerar_texto", fake)


def test_analisar_texto_negativa_e_regular(monkeypatch):
    _mock_llm(monkeypatch, {
        "cnpj": "37.083.255/0001-75", "esfera": "federal",
        "tipo": "Certidão Negativa", "situacao": "Negativa", "regular": True,
        "emitida_em": "01/06/2026", "valida_ate": "01/12/2026", "codigo_controle": "ABC123",
    })
    r = cert._analisar_texto("conteúdo da certidão")
    assert r["regular"] is True
    assert r["cnpj"] == "37083255000175"   # normalizado para dígitos
    assert r["esfera"] == "federal"
    assert r["fonte"] == "pdf"


def test_analisar_texto_positiva_e_irregular(monkeypatch):
    _mock_llm(monkeypatch, {"cnpj": "111", "esfera": "estadual",
                            "situacao": "Positiva", "regular": False})
    assert cert._analisar_texto("x")["regular"] is False


def test_analisar_texto_fallback_regex(monkeypatch):
    # LLM "falha" (JSON inválido) → regex preenche CNPJ e validade a partir do texto.
    _mock_llm(monkeypatch, "isto não é json")
    texto = "CERTIDÃO ... CNPJ 18.946.109/0001-81 ... válida até 31/12/2026"
    r = cert._analisar_texto(texto)
    assert r["cnpj"] == "18946109000181"
    assert r["valida_ate"] == "31/12/2026"
    assert r["regular"] is False   # sem dado → não assume regular


def test_resumir_vazio():
    assert cert.resumir_regularidade([])["regular"] is None


def test_resumir_todas_regulares():
    cs = [{"esfera": "federal", "regular": True, "valida_ate": "31/12/2999"},
          {"esfera": "fgts", "regular": True, "valida_ate": "31/12/2999"}]
    r = cert.resumir_regularidade(cs, data_referencia="01/06/2026")
    assert r["regular"] is True
    assert r["irregulares"] == [] and r["vencidas"] == []


def test_resumir_irregular():
    cs = [{"esfera": "federal", "regular": True, "valida_ate": "31/12/2999"},
          {"esfera": "municipal", "regular": False, "valida_ate": "31/12/2999"}]
    r = cert.resumir_regularidade(cs, data_referencia="01/06/2026")
    assert r["regular"] is False
    assert r["irregulares"] == ["municipal"]


def test_resumir_certidao_vencida_torna_irregular():
    cs = [{"esfera": "federal", "regular": True, "valida_ate": "01/01/2020"}]
    r = cert.resumir_regularidade(cs, data_referencia="01/06/2026")
    assert r["regular"] is False
    assert r["vencidas"] == ["federal"]
