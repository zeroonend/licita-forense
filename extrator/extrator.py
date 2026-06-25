"""
Extrator de documentos — usa Claude API para extrair
estrutura de licitação de PDFs (ata, resultado, propostas).
"""
import re
import json
import warnings
import pdfplumber

from llm import gerar_texto

MAX_CHARS = 15_000        # tamanho de cada bloco enviado ao LLM
CHUNK_OVERLAP = 1_000     # sobreposição entre blocos (evita cortar uma empresa ao meio)
EXTRACTOR_PROMPT_VERSION = "extractor.v2"  # + fallback determinístico de número/data

# Fallbacks determinísticos para os metadados, quando o LLM não os extrai.
# Número do certame: "Pregão Eletrônico nº 021/2026", "Edital 021-2026", etc.
_RE_NUMERO = re.compile(
    r"(?:preg[ãa]o(?:\s+eletr[ôo]nico|\s+presencial)?|edital|concorr[êe]ncia|"
    r"tomada\s+de\s+pre[çc]os|licita[çc][ãa]o|processo(?:\s+administrativo)?)"
    r"[\s:]*n?[º°o.\-\s]*?(\d{1,5}\s*[/\-]\s*\d{4})",
    re.IGNORECASE,
)
_RE_DATA = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
# Número a partir do nome do arquivo: "020-2026 RESULTADO.pdf" → 020/2026.
_RE_NUM_ARQUIVO = re.compile(r"(\d{1,5})[\-_/](\d{4})")


def extrair_licitantes(caminho_pdf: str, nome_original: str = None) -> dict:
    """
    Dado um PDF de ata/resultado, retorna:
    {
        "meta": { "numero", "orgao", "objeto", "data" },
        "empresas": [{ "cnpj", "razao_social", "lance", "resultado" }]
    }

    Documentos longos são processados em blocos com sobreposição e mesclados,
    para não omitir licitantes ao final (antes havia truncamento em 15k chars).
    `nome_original` (quando o arquivo salvo perde o nome, ex.: upload web) ajuda
    o fallback de número do edital.
    """
    texto = _extrair_texto_pdf(caminho_pdf)
    if len(texto) <= MAX_CHARS:
        resultado = _extrair_com_llm(texto)
    else:
        partes = list(_chunks(texto, MAX_CHARS, CHUNK_OVERLAP))
        print(f"      [documento longo: {len(texto)} chars → {len(partes)} blocos]")
        resultados = []
        for i, parte in enumerate(partes):
            try:
                resultados.append(_extrair_com_llm(parte))
            except ValueError as e:
                warnings.warn(f"Bloco {i+1}/{len(partes)} falhou na extração: {e}")
        resultado = _merge_extracoes(resultados)

    # Preenche número/data via regex no texto (e nome do arquivo) se o LLM falhou.
    resultado["meta"] = _completar_meta(resultado.get("meta"), texto, nome_original)
    return resultado


def _completar_meta(meta: dict, texto: str, nome_original: str = None) -> dict:
    """Completa número e data da licitação por regex quando o LLM não os trouxe."""
    meta = dict(meta or {})
    if not meta.get("numero"):
        m = _RE_NUMERO.search(texto or "")
        if m:
            meta["numero"] = _norm_numero(m.group(1))
        elif nome_original:
            a = _RE_NUM_ARQUIVO.search(nome_original)
            if a:
                meta["numero"] = f"{a.group(1)}/{a.group(2)}"
    if not meta.get("data"):
        d = _RE_DATA.search(texto or "")
        if d:
            meta["data"] = d.group(1)
    return meta


def _norm_numero(bruto: str) -> str:
    """Normaliza '021 - 2026' / '021-2026' → '021/2026'."""
    return re.sub(r"\s+", "", bruto or "").replace("-", "/")


def _chunks(texto: str, tamanho: int, overlap: int):
    """Divide o texto em janelas de `tamanho` com `overlap` de sobreposição."""
    passo = max(1, tamanho - overlap)
    for ini in range(0, len(texto), passo):
        yield texto[ini:ini + tamanho]
        if ini + tamanho >= len(texto):
            break


def _chave_empresa(emp: dict) -> str:
    """Chave de deduplicação: CNPJ (dígitos) se houver, senão razão social."""
    cnpj = "".join(c for c in (emp.get("cnpj") or "") if c.isdigit())
    if cnpj:
        return "cnpj:" + cnpj
    return "nome:" + (emp.get("razao_social") or "").strip().upper()


def _merge_extracoes(resultados: list) -> dict:
    """Mescla extrações de múltiplos blocos: meta preenchida e empresas dedup."""
    meta = {}
    empresas = {}
    for r in resultados:
        for k, v in (r.get("meta") or {}).items():
            if meta.get(k) in (None, "") and v not in (None, ""):
                meta[k] = v
        for emp in r.get("empresas") or []:
            chave = _chave_empresa(emp)
            if chave == "nome:":
                continue  # sem CNPJ nem nome → descarta
            if chave not in empresas:
                empresas[chave] = dict(emp)
            else:
                for k, v in emp.items():
                    if empresas[chave].get(k) in (None, "") and v not in (None, ""):
                        empresas[chave][k] = v
    return {"meta": meta, "empresas": list(empresas.values())}


def _extrair_texto_pdf(caminho: str) -> str:
    texto = ""
    with pdfplumber.open(caminho) as pdf:
        for pagina in pdf.pages:
            texto += pagina.extract_text() or ""
    return texto


def _extrair_com_llm(texto: str) -> dict:
    prompt = f"""Você é um especialista em licitações públicas brasileiras.
Extraia as informações estruturadas do documento abaixo.

DOCUMENTO:
{texto}

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

    resposta = gerar_texto(prompt, max_tokens=2000, purpose="extracao")
    print(f"      [extração via {resposta.provider}/{resposta.model}]")

    texto_resposta = resposta.text.strip()
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
