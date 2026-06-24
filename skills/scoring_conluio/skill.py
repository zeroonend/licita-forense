"""
Skill: scoring_conluio
Regras determinísticas baseadas na metodologia do CADE + ponderação LLM.
"""
import os
import json
import anthropic
from dotenv import load_dotenv
load_dotenv()


PESOS = {
    "socio_em_comum": 35,
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

    # Regra 2: Mesmo endereço entre licitantes
    enderecos = {}
    for emp in empresas:
        end = emp.get("endereco", "").strip().upper()
        if end:
            enderecos.setdefault(end, []).append(emp["cnpj"])
    for end, cnpjs in enderecos.items():
        if len(cnpjs) > 1:
            alertas.append({
                "tipo": "mesmo_endereco",
                "peso": PESOS["mesmo_endereco"],
                "descricao": f"Mesmo endereço entre licitantes: {end}",
                "empresas": cnpjs
            })
            score += PESOS["mesmo_endereco"]

    # Regra 3: CNPJs sequenciais (8 primeiros dígitos próximos)
    raizes = [(emp["cnpj"].replace(".","").replace("/","").replace("-","")[:8], emp["cnpj"]) for emp in empresas]
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

    nivel = _classificar_nivel(score)

    return {
        "score_geral": score,
        "nivel_risco": nivel,
        "alertas": alertas,
        "total_alertas": len(alertas)
    }


def _classificar_nivel(score: int) -> str:
    if score >= SCORE_CRITICO:
        return "CRÍTICO"
    elif score >= SCORE_ALTO:
        return "ALTO"
    elif score >= SCORE_MEDIO:
        return "MÉDIO"
    return "BAIXO"
