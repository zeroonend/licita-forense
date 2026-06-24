# Exemplos — Licita Forense

Demo **offline** do motor determinístico, sem precisar de chaves de API nem PDF.

## O que tem aqui

- **`demo.py`** — monta um caso sintético de licitação com conluio plantado
  (3 licitantes), roda o código real de `construir_grafo` + `calcular_score`,
  imprime o relatório e gera os arquivos abaixo.
- **`exemplo_resultado.json`** — saída do pipeline (`{grafo, score}`), pronta
  para carregar no `frontend/organograma.html`.
- **`organograma_exemplo.svg`** — render estático do grafo (gerado pelo `demo.py`;
  não versionado).

## Como rodar

```bash
pip install -r requirements.txt        # na raiz do projeto
python examples/demo.py
```

Saída esperada: **score 100 (bruto 120) — CRÍTICO**, com 5 alertas
(2 sócios em comum, mesmo endereço, 2 pares de CNPJs sequenciais).

## Ver o organograma

Duas opções:

1. **Estático** — abra `examples/organograma_exemplo.svg` no navegador.
2. **Interativo** — abra `frontend/organograma.html` no navegador, clique em
   *Carregar resultado.json* e selecione `examples/exemplo_resultado.json`.
   Nessa versão você arrasta os nós e o tooltip mostra CNPJ, lance e situação.

## O caso plantado

| Empresa | Sócios | Sinal |
|---|---|---|
| ALFA (vencedora) | João, Maria | — |
| BETA (2º) | João, Pedro | mesmo endereço da ALFA; CNPJ sequencial |
| GAMA (3º) | Maria, João | CNPJ sequencial |

João aparece nas **3** empresas e Maria em **2** — o padrão de cartel que a
ferramenta existe para flagrar. Pedro, sócio de uma empresa só, não gera alerta.
