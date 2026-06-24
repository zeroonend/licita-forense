# Analise sistemica e roadmap

Data da analise: 2026-06-24

## Sumario executivo

O Licita Forense ja possui um pipeline funcional e compacto: PDF -> extracao LLM -> consulta cadastral -> busca reversa de socios -> grafo -> scoring -> laudo -> visualizacao. A principal lacuna nao e de fluxo, mas de confiabilidade probatoria: o sistema se declara deterministico, porem ainda depende de APIs/LLM sem persistencia de entradas, respostas, parametros, versoes e politicas de replay.

A prioridade recomendada e estabilizar o contrato de dados e a trilha auditavel antes de ampliar regras de scoring ou frontend. Sem esse baseline, resultados podem variar entre execucoes e ficam dificeis de reproduzir em contexto forense.

## Fluxo canonico observado

1. `orquestrador/main.py` recebe um caminho de PDF e chama `extrair_licitantes`.
2. `extrator/extrator.py` extrai texto via `pdfplumber`, trunca o conteudo em 15.000 caracteres e envia o prompt ao Claude.
3. O resultado esperado da extracao contem `meta` e `empresas`, com CNPJ, razao social, lance e resultado.
4. Para cada empresa, `consulta_cnpj` tenta CNPJa e, em caso de falha, usa BrasilAPI.
5. O orquestrador executa busca reversa de socios via CNPJa quando ha chave configurada.
6. `construir_grafo` monta `empresas`, `socios_index`, `vinculos_suspeitos` e `expansao_socios`.
7. `scoring_conluio` calcula alertas e score a partir do grafo.
8. `gera_laudo` envia grafo, score e metadados da licitacao ao Claude para gerar texto final.
9. `frontend/organograma.html` consome manualmente um JSON carregado pelo usuario e renderiza grafo e alertas.

## Divergencias entre documentacao e comportamento real

| Tema | Documentado | Observado | Risco |
| --- | --- | --- | --- |
| Determinismo | README e arquitetura prometem mesmo input -> mesmo output. | Extracao e laudo dependem de LLM; CNPJa/BrasilAPI dependem de estado externo; nao ha cache, replay ou persistencia. | Alto: execucoes posteriores podem divergir sem explicacao auditavel. |
| Scoring | README cita "regras CADE + ponderacao LLM"; arquitetura lista sete sinais. | Codigo implementa apenas socio em comum, mesmo endereco e CNPJ sequencial. Nao ha ponderacao LLM no scoring. | Alto: escopo prometido maior que a cobertura real. |
| Contrato de saida | Frontend espera `{ grafo, score }`; orquestrador retorna `{ grafo, score, laudo }`. | Nao ha schema versionado, validacao ou metadados de execucao. | Medio/alto: mudancas quebram consumo e auditoria silenciosamente. |
| Persistencia | Base local Postgres aparece como fase 2. | `db/schema.sql` cobre empresas, socios e estabelecimentos, mas nao execucoes, artefatos, evidencias ou chamadas externas. | Alto: nao ha reprocessamento reprodutivel. |
| Documentos longos | Prompt pede todas as empresas. | Extrator trunca em 15.000 caracteres e avisa que licitantes ao final podem ser omitidos. | Alto: falso negativo em atas grandes. |
| Observabilidade | Nao ha padrao declarado. | O pipeline usa `print`; chamadas externas capturam erros parcialmente. | Medio: falhas por etapa nao ficam correlacionaveis. |
| Frontend | Visualizacao interativa. | Upload manual de JSON; sem validacao de schema. | Medio: falhas aparecem como JSON invalido ou renderizacao incompleta. |

## Contrato versionado proposto

Versao inicial recomendada: `investigation_result.v1`.

