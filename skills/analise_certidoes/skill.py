"""
Skill: analise_certidoes
Analisa certidões de regularidade fiscal dos licitantes (Federal RFB/PGFN, FGTS,
Trabalhista/CNDT, Estadual/SEFAZ, Municipal) a partir do PDF apresentado na
habilitação — reaproveita o motor LLM+pdfplumber do extrator.

Best-effort, como `consulta_dominio`: qualquer falha devolve None/registro vazio
sem quebrar o pipeline. O registro normalizado é a "fonte da verdade" do modelo,
preenchido hoje por PDF (`fonte="pdf"`) e, no futuro, por uma API paga
(Infosimples/SERPRO) que devolverá o mesmo formato — ver `buscar_certidoes_api`.
"""
import os
import re
import json
import datetime

import pdfplumber
from dotenv import load_dotenv
load_dotenv()

import cache
from llm import gerar_texto

CERTIDAO_PROMPT_VERSION = "certidao.v1"

# --- Fonte por API paga (Infosimples) --------------------------------------
# Agregador que resolve CAPTCHA e cobre as 3 esferas, devolvendo dados
# estruturados + o PDF oficial (site_receipts). Token em INFOSIMPLES_TOKEN.
INFOSIMPLES_BASE = "https://api.infosimples.com/api/v2/consultas/"
# Mapa esfera → (caminho da consulta, params extras). ATENÇÃO: confirme os
# caminhos exatos na documentação da SUA conta Infosimples — eles podem variar
# por consulta; a lógica de mapeamento abaixo independe disso.
_CONSULTAS_INFOSIMPLES = {
    "federal":     ("receita-federal/pgfn", {"preferencia_emissao": "2via"}),
    "fgts":        ("caixa/regularidade", {}),
    "trabalhista": ("tst/cndt", {}),
    # estadual depende da UF: caminho formatado com {uf} em minúsculas.
    "estadual":    ("sefaz/{uf}/certidao-debitos", {}),
    # municipal varia por município (cobertura parcial) — configure por cidade
    # em _CONSULTAS_MUNICIPAIS quando for usar.
}
_CONSULTAS_MUNICIPAIS = {}  # ex.: {"fortaleza-ce": "pref-ce-fortaleza/cnd"}

_RE_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
_RE_DATA = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")

_PROMPT = """Você é um especialista em certidões fiscais brasileiras.
Analise a certidão abaixo.

DOCUMENTO:
{texto}

Retorne APENAS um JSON válido (sem markdown, sem explicação) com esta estrutura:
{{
  "cnpj": "apenas os dígitos do CNPJ do contribuinte",
  "esfera": "federal | estadual | municipal | fgts | trabalhista",
  "tipo": "título da certidão",
  "situacao": "texto da situação (Negativa / Positiva / Positiva com efeitos de Negativa)",
  "regular": true,
  "emitida_em": "DD/MM/AAAA ou null",
  "valida_ate": "DD/MM/AAAA ou null",
  "codigo_controle": "código de autenticação/controle ou null"
}}

Regras de classificação de "regular":
- Certidão NEGATIVA (nada consta / sem pendências) → regular = true
- Certidão POSITIVA COM EFEITOS DE NEGATIVA (débitos com exigibilidade suspensa/parcelados) → regular = true
- Certidão POSITIVA (débitos exigíveis) → regular = false

Regras de "esfera":
- Receita Federal / RFB / PGFN / Dívida Ativa da União → federal
- FGTS / Caixa / CRF → fgts
- Trabalhista / TST / CNDT / débitos trabalhistas → trabalhista
- Estado / SEFAZ / Secretaria da Fazenda estadual → estadual
- Município / Prefeitura / tributos municipais / ISS → municipal"""


def analisar_certidao_pdf(caminho_pdf: str) -> dict:
    """Lê o PDF da certidão e devolve o registro normalizado (ou None em falha)."""
    try:
        texto = ""
        with pdfplumber.open(caminho_pdf) as pdf:
            for pagina in pdf.pages:
                texto += pagina.extract_text() or ""
    except Exception as e:  # noqa: BLE001 — best-effort
        print(f"      [falha ao ler certidão {caminho_pdf}: {e}]")
        return None
    return _analisar_texto(texto)


def _analisar_texto(texto: str) -> dict:
    """LLM → registro normalizado, com fallback de regex para CNPJ/datas."""
    if not (texto or "").strip():
        return None
    try:
        resposta = gerar_texto(_PROMPT.format(texto=texto[:15000]),
                               max_tokens=600, purpose="certidao")
        registro = json.loads(_remover_cerca_markdown(resposta.text.strip()))
    except Exception as e:  # noqa: BLE001 — best-effort, cai no fallback
        print(f"      [análise de certidão via LLM falhou: {e}]")
        registro = {}

    registro["cnpj"] = _so_digitos(registro.get("cnpj")) or _cnpj_do_texto(texto)
    if not registro.get("valida_ate"):
        registro["valida_ate"] = _ultima_data(texto)
    registro["regular"] = bool(registro.get("regular"))
    registro["fonte"] = "pdf"
    return registro


