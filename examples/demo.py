"""
Demo offline do licita-forense — roda o motor determinístico (sem APIs/chaves)
sobre um caso sintético de licitação com conluio plantado e gera:

  - examples/exemplo_resultado.json  → carregue no frontend/organograma.html
  - examples/organograma_exemplo.svg → render estático do grafo (abre no navegador)

Uso (após `pip install -r requirements.txt`):

    python examples/demo.py

Exercita o CÓDIGO REAL de `construir_grafo` (cruzamento de sócios) e
`calcular_score` (regras CADE) — as partes determinísticas, com valor probatório.
A extração de PDF, as consultas CNPJá e o laudo dependem de chaves e ficam fora
deste demo.
"""
import os
import sys
import json
import math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from orquestrador.main import construir_grafo
from skills.scoring_conluio.skill import calcular_score


# --- caso sintético: 3 licitantes, conluio plantado ---------------------------
# ALFA e BETA: mesmo sócio (João), mesmo endereço, CNPJs sequenciais.
# ALFA e GAMA: outra sócia em comum (Maria). BETA e GAMA também sequenciais.
DADOS_EMPRESAS = [
    {
        "cnpj": "11.111.111/0001-00",
        "razao_social": "ALFA COMERCIO E SERVICOS LTDA",
        "situacao": "ATIVA",
        "data_abertura": "2019-03-10",
        "endereco": "RUA DAS ACACIAS, 100, GOIANIA, GO",
        "lance": "R$ 98.000,00",
        "resultado": "VENCEDOR",
        "qsa": [
            {"nome_socio": "JOAO DA SILVA", "cpf_cnpj_socio": "***123456**", "qualificacao": "Sócio-Administrador"},
            {"nome_socio": "MARIA SOUZA", "cpf_cnpj_socio": "***222333**", "qualificacao": "Sócia"},
        ],
    },
    {
        "cnpj": "11.111.112/0001-00",
        "razao_social": "BETA SOLUCOES EIRELI",
        "situacao": "ATIVA",
        "data_abertura": "2019-03-12",
        "endereco": "RUA DAS ACACIAS, 100, GOIANIA, GO",
        "lance": "R$ 99.500,00",
        "resultado": "2º lugar",
        "qsa": [
            {"nome_socio": "JOAO DA SILVA", "cpf_cnpj_socio": "***123456**", "qualificacao": "Titular"},
            {"nome_socio": "PEDRO LIMA", "cpf_cnpj_socio": "***444555**", "qualificacao": "Sócio"},
        ],
    },
    {
        "cnpj": "11.111.113/0001-00",
        "razao_social": "GAMA DISTRIBUIDORA LTDA",
        "situacao": "ATIVA",
        "data_abertura": "2020-07-01",
        "endereco": "AV. CENTRAL, 500, APARECIDA DE GOIANIA, GO",
        "lance": "R$ 99.900,00",
        "resultado": "3º lugar",
        "qsa": [
            {"nome_socio": "MARIA SOUZA", "cpf_cnpj_socio": "***222333**", "qualificacao": "Sócia"},
            {"nome_socio": "JOAO DA SILVA", "cpf_cnpj_socio": "***123456**", "qualificacao": "Sócio"},
        ],
    },
]


def imprimir_relatorio(grafo: dict, score: dict) -> None:
    print("=" * 64)
    print("VÍNCULOS SUSPEITOS (sócios em comum entre licitantes)")
    print("=" * 64)
    for v in grafo["vinculos_suspeitos"]:
        print(f"  • {v['socio']}  →  {len(v['empresas'])} empresas: {', '.join(v['empresas'])}")

    print("\n" + "=" * 64)
    print("ALERTAS (metodologia CADE)")
    print("=" * 64)
    for a in score["alertas"]:
        print(f"  [{a['tipo']:18}] +{a['peso']:>3}  {a['descricao']}")

    print("\n" + "=" * 64)
    print("SCORE")
    print("=" * 64)
    print(f"  score_geral (0–100): {score['score_geral']}")
    print(f"  score_bruto         : {score['score_bruto']}")
    print(f"  nível de risco      : {score['nivel_risco']}")
    print(f"  total de alertas    : {score['total_alertas']}")


