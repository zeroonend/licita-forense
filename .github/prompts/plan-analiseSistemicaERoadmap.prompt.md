\## Plan: Análise Sistêmica e Roadmap

Consolidar a análise completa do sistema atual e transformar os achados em um roteiro de execução com foco em confiabilidade probatória, cobertura funcional do scoring, e operacionalização (persistência, testes, observabilidade). A abordagem recomendada é: estabilizar contrato de dados e trilha auditável (P0), fechar lacunas de regras/documentação (P1), e então escalar integração/UX (P2/P3).

**Steps**
1. Fase 1 - Baseline arquitetural e contrato de dados
2. Confirmar e documentar o fluxo canônico ponta a ponta (PDF -> extração -> enriquecimento -> grafo -> score -> laudo -> frontend), usando o comportamento real do código como fonte de verdade.
3. Definir contrato versionado do payload de saída da investigação (metadados da execução, entidades, vínculos, score, laudo, evidências). *Bloqueia passos 6-9*.
4. Especificar estratégia de rastreabilidade por execução: hash do PDF, parâmetros, respostas de APIs/LLM, versão de prompts/modelo, timestamps. *Paralelo com passo 3*.
5. Fase 2 - Confiabilidade e determinismo operacional
6. Introduzir persistência de artefatos de execução (arquivo + banco) para auditoria e reprocessamento reprodutível. *depende de 3 e 4*.
7. Definir modo determinístico de operação (cache + replay de chamadas externas + política de fallback explícita). *depende de 6*.
8. Revisar truncamento de contexto do extrator para evitar perda de licitantes e definir estratégia segura para documentos longos (chunking/janela). *paralelo com passo 7*.
9. Fase 3 - Cobertura funcional de investigação
10. Fechar gap entre metodologia e implementação do scoring: implementar regras faltantes ou atualizar escopo documentado com transparência. *depende de 1*.
11. Fortalecer construção do grafo com deduplicação/normalização de CNPJ e entidades para reduzir falso positivo/negativo. *paralelo com passo 10*.
12. Fase 4 - Qualidade e observabilidade
13. Criar suíte mínima de testes (unitários dos normalizadores + integração do pipeline com fixtures e mocks de APIs). *depende de 3*.
14. Substituir logs ad-hoc por logging estruturado com ID de execução e níveis de severidade.
15. Definir monitoramento básico de falhas por etapa (extração, enriquecimento, scoring, laudo). *paralelo com passo 14*.
16. Fase 5 - Integração de produto e experiência
17. Integrar banco local da fase 2 ao orquestrador para modo híbrido (cache local + APIs externas).
18. Expor saída JSON do orquestrador de forma direta para consumo no frontend, reduzindo operação manual.
19. Adicionar validação de schema no frontend para falhas amigáveis de upload/estrutura.

**Relevant files**
- /workspaces/licita-forense/orquestrador/main.py — fluxo principal, composição de etapas, construção de grafo e saída.
- /workspaces/licita-forense/extrator/extrator.py — extração de texto, chamada LLM e limitação de contexto.
- /workspaces/licita-forense/skills/consulta_cnpj/skill.py — consulta/fallback de dados cadastrais e normalização.
- /workspaces/licita-forense/skills/busca_reversa_socios/skill.py — expansão da rede por sócios e extração de CNPJs.
- /workspaces/licita-forense/skills/scoring_conluio/skill.py — regras implementadas, pesos e classificação de risco.
- /workspaces/licita-forense/skills/gera_laudo/skill.py — geração de laudo por LLM.
- /workspaces/licita-forense/frontend/organograma.html — ingestão de JSON e renderização do grafo.
- /workspaces/licita-forense/db/schema.sql — modelo relacional e índices para busca reversa.
- /workspaces/licita-forense/docs/arquitetura.md — metodologia alvo e regras declaradas.
- /workspaces/licita-forense/README.md — escopo prometido e instruções de uso.

**Verification**
1. Validar consistência documental: comparar comportamento real do código com README/arquitetura e registrar divergências fechadas.
2. Executar cenário controle com fixture de PDF conhecido e confirmar que saída estruturada atende ao contrato versionado.
3. Simular indisponibilidade de APIs externas para validar política de fallback, cache/replay e modo determinístico.
4. Medir regressão/ganho de precisão do scoring após fechamento das regras faltantes (dataset de casos positivos/negativos).
5. Rodar testes automatizados em CI para pipeline mínimo (extração, consulta, scoring, laudo) e exigir aprovação para merge.

**Decisions**
- Escopo incluído: análise técnica completa do estado atual e roadmap priorizado por risco/impacto.
- Escopo excluído nesta etapa: implementação de código, migrações, e mudanças de infraestrutura.
- Premissa: prioridade máxima é reprodutibilidade e auditabilidade para uso forense.

**Further Considerations**
1. Definição do modo de laudo: opção A (LLM obrigatório), opção B (template determinístico), opção C (híbrido com fallback). Recomendação: opção C.
2. Estratégia de persistência: opção A (somente banco), opção B (somente arquivos versionados), opção C (dual-write). Recomendação: opção C.
3. Prioridade de entrega: opção A (confiabilidade primeiro), opção B (features de scoring primeiro), opção C (frontend primeiro). Recomendação: opção A.