# Arquitetura — Licita Forense

## Princípio fundamental

Pipeline determinístico: mesmo input → mesmo output.
LLM entra apenas em extração de documentos e síntese do laudo final.
Todo encanamento é código determinístico para garantir valor probatório.

## Fluxo

PDF upload → Extrator (Claude API) → CNPJs + lances
→ consulta_cnpj (CNPJá) → QSA de cada empresa
→ construir_grafo → detecta sócios em comum
→ scoring_conluio → score + alertas CADE
→ gera_laudo (Claude API) → laudo investigativo
→ organograma.html → visualização interativa

## Fontes de dados (hierarquia)

1. CNPJá API (pago/crédito) — primário, QSA em tempo real
2. BrasilAPI — fallback gratuito, dados mensais
   - Exceção (economia): empresas SCP (Sociedade em Conta de Participação)
     consultam BrasilAPI primeiro; CNPJá só como fallback.
3. Junta Comercial — CPF completo, passo manual, fé pública
4. Base RFB local Postgres — fase 2, para volume

## Sinais de alerta (metodologia CADE)

Implementados hoje (scoring 100% determinístico, sem LLM):

- Sócio em comum entre licitantes (peso 35)
- Rede externa compartilhada — empresa fora do edital que concentra sócios de
  2+ licitantes via busca reversa (peso 25)
- Mesmo endereço entre licitantes — normalização canônica (peso 20)
- Ponte via aprofundamento — sócio comum a empresas externas (SCPs) ligadas a
  2+ licitantes; só com `aprofundar=True` (peso 20)
- CNPJs sequenciais (peso 15)
- Abertura próxima — constituição em datas próximas (peso 10)

Previstos no roadmap, ainda **não implementados** (pesos reservados):

- Mesmo contador assinando balanços (peso 10)
- Lance de cobertura / valores redondos (peso 5)
- Subcontratação do perdedor pelo vencedor (peso 5)
