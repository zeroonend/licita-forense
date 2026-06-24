"""
Skill: scoring_conluio
Regras determinísticas baseadas na metodologia do CADE.
Totalmente determinístico: mesmo grafo → mesmo score (sem LLM).
"""
import re
import unicodedata
from datetime import datetime

RULESET_VERSION = "scoring_conluio.v3"  # 7 regras (inclui lance redondo/cobertura)
JANELA_ABERTURA_DIAS = 90    # aberturas dentro desta janela são consideradas próximas
LIMIAR_COBERTURA = 0.005     # lances com diferença relativa <= 0.5% → lance de cobertura
PASSO_REDONDO = 1000         # valor "redondo" = múltiplo de R$ 1.000 sem centavos


PESOS = {
    "socio_em_comum": 35,
    "rede_externa_compartilhada": 25,
    "ponte_externa_aprofundada": 20,
    "mesmo_endereco": 20,
    "cnpj_sequencial": 15,
    "abertura_proxima": 10,
    "mesmo_contador": 10,
    "lance_redondo": 5,
    "subcontratacao_perdedor": 5,
}

SCORE_CRITICO = 50
SCORE_ALTO = 30
SCORE_MEDIO = 15


def calcular_score(grafo: dict) -> dict:
    """
    Calcula score de conluio para o conjunto de licitantes.
    Retorna score, nível de risco, alertas e justificativas.
    """
    alertas = []
    score = 0

    empresas = grafo.get("empresas", [])
    vinculos = grafo.get("vinculos_suspeitos", [])

    # Regra 1: Sócio em comum
    for vinculo in vinculos:
        alerta = {
            "tipo": "socio_em_comum",
            "peso": PESOS["socio_em_comum"],
            "descricao": f"Sócio '{vinculo['socio']}' aparece em {len(vinculo['empresas'])} empresas licitantes: {', '.join(vinculo['empresas'])}",
            "empresas": vinculo["empresas"]
        }
        alertas.append(alerta)
        score += PESOS["socio_em_comum"]

    # Regra 2: Mesmo endereço entre licitantes.
    # Normaliza para forma canônica (sem acento/pontuação, caixa única, espaços
    # colapsados) para não dar falso-negativo entre fontes diferentes (CNPJá × BrasilAPI).
    enderecos = {}
    for emp in empresas:
        end = _normalizar_endereco(emp.get("endereco", ""))
        if end:
            enderecos.setdefault(end, []).append(emp.get("cnpj", ""))
    for end, cnpjs in enderecos.items():
        if len(cnpjs) > 1:
            alertas.append({
                "tipo": "mesmo_endereco",
                "peso": PESOS["mesmo_endereco"],
                "descricao": f"Mesmo endereço entre licitantes: {end}",
                "empresas": cnpjs
            })
            score += PESOS["mesmo_endereco"]

    # Regra 3: CNPJs sequenciais (8 primeiros dígitos próximos).
    # Só considera empresas com raiz numérica de 8 dígitos; CNPJs vazios/ilegíveis
    # (campo null da extração) são ignorados para não derrubar o pipeline em int().
    raizes = []
    for emp in empresas:
        raiz = _so_digitos(emp.get("cnpj", ""))[:8]
        if len(raiz) == 8:
            raizes.append((raiz, emp.get("cnpj", "")))
    raizes_sorted = sorted(raizes, key=lambda x: x[0])
    for i in range(len(raizes_sorted) - 1):
        if abs(int(raizes_sorted[i][0]) - int(raizes_sorted[i+1][0])) < 1000:
            alertas.append({
                "tipo": "cnpj_sequencial",
                "peso": PESOS["cnpj_sequencial"],
                "descricao": f"CNPJs possivelmente sequenciais: {raizes_sorted[i][1]} e {raizes_sorted[i+1][1]}",
                "empresas": [raizes_sorted[i][1], raizes_sorted[i+1][1]]
            })
            score += PESOS["cnpj_sequencial"]

    # Regra 4: Rede externa compartilhada (busca reversa de sócios).
    # Cruza a expansão da busca reversa com o índice de sócios: se uma empresa
    # de FORA do edital concentra sócios de dois ou mais licitantes distintos,
    # há um vínculo oculto que os licitantes não declaram entre si.
    socios_index = grafo.get("socios_index", {})
    expansao = grafo.get("expansao_socios", {})
    # A busca reversa devolve raiz de CNPJ (8 dígitos); comparamos por raiz.
    raizes_licitantes = {_so_digitos(e.get("cnpj", ""))[:8] for e in empresas}
    externas_idx = {}  # raiz_externa → {"razao", "licitantes": set, "socios": set}
    for chave, externas in expansao.items():
        licitantes_do_socio = socios_index.get(chave, [])
        if not licitantes_do_socio:
            continue
        nome_socio = chave.split("|", 1)[1] if "|" in chave else chave
        for ext in externas:
            cnpj_ext = _so_digitos(ext.get("cnpj", ""))[:8]
            # Ignora empresas do próprio edital — já cobertas por outras regras.
            if not cnpj_ext or cnpj_ext in raizes_licitantes:
                continue
            reg = externas_idx.setdefault(cnpj_ext, {
                "razao": ext.get("razao_social", ""),
                "licitantes": set(),
                "socios": set(),
            })
            reg["licitantes"].update(licitantes_do_socio)
            reg["socios"].add(nome_socio)
    for cnpj_ext, reg in externas_idx.items():
        if len(reg["licitantes"]) > 1:
            alertas.append({
                "tipo": "rede_externa_compartilhada",
                "peso": PESOS["rede_externa_compartilhada"],
                "descricao": (
                    f"Empresa externa '{reg['razao'] or cnpj_ext}' ({cnpj_ext}) "
                    f"conecta {len(reg['licitantes'])} licitantes via sócios: "
                    f"{', '.join(sorted(reg['socios']))}"
                ),
                "empresas": sorted(reg["licitantes"]),
                "empresa_externa": cnpj_ext
            })
            score += PESOS["rede_externa_compartilhada"]

    # Regra 5: Abertura próxima — empresas constituídas em datas muito próximas
    # podem indicar criação coordenada de licitantes "de fachada".
    datas = []
    for emp in empresas:
        d = _parse_data(emp.get("data_abertura"))
        if d:
            datas.append((d, emp.get("cnpj", "")))
    datas.sort(key=lambda x: x[0])
    for i in range(len(datas) - 1):
        delta = abs((datas[i][0] - datas[i + 1][0]).days)
        if delta <= JANELA_ABERTURA_DIAS:
            alertas.append({
                "tipo": "abertura_proxima",
                "peso": PESOS["abertura_proxima"],
                "descricao": (
                    f"Aberturas próximas ({delta} dias) entre {datas[i][1]} "
                    f"({datas[i][0].isoformat()}) e {datas[i+1][1]} "
                    f"({datas[i+1][0].isoformat()})"
                ),
                "empresas": [datas[i][1], datas[i + 1][1]]
            })
            score += PESOS["abertura_proxima"]

    # Regra 6: Ponte via aprofundamento — sócio (pessoa/empresa) que aparece em
    # empresas externas aprofundadas (ex.: SCPs) ligadas a 2+ licitantes distintos.
    # Capta vínculo oculto de 2º nível (ex.: mesma pessoa em SCPs de licitantes
    # diferentes). Só roda quando o aprofundamento foi executado.
    aprof = grafo.get("aprofundamento", {})
    if aprof:
        cnpjs_lic = {_so_digitos(e.get("cnpj", "")): e.get("razao_social", "") for e in empresas}
        socios_lic = {}
        for e in empresas:
            for s in e.get("qsa", []):
                nm = (s.get("nome_socio", "") or "").upper()
                if nm:
                    socios_lic[nm] = e.get("razao_social", "")

        def _assoc_licitantes(qsa):
            lic = set()
            for s in qsa:
                doc = _so_digitos(s.get("cpf_cnpj_socio", ""))
                nm = (s.get("nome_socio", "") or "").upper()
                if doc and doc in cnpjs_lic:
                    lic.add(cnpjs_lic[doc])
                elif nm and nm in socios_lic:
                    lic.add(socios_lic[nm])
            return lic

        pontes = {}
        for info in aprof.values():
            qsa = info.get("qsa", [])
            lic = _assoc_licitantes(qsa)
            if not lic:
                continue
            for s in qsa:
                doc = _so_digitos(s.get("cpf_cnpj_socio", ""))
                nm = (s.get("nome_socio", "") or "").upper()
                if doc and doc in cnpjs_lic:
                    continue  # o próprio licitante não é "sócio-ponte"
                if not nm and not doc:
                    continue
                chave = doc if len(doc) >= 8 else ("N:" + nm)
                reg = pontes.setdefault(chave, {"nome": nm or doc, "licitantes": set(), "externas": set()})
                reg["licitantes"] |= lic
                reg["externas"].add(info.get("razao_social", ""))
        for reg in pontes.values():
            if len(reg["licitantes"]) >= 2:
                alertas.append({
                    "tipo": "ponte_externa_aprofundada",
                    "peso": PESOS["ponte_externa_aprofundada"],
                    "descricao": (
                        f"'{reg['nome']}' conecta {len(reg['licitantes'])} licitantes "
                        f"via empresas externas aprofundadas (SCPs): "
                        f"{', '.join(sorted(reg['externas'])[:4])}"
                    ),
                    "empresas": sorted(reg["licitantes"]),
                })
                score += PESOS["ponte_externa_aprofundada"]

    # Regra 7: Lance de cobertura / valores redondos.
    # - Cobertura: dois lances quase idênticos (diferença relativa <= 0,5%)
    #   sugerem proposta "de cobertura" combinada.
    # - Redondos: dois ou mais lances em valores redondos (múltiplos de R$1.000
    #   sem centavos) é um padrão atípico para propostas reais.
    lances = []
    for emp in empresas:
        v = _parse_valor(emp.get("lance"))
        if v and v > 0:
            lances.append((v, emp.get("cnpj", "")))

    lances_ord = sorted(lances, key=lambda x: x[0])
    for i in range(len(lances_ord) - 1):
        a, ca = lances_ord[i]
        b, cb = lances_ord[i + 1]
        if abs(a - b) / max(a, b) <= LIMIAR_COBERTURA:
            alertas.append({
                "tipo": "lance_cobertura",
                "peso": PESOS["lance_redondo"],
                "descricao": (
                    f"Lances quase idênticos (dif. {abs(a-b)/max(a,b)*100:.2f}%): "
                    f"{ca} (R$ {a:,.2f}) e {cb} (R$ {b:,.2f})"
                ),
                "empresas": [ca, cb],
            })
            score += PESOS["lance_redondo"]

    redondos = [(v, c) for v, c in lances if v == int(v) and int(v) % PASSO_REDONDO == 0]
    if len(redondos) >= 2:
        alertas.append({
            "tipo": "lance_redondo",
            "peso": PESOS["lance_redondo"],
            "descricao": (
                "Múltiplos lances em valores redondos (múltiplos de "
                f"R$ {PASSO_REDONDO:,}): " + ", ".join(f"{c} (R$ {v:,.2f})" for v, c in redondos)
            ),
            "empresas": [c for _, c in redondos],
        })
        score += PESOS["lance_redondo"]

    # Classificação usa o score bruto (aditivo); score_geral é normalizado a 0–100
    # para exibição, mas score_bruto preserva o valor real para auditoria.
    nivel = _classificar_nivel(score)

    return {
        "score_geral": min(score, 100),
        "score_bruto": score,
        "nivel_risco": nivel,
        "alertas": alertas,
        "total_alertas": len(alertas),
        "ruleset_version": RULESET_VERSION
    }