```json
{
  "schema_version": "investigation_result.v1",
  "execution": {
    "id": "uuid",
    "started_at": "2026-06-24T00:00:00Z",
    "finished_at": "2026-06-24T00:00:00Z",
    "status": "success|partial|failed",
    "input_pdf_sha256": "hex",
    "source_file_name": "ata.pdf",
    "parameters": {
      "extractor_max_chars": 15000,
      "deterministic_mode": false
    },
    "components": {
      "extractor_model": "claude-sonnet-4-6",
      "laudo_model": "claude-sonnet-4-6",
      "prompt_versions": {
        "extractor": "extractor.v1",
        "laudo": "laudo.v1"
      }
    }
  },
  "licitacao": {
    "numero": null,
    "orgao": null,
    "objeto": null,
    "data": null
  },
  "empresas": [],
  "grafo": {
    "socios_index": {},
    "vinculos_suspeitos": [],
    "expansao_socios": {}
  },
  "score": {
    "score_geral": 0,
    "score_bruto": 0,
    "nivel_risco": "BAIXO",
    "alertas": [],
    "total_alertas": 0,
    "ruleset_version": "scoring_conluio.v1"
  },
  "laudo": {
    "mode": "llm|template|hybrid",
    "text": "",
    "generated_at": "2026-06-24T00:00:00Z"
  },
  "evidencias": [],
  "warnings": []
}
```

## Rastreabilidade minima por execucao

Registrar, no minimo:

- hash SHA-256 do PDF original e tamanho do arquivo;
- texto extraido ou hash do texto extraido, com numero de paginas e aviso de truncamento;
- parametros efetivos da execucao;
- prompt completo ou prompt versionado + variaveis renderizadas;
- modelo, versao de prompt, `max_tokens` e timestamps das chamadas LLM;
- request/response brutos de CNPJa e BrasilAPI, com status HTTP e timestamps;
- fonte usada para cada empresa (`cnpja`, `brasilapi`, `cache`, `replay`);
- warnings e excecoes por etapa;
- artefato final JSON assinado por `schema_version`.

## Roadmap priorizado

### P0 - Baseline probatorio e contrato

1. Criar schema JSON versionado para a saida do orquestrador.
2. Incluir objeto `execution` com ID, timestamps, hash do PDF, parametros e versoes de componentes.
3. Separar `licitacao`/`meta` de `grafo` para reduzir acoplamento com a extracao.
4. Persistir artefato final em arquivo JSON por execucao.
5. Atualizar README e arquitetura para distinguir o que e deterministico hoje do que depende de LLM/API.

### P1 - Persistencia, replay e documentos longos

1. Estender o schema SQL com tabelas de `execucoes`, `artefatos`, `external_calls` e `evidencias`.
2. Implementar cache/replay para CNPJa, BrasilAPI e chamadas LLM.
3. Definir modo deterministico: em `replay`, nenhuma chamada externa nova deve ocorrer.
4. Substituir truncamento simples do PDF por estrategia de chunking ou extracao por paginas.
5. Registrar warnings estruturados quando a cobertura do documento for parcial.

### P2 - Cobertura funcional de investigacao

1. Implementar ou remover da documentacao as regras ainda nao cobertas: telefone/email compartilhado, abertura proxima, mesmo contador, lance redondo/cobertura e subcontratacao.
2. Normalizar CNPJs para formato canonico antes do grafo e do scoring.
3. Deduplicar socios por CPF quando disponivel e por nome normalizado quando CPF estiver mascarado.
4. Explicitar versao do ruleset no resultado do score.

### P3 - Qualidade, observabilidade e produto

1. Adicionar testes unitarios para normalizacao de CNPJ, QSA, grafo e regras de scoring.
2. Criar teste de integracao do pipeline com fixtures e mocks de APIs/LLM.
3. Trocar `print` por logging estruturado com `execution.id`.
4. Expor diretamente o JSON final para consumo do frontend.
5. Adicionar validacao de schema no frontend antes de renderizar.

## Plano de verificacao

1. Validar o contrato `investigation_result.v1` contra um artefato fixture.
2. Rodar o pipeline em modo normal e repetir em modo replay, confirmando igualdade byte a byte do resultado normalizado.
3. Simular indisponibilidade de CNPJa, BrasilAPI e LLM para verificar fallback e status `partial|failed`.
4. Testar um PDF maior que 15.000 caracteres e confirmar que nenhum participante e omitido sem warning explicito.
5. Executar suite automatizada de normalizadores, grafo, scoring e pipeline minimo.

## Decisoes recomendadas

- Laudo: modo hibrido, com LLM quando disponivel e template deterministico como fallback.
- Persistencia: dual-write, com JSON versionado em arquivo e banco relacional para consultas.
- Ordem de entrega: confiabilidade e auditabilidade primeiro; cobertura de scoring depois; frontend por ultimo.