def resumir_regularidade(certidoes: list, data_referencia: str = None) -> dict:
    """
    Consolida as certidões de um licitante. `regular` final é True só se TODAS as
    certidões presentes são regulares e não estão vencidas na data de referência
    (data do certame; senão, hoje). None quando não há certidões.
    """
    certidoes = certidoes or []
    if not certidoes:
        return {"regular": None, "esferas": {}, "vencidas": [], "irregulares": []}

    ref = _parse_data(data_referencia) or datetime.date.today()
    esferas, irregulares, vencidas = {}, [], []
    for c in certidoes:
        esfera = c.get("esfera") or "?"
        regular = bool(c.get("regular"))
        esferas[esfera] = regular and esferas.get(esfera, True)
        if not regular:
            irregulares.append(esfera)
        venc = _parse_data(c.get("valida_ate"))
        if venc and venc < ref:
            vencidas.append(esfera)

    regular_final = not irregulares and not vencidas
    return {
        "regular": regular_final,
        "esferas": esferas,
        "vencidas": sorted(set(vencidas)),
        "irregulares": sorted(set(irregulares)),
    }


# ---- Fonte por API (Infosimples) -------------------------------------------
def buscar_certidoes_api(cnpj: str, uf: str = None, municipio: str = None) -> list:
    """
    Busca as certidões via Infosimples e devolve a MESMA estrutura de registro
    (fonte="infosimples"), incluindo a URL do PDF oficial em `comprovante`.

    Federal/FGTS/Trabalhista sempre; Estadual quando há `uf`; Municipal quando há
    `municipio` configurado em _CONSULTAS_MUNICIPAIS. Sem token → [] (o
    orquestrador avisa). Best-effort: falha em uma esfera não derruba as outras.
    """
    token = os.getenv("INFOSIMPLES_TOKEN")
    cnpj = _so_digitos(cnpj)
    if not token or not cnpj:
        return []

    alvos = [(e, p, dict(extra)) for e, (p, extra) in _CONSULTAS_INFOSIMPLES.items()
             if e != "estadual"]
    if uf:
        cam, extra = _CONSULTAS_INFOSIMPLES["estadual"]
        alvos.append(("estadual", cam.format(uf=uf.lower()), dict(extra)))
    chave_mun = (municipio or "").strip().lower()
    if chave_mun in _CONSULTAS_MUNICIPAIS:
        alvos.append(("municipal", _CONSULTAS_MUNICIPAIS[chave_mun], {}))

    registros = []
    for esfera, caminho, extra in alvos:
        try:
            resp, _ = cache.http_post(INFOSIMPLES_BASE + caminho,
                                      dados={"cnpj": cnpj, **extra},
                                      segredos={"token": token})
        except Exception as e:  # noqa: BLE001 — best-effort por esfera
            print(f"      [Infosimples {esfera} falhou para {cnpj}: {e}]")
            continue
        registro = _mapear_infosimples(esfera, cnpj, resp)
        if registro:
            registros.append(registro)
    return registros


def _mapear_infosimples(esfera: str, cnpj: str, resp: dict) -> dict:
    """Converte a resposta da Infosimples no registro normalizado, ou None."""
    if not resp or resp.get("code") != 200:
        return None
    data = (resp.get("data") or [{}])[0]
    situacao = (data.get("situacao") or data.get("normalizado_situacao")
                or data.get("descricao") or "")
    return {
        "cnpj": cnpj,
        "esfera": esfera,
        "tipo": data.get("certidao") or data.get("titulo") or "",
        "situacao": situacao,
        "regular": _classificar_regular(situacao, data),
        "emitida_em": data.get("emissao_data") or data.get("normalizado_emissao_data"),
        "valida_ate": data.get("validade_data") or data.get("normalizado_validade_data"),
        "codigo_controle": data.get("certidao_codigo") or data.get("normalizado_codigo_controle"),
        "comprovante": (resp.get("site_receipts") or [None])[0],  # PDF oficial
        "fonte": "infosimples",
    }


def _classificar_regular(situacao: str, data: dict = None) -> bool:
    """
    Semântica BR: Negativa e 'Positiva com efeitos de Negativa' = regular;
    Positiva (débito exigível) = irregular. Fallback: presença de débitos.
    """
    s = (situacao or "").lower()
    if "efeito" in s and "negativ" in s:   # positiva com efeitos de negativa
        return True
    if "negativ" in s:
        return True
    if "positiv" in s:
        return False
    data = data or {}
    debitos = (data.get("debitos_rfb") or []) + (data.get("debitos_pgfn") or [])
    return not debitos


# ---- helpers ---------------------------------------------------------------
def _remover_cerca_markdown(texto: str) -> str:
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    return texto.strip()


def _so_digitos(valor) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def _cnpj_do_texto(texto: str) -> str:
    m = _RE_CNPJ.search(texto or "")
    return _so_digitos(m.group(0)) if m else ""


def _ultima_data(texto: str) -> str:
    """Heurística: a validade costuma ser a última data do documento."""
    achados = _RE_DATA.findall(texto or "")
    return achados[-1] if achados else None


def _parse_data(valor: str):
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime((valor or "").strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return None
