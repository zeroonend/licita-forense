"""
Skill: gera_laudo
Síntese final via Claude API — gera laudo investigativo em texto.
"""
import os
import json
import anthropic
from dotenv import load_dotenv
load_dotenv()


def gerar_laudo(grafo: dict, score: dict, meta: dict) -> str:
    """
    Gera laudo investigativo completo baseado no grafo e score.
    """
    client = anthropic.Anthropic()

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

    resposta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )

    return resposta.content[0].text
