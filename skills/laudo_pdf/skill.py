"""
Skill: laudo_pdf
Gera o laudo investigativo como PDF formatado (fpdf2, Python puro), com:
cabeçalho da licitação, score/risco, rede de vínculos desenhada, tabela de
licitantes, alertas (com empresas envolvidas), texto do laudo e rodapé de
rastreabilidade (modelos, ruleset, hash do PDF de entrada).
"""
import os
import math

from fpdf import FPDF

NIVEL_COR = {
    "CRÍTICO": (224, 82, 82),
    "ALTO": (224, 138, 82),
    "MÉDIO": (224, 196, 82),
    "BAIXO": (82, 196, 122),
}
COR_EMPRESA = (74, 144, 217)
COR_VINCULO = (224, 82, 82)


def gerar_pdf(artefato: dict, caminho_saida: str = None) -> str:
    """Renderiza o artefato `investigation_result.v1` em PDF e retorna o caminho."""
    lic = artefato.get("licitacao") or {}
    score = artefato.get("score") or {}
    grafo = artefato.get("grafo") or {}
    empresas = grafo.get("empresas") or []
    ex = artefato.get("execution") or {}
    laudo = artefato.get("laudo") or {}

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, _s("LAUDO INVESTIGATIVO DE LICITAÇÃO"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _s(f"Edital {lic.get('numero','-')}  |  {lic.get('orgao','-')}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5, _s(f"Objeto: {lic.get('objeto') or '-'}"))
    pdf.set_x(pdf.l_margin)
    pdf.cell(0, 5, _s(f"Data: {lic.get('data') or '-'}"), new_x="LMARGIN", new_y="NEXT")

    # Faixa de score/risco
    nivel = score.get("nivel_risco", "-")
    pdf.ln(2)
    pdf.set_fill_color(*NIVEL_COR.get(nivel, (120, 120, 120)))
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 9, _s(f"  Score {score.get('score_geral', 0)}/100   -   Risco {nivel}"
                      f"   -   {score.get('total_alertas', 0)} alertas"),
             new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.set_text_color(0, 0, 0)

    _desenhar_rede(pdf, empresas, score.get("alertas", []))
    _tabela_licitantes(pdf, empresas)
    _lista_alertas(pdf, empresas, score.get("alertas", []))
    _texto_laudo(pdf, laudo.get("text", ""))
    _rodape(pdf, ex)

    caminho = caminho_saida or os.path.join("laudos", f"laudo_{ex.get('id', 'sem-id')}.pdf")
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    pdf.output(caminho)
    return caminho


def _desenhar_rede(pdf, empresas, alertas):
    """Desenha os licitantes em círculo e liga, em vermelho, os pares com alerta."""
    licit = [e for e in empresas if (e.get("cnpj") or e.get("razao_social"))]
    n = len(licit)
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _s("Rede de vínculos detectados"), new_x="LMARGIN", new_y="NEXT")
    if n == 0:
        return
    y0 = pdf.get_y()
    W, H = 180, 92
    cx = pdf.l_margin + W / 2
    cy = y0 + H / 2
    r = min(W, H) / 2 - 24

    pos, bycnpj, byname = {}, {}, {}
    for i, e in enumerate(licit):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        pos[i] = (cx + r * math.cos(ang), cy + r * math.sin(ang))
        bycnpj["".join(c for c in (e.get("cnpj", "") or "") if c.isdigit())] = i
        byname[(e.get("razao_social", "") or "").upper()] = i

    # Arestas (alertas que ligam 2+ licitantes)
    pdf.set_draw_color(*COR_VINCULO)
    pdf.set_line_width(0.5)
    for a in alertas or []:
        idxs = []
        for xv in a.get("empresas", []) or []:
            d = "".join(c for c in str(xv) if c.isdigit())
            j = bycnpj.get(d) if d else None
            if j is None:
                j = byname.get(str(xv).upper())
            if j is not None and j not in idxs:
                idxs.append(j)
        for p in range(len(idxs)):
            for q in range(p + 1, len(idxs)):
                (x1, y1), (x2, y2) = pos[idxs[p]], pos[idxs[q]]
                pdf.line(x1, y1, x2, y2)

    # Nós
    pdf.set_draw_color(40, 40, 40)
    pdf.set_line_width(0.2)
    pdf.set_fill_color(*COR_EMPRESA)
    pdf.set_font("Helvetica", "", 7)
    for i, e in enumerate(licit):
        x, y = pos[i]
        pdf.ellipse(x - 3, y - 3, 6, 6, style="FD")
        nome = _s((e.get("razao_social") or e.get("cnpj") or "")[:18])
        lx = max(pdf.l_margin, min(x - 18, pdf.l_margin + W - 36))
        pdf.set_xy(lx, y + 3.5)
        pdf.cell(36, 4, nome, align="C")
    pdf.set_draw_color(0, 0, 0)
    pdf.set_xy(pdf.l_margin, y0 + H)  # reseta x também (set_y sozinho não reseta)


def _tabela_licitantes(pdf, empresas):
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _s("Licitantes investigados"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(235, 235, 235)
    larg = (78, 42, 35, 35)
    for t, w in zip(("Empresa", "CNPJ", "Lance", "Resultado"), larg):
        pdf.cell(w, 6, _s(t), border=1, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    for e in empresas:
        linha = (
            (e.get("razao_social") or "-")[:46],
            e.get("cnpj") or "-",
            str(e.get("lance") or "-")[:18],
            str(e.get("resultado") or "-")[:18],
        )
        for v, w in zip(linha, larg):
            pdf.cell(w, 6, _s(v), border=1)
        pdf.ln()
    pdf.ln(2)


def _lista_alertas(pdf, empresas, alertas):
    nomes = {"".join(c for c in (e.get("cnpj", "") or "") if c.isdigit()):
             (e.get("razao_social") or e.get("cnpj")) for e in empresas}
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _s("Alertas detectados"), new_x="LMARGIN", new_y="NEXT")
    if not alertas:
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 6, _s("Nenhum alerta."), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        return
    for a in alertas:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 5, _s(f"[{a.get('tipo', '-')}]  +{a.get('peso', 0)}"),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, _s(a.get("descricao", "")))
        envolvidas = [nomes.get("".join(c for c in str(x) if c.isdigit()), x)
                      for x in a.get("empresas", []) or []]
        if envolvidas:
            pdf.set_text_color(90, 90, 90)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 5, _s("Empresas: " + "  -  ".join(map(str, envolvidas))))
            pdf.set_text_color(0, 0, 0)
        pdf.ln(1)
    pdf.ln(1)


