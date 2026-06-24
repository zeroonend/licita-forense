"""
Camada de LLM com fallback em cadeia.

Primário: Anthropic (Claude). Fallback: Google Gemini (tier grátis).
Sempre temperature=0 para reduzir variação entre execuções (valor probatório).
Registra qual provedor/modelo gerou cada resposta para rastreabilidade forense.

Uso:
    from llm import gerar_texto
    res = gerar_texto(prompt, max_tokens=2000)
    res.text      # texto gerado
    res.provider  # "anthropic" | "gemini"
    res.model     # id do modelo efetivamente usado
"""
import os
from dotenv import load_dotenv
load_dotenv()

ANTHROPIC_MODEL = "claude-sonnet-4-6"
# Modelo pinado (não alias "latest") para reprodutibilidade. O tier grátis do
# Gemini varia a quota por modelo; 3.1-flash-lite tem quota gratuita estável.
GEMINI_MODEL = "gemini-3.1-flash-lite"


class LLMResult:
    """Resultado de uma geração, com a fonte registrada."""
    def __init__(self, text: str, provider: str, model: str):
        self.text = text
        self.provider = provider
        self.model = model


def gerar_texto(prompt: str, max_tokens: int = 2000, temperature: float = 0) -> LLMResult:
    """
    Gera texto tentando os provedores em ordem (Anthropic → Gemini).
    Cai para o próximo provedor em qualquer falha do anterior (sem chave,
    sem crédito, erro de rede). Levanta RuntimeError se nenhum funcionar.
    """
    erros = []

    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return _anthropic(prompt, max_tokens, temperature)
        except Exception as e:
            erros.append(f"anthropic: {type(e).__name__}: {str(e)[:140]}")

    if os.getenv("GEMINI_API_KEY"):
        try:
            return _gemini(prompt, max_tokens, temperature)
        except Exception as e:
            erros.append(f"gemini: {type(e).__name__}: {str(e)[:140]}")

    if erros:
        raise RuntimeError("Todos os provedores LLM falharam. " + " | ".join(erros))
    raise RuntimeError(
        "Nenhum provedor LLM configurado. Defina ANTHROPIC_API_KEY e/ou "
        "GEMINI_API_KEY no .env."
    )


def _anthropic(prompt: str, max_tokens: int, temperature: float) -> LLMResult:
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return LLMResult(resp.content[0].text, "anthropic", ANTHROPIC_MODEL)


def _gemini(prompt: str, max_tokens: int, temperature: float) -> LLMResult:
    import time
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    config = types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        temperature=temperature,
    )
    # Retry curto em erros transitórios (503 high demand, 429 momentâneo).
    tentativas = 3
    for i in range(tentativas):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt, config=config
            )
            return LLMResult(resp.text, "gemini", GEMINI_MODEL)
        except Exception as e:
            transitorio = any(s in str(e) for s in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"))
            if transitorio and i < tentativas - 1:
                time.sleep(2 * (i + 1))
                continue
            raise
