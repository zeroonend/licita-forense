"""
Skill: gera_laudo
Síntese final via LLM (Anthropic → fallback Gemini) — gera laudo investigativo.
"""
import json

from llm import gerar_texto

LAUDO_PROMPT_VERSION = "laudo.v1"


def gerar_laudo(grafo: dict, score: dict, meta: dict) -> str:
    """
    Gera laudo investigativo completo baseado no grafo e score.
    """
    contexto = json.dumps({
        "licitacao": meta,
        "empresas": [
            {
                "cnpj": e["cnpj"],
                "razao_social": e["razao_social"],
                "resultado": e.get("resultado"),
                "lance": e.get("lance"),
                "situacao": e.get("situacao"),
                "data_abertura": e.get("data_abertura"),
                "endereco": e.get("endereco"),
                "socios": e.get("qsa", [])
            }
            for e in grafo["empresas"]
        ],
        "vinculos_suspeitos": grafo["vinculos_suspeitos"],
        "score": score
    }, ensure_ascii=False, indent=2)

    prompt = f"""Você é um especialista em análise de licitações públicas brasileiras e detecção de cartel/conluio.
Baseado nos dados abaixo, redija um LAUDO INVESTIGATIVO objetivo e técnico.

DADOS:
{contexto}

O laudo deve conter:
1. RESUMO EXECUTIVO (3-4 linhas sobre o nível de risco detectado)
2. LICITANTES INVESTIGADOS (tabela: empresa, CNPJ, lance, resultado)
3. VÍNCULOS DETECTADOS (descreva cada vínculo suspeito com precisão)
4. ANÁLISE DE RISCO (explique os padrões identificados com base na metodologia CADE)
5. CONCLUSÃO E RECOMENDAÇÃO (encaminhar para investigação / arquivar / monitorar)
6. OBSERVAÇÕES SOBRE EVIDÊNCIAS (o que falta para confirmar — certidão da Junta, etc.)

Tom: técnico, objetivo, sem especulação além dos dados.
Formato: texto corrido com seções numeradas.
Não invente dados que não estão nos inputs."""

    # Modo híbrido: LLM quando disponível; template determinístico como fallback.
    try:
        resposta = gerar_texto(prompt, max_tokens=3000, purpose="laudo")
        print(f"      [laudo via {resposta.provider}/{resposta.model}]")
        return resposta.text
    except Exception as e:
        print(f"      [LLM indisponível ({str(e)[:80]}...) — laudo via template determinístico]")
        return _laudo_template(grafo, score, meta)


def _laudo_template(grafo: dict, score: dict, meta: dict) -> str:
    """Laudo determinístico (sem LLM) montado diretamente dos dados."""
    linhas = []
    linhas.append("LAUDO INVESTIGATIVO (gerado por template determinístico — LLM indisponível)")
    linhas.append("")
    linhas.append(f"Licitação: {meta.get('numero','—')} | Órgão: {meta.get('orgao','—')}")
    linhas.append(f"Objeto: {meta.get('objeto','—')}")
    linhas.append(f"Data: {meta.get('data','—')}")
    linhas.append("")
    linhas.append("1. RESUMO EXECUTIVO")
    linhas.append(
        f"   Nível de risco: {score.get('nivel_risco','—')} "
        f"(score {score.get('score_geral',0)}/100, bruto {score.get('score_bruto',0)}). "
        f"{score.get('total_alertas',0)} alerta(s) detectado(s) sobre "
        f"{len(grafo.get('empresas', []))} licitante(s)."
    )
    linhas.append("")
    linhas.append("2. LICITANTES INVESTIGADOS")
    for e in grafo.get("empresas", []):
        linhas.append(
            f"   - {e.get('razao_social','—')} (CNPJ {e.get('cnpj','—')}) | "
            f"lance {e.get('lance','—')} | {e.get('resultado','—')} | "
            f"{len(e.get('qsa', []))} sócio(s)"
        )
    linhas.append("")
    linhas.append("3. VÍNCULOS / ALERTAS DETECTADOS")
    if score.get("alertas"):
        for a in score["alertas"]:
            linhas.append(f"   - [{a['tipo']} +{a['peso']}] {a['descricao']}")
    else:
        linhas.append("   Nenhum vínculo suspeito detectado pelas regras atuais.")
    linhas.append("")
    linhas.append("4. CONCLUSÃO E RECOMENDAÇÃO")
    nivel = score.get("nivel_risco", "BAIXO")
    rec = {
        "CRÍTICO": "Encaminhar para investigação formal (indícios fortes de conluio).",
        "ALTO": "Encaminhar para investigação (indícios relevantes).",
        "MÉDIO": "Monitorar e aprofundar com certidões da Junta Comercial.",
        "BAIXO": "Arquivar, sem prejuízo de reanálise se surgirem novos dados.",
    }.get(nivel, "Monitorar.")
    linhas.append(f"   {rec}")
    linhas.append("")
    linhas.append("5. OBSERVAÇÕES SOBRE EVIDÊNCIAS")
    linhas.append(
        "   Vínculos via busca reversa baseiam-se em CPF mascarado da Receita; "
        "confirmar com certidão da Junta Comercial (CPF completo, fé pública)."
    )
    return "\n".join(linhas)