# --- render estático do organograma em SVG (mesmas cores do frontend) ---------
CORES = {
    "bg": "#0f1117", "panel": "#1a1d27", "border": "#2a2e3a", "text": "#e4e6eb",
    "muted": "#8a8f9c", "empresa": "#4a90d9", "socio": "#d99a4a", "vinc": "#e05252",
}


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _trunc(s: str, k: int) -> str:
    s = s or ""
    return s if len(s) <= k else s[:k] + "…"


def gerar_svg(grafo: dict, score: dict) -> str:
    susp = {f"{v['cpf']}|{v['socio'].upper()}" for v in grafo["vinculos_suspeitos"]}

    nodes, idx, edges = [], {}, []
    for e in grafo["empresas"]:
        idx[e["cnpj"]] = len(nodes)
        nodes.append({"tipo": "empresa", "label": e["razao_social"], "r": 18})
    for e in grafo["empresas"]:
        for s in e.get("qsa", []):
            chave = f"{s.get('cpf_cnpj_socio', '')}|{s.get('nome_socio', '').upper()}"
            sid = "soc:" + chave
            if sid not in idx:
                idx[sid] = len(nodes)
                nodes.append({"tipo": "socio", "label": s.get("nome_socio", ""), "r": 11})
            edges.append((idx[sid], idx[e["cnpj"]], chave in susp))

    # layout force-directed determinístico (sem random)
    GX0, GY0, GW, GH = 340, 30, 840, 660
    cx, cy = GX0 + GW / 2, GY0 + GH / 2
    n = len(nodes)
    for i, nd in enumerate(nodes):
        ang = 2 * math.pi * i / n
        nd["x"] = cx + 180 * math.cos(ang)
        nd["y"] = cy + 180 * math.sin(ang)

    K_REP, K_ATT, GRAV, STEP = 90000.0, 0.02, 0.02, 0.85
    for _ in range(600):
        fx = [0.0] * n
        fy = [0.0] * n
        for i in range(n):
            for j in range(i + 1, n):
                dx = nodes[i]["x"] - nodes[j]["x"]
                dy = nodes[i]["y"] - nodes[j]["y"]
                d2 = dx * dx + dy * dy + 0.01
                d = math.sqrt(d2)
                f = K_REP / d2
                ux, uy = dx / d, dy / d
                fx[i] += ux * f; fy[i] += uy * f
                fx[j] -= ux * f; fy[j] -= uy * f
        for a, b, _s in edges:
            dx = nodes[b]["x"] - nodes[a]["x"]
            dy = nodes[b]["y"] - nodes[a]["y"]
            fx[a] += dx * K_ATT; fy[a] += dy * K_ATT
            fx[b] -= dx * K_ATT; fy[b] -= dy * K_ATT
        for i in range(n):
            fx[i] += (cx - nodes[i]["x"]) * GRAV
            fy[i] += (cy - nodes[i]["y"]) * GRAV
            nodes[i]["x"] += max(-15, min(15, fx[i] * STEP))
            nodes[i]["y"] += max(-15, min(15, fy[i] * STEP))
            nodes[i]["x"] = max(GX0 + 30, min(GX0 + GW - 30, nodes[i]["x"]))
            nodes[i]["y"] = max(GY0 + 30, min(GY0 + GH - 30, nodes[i]["y"]))

    W, H = 1200, 720
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="Segoe UI, Arial, sans-serif">']
    o.append(f'<rect width="{W}" height="{H}" fill="{CORES["bg"]}"/>')
    o.append(f'<rect x="0" y="0" width="320" height="{H}" fill="{CORES["panel"]}"/>')
    o.append(f'<line x1="320" y1="0" x2="320" y2="{H}" stroke="{CORES["border"]}"/>')
    o.append(f'<text x="24" y="40" fill="{CORES["text"]}" font-size="20" font-weight="700">Licita Forense</text>')
    o.append(f'<text x="24" y="62" fill="{CORES["muted"]}" font-size="12">Organograma de vínculos societários</text>')
    o.append(f'<rect x="24" y="84" width="272" height="110" rx="10" fill="{CORES["bg"]}" stroke="{CORES["border"]}"/>')
    o.append(f'<text x="40" y="108" fill="{CORES["muted"]}" font-size="11">SCORE DE CONLUIO</text>')
    o.append(f'<text x="40" y="156" fill="{CORES["text"]}" font-size="44" font-weight="800">{score["score_geral"]}</text>')
    o.append(f'<text x="150" y="150" fill="{CORES["muted"]}" font-size="12">bruto: {score["score_bruto"]}</text>')
    o.append(f'<rect x="40" y="168" width="{30 + len(score["nivel_risco"]) * 9}" height="22" rx="11" fill="{CORES["vinc"]}"/>')
    o.append(f'<text x="52" y="183" fill="{CORES["bg"]}" font-size="12" font-weight="700">{_esc(score["nivel_risco"])}</text>')
    o.append(f'<text x="24" y="222" fill="{CORES["muted"]}" font-size="11">ALERTAS DETECTADOS ({score["total_alertas"]})</text>')
    y = 236
    for a in score["alertas"]:
        o.append(f'<rect x="24" y="{y}" width="272" height="56" rx="4" fill="{CORES["bg"]}"/>')
        o.append(f'<rect x="24" y="{y}" width="3" height="56" fill="{CORES["vinc"]}"/>')
        o.append(f'<text x="36" y="{y + 18}" fill="{CORES["vinc"]}" font-size="10" font-weight="700">{_esc(a["tipo"].upper())}</text>')
        o.append(f'<text x="280" y="{y + 18}" fill="{CORES["muted"]}" font-size="10" text-anchor="end">+{a["peso"]}</text>')
        o.append(f'<text x="36" y="{y + 36}" fill="{CORES["text"]}" font-size="10">{_esc(_trunc(a["descricao"], 44))}</text>')
        y += 64

    for a, b, s in edges:
        col = CORES["vinc"] if s else CORES["border"]
        dash = ' stroke-dasharray="5 3"' if s else ''
        wdt = 2.4 if s else 1.4
        o.append(f'<line x1="{nodes[a]["x"]:.1f}" y1="{nodes[a]["y"]:.1f}" '
                 f'x2="{nodes[b]["x"]:.1f}" y2="{nodes[b]["y"]:.1f}" '
                 f'stroke="{col}" stroke-width="{wdt}"{dash}/>')
    for nd in nodes:
        fill = CORES["empresa"] if nd["tipo"] == "empresa" else CORES["socio"]
        o.append(f'<circle cx="{nd["x"]:.1f}" cy="{nd["y"]:.1f}" r="{nd["r"]}" '
                 f'fill="{fill}" stroke="{CORES["bg"]}" stroke-width="2"/>')
        o.append(f'<text x="{nd["x"] + nd["r"] + 4:.1f}" y="{nd["y"] + 4:.1f}" '
                 f'fill="{CORES["text"]}" font-size="11">{_esc(_trunc(nd["label"], 26))}</text>')

    lx, ly = W - 210, H - 92
    o.append(f'<rect x="{lx}" y="{ly}" width="196" height="78" rx="8" fill="{CORES["panel"]}" stroke="{CORES["border"]}"/>')
    for i, (k, t) in enumerate([("empresa", "Empresa licitante"), ("socio", "Sócio"), ("vinc", "Vínculo suspeito")]):
        yy = ly + 22 + i * 20
        o.append(f'<circle cx="{lx + 18}" cy="{yy - 4}" r="6" fill="{CORES[k]}"/>')
        o.append(f'<text x="{lx + 34}" y="{yy}" fill="{CORES["text"]}" font-size="12">{t}</text>')

    o.append('</svg>')
    return "\n".join(o)


def main() -> None:
    grafo = construir_grafo(DADOS_EMPRESAS)
    score = calcular_score(grafo)
    imprimir_relatorio(grafo, score)

    here = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(here, "exemplo_resultado.json")
    svg_path = os.path.join(here, "organograma_exemplo.svg")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"grafo": grafo, "score": score}, f, ensure_ascii=False, indent=2)
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(gerar_svg(grafo, score))

    print(f"\n✓ {json_path}")
    print(f"✓ {svg_path}")
    print("\nAbra o SVG no navegador, ou carregue o JSON em frontend/organograma.html.")


if __name__ == "__main__":
    main()
