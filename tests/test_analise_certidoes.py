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


# ---- provider Infosimples ----
def test_classificar_regular():
    assert cert._classificar_regular("Certidão Negativa") is True
    assert cert._classificar_regular("Positiva com efeitos de Negativa") is True
    assert cert._classificar_regular("Certidão Positiva") is False
    assert cert._classificar_regular("", {"debitos_rfb": [{"x": 1}]}) is False
    assert cert._classificar_regular("", {}) is True


def test_buscar_api_sem_token_retorna_vazio(monkeypatch):
    monkeypatch.delenv("INFOSIMPLES_TOKEN", raising=False)
    assert cert.buscar_certidoes_api("37083255000175", uf="GO") == []


def test_buscar_api_mapeia_resposta(monkeypatch):
    monkeypatch.setenv("INFOSIMPLES_TOKEN", "tok-123")
    chamadas = []

    def fake_post(url, dados=None, segredos=None, timeout=30):
        chamadas.append((url, dados, segredos))
        esfera_neg = {"code": 200, "site_receipts": ["https://infosimples/pdf"],
                      "data": [{"situacao": "Negativa", "validade_data": "01/12/2026",
                                "certidao_codigo": "ABC"}]}
        # federal vem Positiva (irregular), o resto Negativa
        if "pgfn" in url:
            return ({"code": 200, "site_receipts": ["https://infosimples/fed"],
                     "data": [{"situacao": "Positiva", "validade_data": "01/12/2026"}]}, 200)
        return (esfera_neg, 200)
    monkeypatch.setattr(cert.cache, "http_post", fake_post)

    regs = cert.buscar_certidoes_api("37.083.255/0001-75", uf="GO")
    esferas = {r["esfera"] for r in regs}
    assert {"federal", "fgts", "trabalhista", "estadual"} <= esferas
    fed = next(r for r in regs if r["esfera"] == "federal")
    assert fed["regular"] is False and fed["fonte"] == "infosimples"
    assert fed["comprovante"] == "https://infosimples/fed"
    # token foi enviado como segredo (fora de `dados`), CNPJ normalizado em dados
    assert all(s["token"] == "tok-123" for _, _, s in chamadas)
    assert all(d["cnpj"] == "37083255000175" for _, d, _ in chamadas)