def _texto_laudo(pdf, texto):
    if not (texto or "").strip():
        return
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _s("Laudo"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for linha in str(texto).split("\n"):
        limpa = linha.replace("**", "").replace("`", "").lstrip("#").strip()
        if not limpa:
            pdf.ln(2)
            continue
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, _s(limpa))


def _rodape(pdf, ex):
    comp = (ex or {}).get("components", {}) or {}
    pdf.ln(3)
    pdf.set_draw_color(180, 180, 180)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(1)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(120, 120, 120)
    sha = (ex.get("input_pdf_sha256") or "")[:16]
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 4, _s(
        f"Execução {ex.get('id', '-')} | status {ex.get('status', '-')} | "
        f"ruleset {comp.get('ruleset_version', '-')} | "
        f"extrator {comp.get('extractor_model', '-')} | laudo {comp.get('laudo_model', '-')} | "
        f"PDF sha256 {sha}..."))
    pdf.set_text_color(0, 0, 0)


def _s(txt) -> str:
    """Torna o texto seguro para as fontes core (latin-1) do fpdf2."""
    repl = {"—": "-", "–": "-", "…": "...", "•": "-", "·": "-",
            "’": "'", "‘": "'", "“": '"', "”": '"', " ": " "}
    t = str(txt if txt is not None else "")
    for k, v in repl.items():
        t = t.replace(k, v)
    return t.encode("latin-1", "replace").decode("latin-1")
