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
- `consulta_dominio` — titular de domínio via RDAP do registro.br (.br)
- `laudo_pdf` — gera o laudo investigativo em PDF (rede de vínculos + alertas + texto)
- `scoring_conluio` — regras determinísticas (CADE); sem LLM, mesmo grafo → mesmo score
- `gera_laudo` — síntese Claude API
- `certidao_junta` — passo manual: certidão JUCEG para CPF completo nos licitantes do edital

## Fontes de Dados

- **CNPJá (primário)** — QSA em tempo real, busca reversa de sócios
- **BrasilAPI (fallback)** — gratuito, dados mensais
- **Junta Comercial** — certidão oficial com CPF completo e fé pública (passo manual)
- **SQLite local (`--banco`)** — cache persistente de consultas + índice de execuções
  (cruzamento entre editais). Camada portável: vira Postgres no dia do dump RFB.
- **Base RFB local (fase 2)** — Postgres com dump nacional da Receita Federal

## Setup

```bash
cp .env.example .env
# preencha as variáveis (ANTHROPIC_API_KEY e/ou GEMINI_API_KEY, CNPJA_API_KEY)
pip install -r requirements.txt
python orquestrador/main.py <caminho_do_pdf> [--aprofundar] [--frontend] [--pdf] [--banco]
```

Cada execução grava o artefato versionado em `execucoes/<id>.json`.
`--pdf` gera o laudo formatado em `laudos/laudo_<id>.pdf`.
`--banco` liga o SQLite (`dados/licita.db`): cache persistente de consultas
(CNPJ/domínio) que economiza créditos entre execuções e índice de execuções
para cruzamento entre editais. Desligado nos modos `--gravar-cache`/replay
para não interferir na trilha determinística.

Para visualizar no organograma:

```bash
python orquestrador/main.py <pdf> --frontend     # exporta para o frontend
python -m http.server 8000 -d frontend           # serve o organograma
# abra http://localhost:8000/organograma.html (carrega o último resultado)
```

## Painel web (para funcionários, sem terminal)

Camada FastAPI sobre o pipeline: subir PDF e investigar pelo navegador,
histórico de execuções e cruzamento entre editais (lê o SQLite). Sem
login/multi-tenant por enquanto — estrutura preparada para virar SaaS depois.

```bash
pip install -r requirements.txt
uvicorn web.server:app --reload      # ou: python -m web.server
# abra http://localhost:8000
```

- `POST /api/investigacoes` — sobe o PDF e dispara a investigação (background)
- `GET /api/investigacoes` — histórico · `GET /api/cruzamento/recorrentes` — recorrentes
- `GET /api/investigacoes/<id>/laudo.pdf` — laudo · organograma via `?data=/api/investigacoes/<id>/artefato`

## O que NUNCA vai ao git

`.env`, PDFs de editais (incl. `uploads/`), laudos gerados, artefatos de
execução (`execucoes/`, `frontend/resultado-*.json`), o banco (`dados/`,
`*.db`), dumps da Receita Federal.
