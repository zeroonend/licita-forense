"""Testes da camada LLM: telemetria e ordem de fallback."""
import llm


def test_reset_e_telemetria():
    llm.reset_telemetria()
    assert llm.telemetria() == []


def test_registrar_grava_chamada():
    llm.reset_telemetria()
    res = llm._registrar(llm.LLMResult("texto", "gemini", "modelo-x"), "extracao", 2000)
    assert res.text == "texto"
    tele = llm.telemetria()
    assert len(tele) == 1
    assert tele[0] == {"purpose": "extracao", "provider": "gemini", "model": "modelo-x", "max_tokens": 2000}


def test_fallback_anthropic_para_gemini(monkeypatch):
    llm.reset_telemetria()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "y")

    def anthropic_falha(prompt, mt, temp):
        raise RuntimeError("sem credito")
    monkeypatch.setattr(llm, "_anthropic", anthropic_falha)
    monkeypatch.setattr(llm, "_gemini", lambda p, mt, t: llm.LLMResult("ok", "gemini", "g"))

    res = llm.gerar_texto("oi", max_tokens=10, purpose="laudo")
    assert res.provider == "gemini"
    assert llm.telemetria()[0]["purpose"] == "laudo"


def test_sem_provedor_levanta(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    try:
        llm.gerar_texto("oi")
        assert False, "deveria ter levantado"
    except RuntimeError as e:
        assert "Nenhum provedor" in str(e)
