# Licita Forense

Sistema de investigação profunda de licitações públicas brasileiras.
Detecta potencial conluio e cartel entre licitantes via cruzamento de dados societários.

## Arquitetura

Pipeline com encanamento determinístico (LLM só na extração e no laudo), com
saída versionada e trilha de execução para valor probatório:

1. Upload de documentos (edital, ata, resultado, propostas)
2. Extração estruturada via LLM (Anthropic→Gemini, fallback) → {cnpjs, lances, resultado}
3. Investigação societária via CNPJá API (QSA, busca reversa de sócios); 2º nível opcional
4. Scoring de conluio (regras determinísticas CADE)
5. Laudo via LLM (com fallback para template determinístico)
6. Artefato `investigation_result.v1` persistido por execução (hash do PDF, modelos, timestamps)
7. Visualização em organograma interativo

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
# preencha as variáveis (ANTHROPIC_API_KEY e/ou GEMINI_API_KEY, CNPJA_API_KEY)
pip install -r requirements.txt
python orquestrador/main.py <caminho_do_pdf> [--aprofundar]
```

Cada execução grava o artefato versionado em `execucoes/<id>.json`.

Para visualizar no organograma:

```bash
python orquestrador/main.py <pdf> --frontend     # exporta para o frontend
python -m http.server 8000 -d frontend           # serve o organograma
# abra http://localhost:8000/organograma.html (carrega o último resultado)
```

## O que NUNCA vai ao git

`.env`, PDFs de editais, laudos gerados, artefatos de execução
(`execucoes/`, `frontend/resultado-*.json`), dumps da Receita Federal.
