# Licita Forense

Sistema de investigação profunda de licitações públicas brasileiras.
Detecta potencial conluio e cartel entre licitantes via cruzamento de dados societários.

## Arquitetura

Pipeline determinístico (mesmo input → mesmo output, para valor probatório):

1. Upload de documentos (edital, ata, resultado, propostas)
2. Extração estruturada via Claude API → {cnpjs, lances, resultado}
3. Investigação societária via CNPJá API (QSA, busca reversa de sócios)
4. Scoring de conluio (regras determinísticas CADE)
5. Laudo gerado pelo Claude API
6. Visualização em organograma interativo

## Skills

- `consulta_cnpj` — wrapper CNPJá: dados da empresa + QSA
- `busca_reversa_socios` — dado sócio (nome + CPF 6 dígitos), retorna todas as empresas
- `scoring_conluio` — regras determinísticas (CADE); sem LLM, mesmo grafo → mesmo score
- `gera_laudo` — síntese Claude API
- `certidao_junta` — passo manual: certidão JUCEG para CPF completo nos licitantes do edital

## Fontes de Dados

- **CNPJá (primário)** — QSA em tempo real, busca reversa de sócios
- **BrasilAPI (fallback)** — gratuito, dados mensais
- **Junta Comercial** — certidão oficial com CPF completo e fé pública (passo manual)
- **Base RFB local (fase 2)** — Postgres com dump nacional da Receita Federal

## Setup

```bash
cp .env.example .env
# preencha as variáveis
pip install -r requirements.txt
python orquestrador/main.py
```

## O que NUNCA vai ao git

`.env`, PDFs de editais, laudos gerados, dumps da Receita Federal.
