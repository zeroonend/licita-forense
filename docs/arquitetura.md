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
3. Junta Comercial — CPF completo, passo manual, fé pública
4. Base RFB local Postgres — fase 2, para volume

## Sinais de alerta (metodologia CADE)

- Sócio em comum entre licitantes (peso 35)
- Mesmo endereço/telefone/email (peso 20)
- CNPJs sequenciais ou abertura próxima (peso 15/10)
- Mesmo contador assinando balanços (peso 10)
- Lance de cobertura / valores redondos (peso 5)
- Subcontratação do perdedor pelo vencedor (peso 5)