def _so_digitos(valor: str) -> str:
    """Normaliza um CNPJ/CPF para apenas dígitos (formato canônico de comparação)."""
    return "".join(c for c in (valor or "") if c.isdigit())


def _normalizar_endereco(valor: str) -> str:
    """
    Forma canônica de um endereço: sem acentos, caixa única, só alfanumérico,
    espaços colapsados. Reduz falso-negativo entre fontes com formatos distintos.
    """
    s = unicodedata.normalize("NFKD", valor or "").encode("ascii", "ignore").decode()
    s = "".join(ch if ch.isalnum() else " " for ch in s.upper())
    return " ".join(s.split())


def _parse_valor(valor) -> float:
    """
    Converte um lance em float. Aceita formato BR ('R$ 1.234.567,89') e número.
    Retorna None se não houver valor numérico reconhecível.
    """
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = re.sub(r"[^0-9,\.]", "", str(valor))
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")  # BR: . milhar, , decimal
    try:
        return float(s)
    except ValueError:
        return None


def _parse_data(valor: str):
    """Converte data ISO (AAAA-MM-DD) ou BR (DD/MM/AAAA) em date; None se inválida."""
    s = (valor or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _classificar_nivel(score: int) -> str:
    if score >= SCORE_CRITICO:
        return "CRÍTICO"
    elif score >= SCORE_ALTO:
        return "ALTO"
    elif score >= SCORE_MEDIO:
        return "MÉDIO"
    return "BAIXO"
