"""
Extrator de documentos — usa Claude API para extrair
estrutura de licitação de PDFs (ata, resultado, propostas).
"""
import os
import json
import base64
import warnings
import anthropic
import pdfplumber

MAX_CHARS = 15_000


def extrair_licitantes(caminho_pdf: str) -> dict:
    """
    Dado um PDF de ata/resultado, retorna:
    {
        "meta": { "numero", "orgao", "objeto", "data" },
        "empresas": [{ "cnpj", "razao_social", "lance", "resultado" }]
    }
    """
    texto = _extrair_texto_pdf(caminho_pdf)
    return _extrair_com_claude(texto)


def _extrair_texto_pdf(caminho: str) -> str:
    texto = ""
    with pdfplumber.open(caminho) as pdf:
        for pagina in pdf.pages:
            texto += pagina.extract_text() or ""
    return texto


def _extrair_com_claude(texto: str) -> dict:
    client = anthropic.Anthropic()

    if len(texto) > MAX_CHARS:
        warnings.warn(
            f"PDF tem {len(texto)} caracteres; truncado em {MAX_CHARS}. "
            "Licitantes ao final do documento podem ser omitidos — "
            "considere processar por páginas."
        )
    texto_truncado = texto[:MAX_CHARS]

    prompt = f"""Você é um especialista em licitações públicas brasileiras.
Extraia as informações estruturadas do documento abaixo.

DOCUMENTO:
{texto_truncado}

Retorne APENAS um JSON válido (sem markdown, sem explicação) com esta estrutura exata:
{{
  "meta": {{
    "numero": "número do pregão/licitação",
    "orgao": "nome do órgão",
    "objeto": "objeto da licitação",
    "data": "data no formato DD/MM/AAAA"
  }},
  "empresas": [
    {{
      "cnpj": "XX.XXX.XXX/XXXX-XX",
      "razao_social": "NOME DA EMPRESA LTDA",
      "lance": "R$ 0.000,00",
      "resultado": "1º lugar / 2º lugar / desclassificado / VENCEDOR"
    }}
  ]
}}

Regras:
- CNPJ sempre no formato com pontos, barra e traço
- Se não encontrar algum campo, use null
- Inclua TODAS as empresas participantes, inclusive desclassificadas
- Ordene pelo resultado (vencedor primeiro)"""

    resposta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    texto_resposta = resposta.content[0].text.strip()
    texto_resposta = _remover_cerca_markdown(texto_resposta)
    try:
        return json.loads(texto_resposta)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude retornou JSON inválido: {e}\nResposta: {texto_resposta[:300]}"
        )


def _remover_cerca_markdown(texto: str) -> str:
    """Remove cercas de código markdown (```json ... ```) que o modelo às vezes inclui."""
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    return texto.strip()
