"""
Camada de persistência (SQLite) — duas finalidades:

1. Cache de consultas externas (empresas/CNPJ e domínios) que sobrevive entre
   execuções: a 2ª vez que vir a mesma empresa, não gasta crédito da CNPJá.
2. Índice de execuções + participações (empresa/sócio × edital), que habilita
   o cruzamento entre editais — o sinal mais forte de cartel é o padrão que se
   repete em várias licitações.

Projetado para ser portável: SQL padrão, segredos nunca entram aqui, e toda a
dependência de SQLite fica isolada neste módulo. Trocar por Postgres no dia do
dump da RFB é mudança de configuração, não reescrita.
"""
import os
import json
import sqlite3
import datetime

CAMINHO_PADRAO = os.getenv("LICITA_DB", os.path.join("dados", "licita.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS empresas_cache (
    cnpj          TEXT PRIMARY KEY,
    razao_social  TEXT,
    dados_json    TEXT NOT NULL,
    fonte         TEXT,
    consultado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dominios_cache (
    dominio       TEXT PRIMARY KEY,
    titular_id    TEXT,
    titular_nome  TEXT,
    consultado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execucoes (
    id            TEXT PRIMARY KEY,
    criado_em     TEXT NOT NULL,
    edital_numero TEXT,
    orgao         TEXT,
    objeto        TEXT,
    score_geral   INTEGER,
    nivel_risco   TEXT,
    total_alertas INTEGER,
    pdf_sha256    TEXT,
    artefato_path TEXT
);

CREATE TABLE IF NOT EXISTS participacoes (
    execucao_id   TEXT NOT NULL,
    edital_numero TEXT,
    papel         TEXT NOT NULL,   -- licitante | socio | externa
    cnpj          TEXT,
    nome          TEXT,
    doc           TEXT,            -- CPF mascarado/ CNPJ do sócio
    FOREIGN KEY (execucao_id) REFERENCES execucoes(id)
);

CREATE INDEX IF NOT EXISTS ix_part_cnpj ON participacoes(cnpj);
CREATE INDEX IF NOT EXISTS ix_part_doc  ON participacoes(doc);
CREATE INDEX IF NOT EXISTS ix_part_exec ON participacoes(execucao_id);
"""


def conectar(caminho: str = None) -> sqlite3.Connection:
    """Abre (criando o arquivo/pasta se preciso) e devolve a conexão já com schema."""
    caminho = caminho or CAMINHO_PADRAO
    if caminho != ":memory:":
        os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    inicializar(conn)
    return conn


def inicializar(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _agora() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _so_digitos(v: str) -> str:
    return "".join(c for c in (v or "") if c.isdigit())


# ---------------------------------------------------------------- cache empresas
def empresa_cacheada(conn, cnpj: str, max_idade_dias: int = None) -> dict:
    """Devolve os dados normalizados da empresa do cache, ou None se ausente/velho."""
    cnpj = _so_digitos(cnpj)
    if not cnpj:
        return None
    row = conn.execute(
        "SELECT dados_json, consultado_em FROM empresas_cache WHERE cnpj = ?",
        (cnpj,),
    ).fetchone()
    if not row or _expirado(row["consultado_em"], max_idade_dias):
        return None
    return json.loads(row["dados_json"])


def salvar_empresa(conn, cnpj: str, dados: dict) -> None:
    cnpj = _so_digitos(cnpj)
    if not cnpj:
        return
    conn.execute(
        "INSERT OR REPLACE INTO empresas_cache "
        "(cnpj, razao_social, dados_json, fonte, consultado_em) VALUES (?, ?, ?, ?, ?)",
        (cnpj, dados.get("razao_social", ""),
         json.dumps(dados, ensure_ascii=False), dados.get("fonte"), _agora()),
    )
    conn.commit()


# ---------------------------------------------------------------- cache domínios
def dominio_cacheado(conn, dominio: str, max_idade_dias: int = None):
    """Devolve {'id','nome'} (ou None) do cache. Sentinela vazio => 'sem titular'."""
    dominio = (dominio or "").strip().lower()
    row = conn.execute(
        "SELECT titular_id, titular_nome, consultado_em FROM dominios_cache WHERE dominio = ?",
        (dominio,),
    ).fetchone()
    if not row or _expirado(row["consultado_em"], max_idade_dias):
        return None
    if not row["titular_id"] and not row["titular_nome"]:
        return {"id": None, "nome": None}  # consultado antes, sem titular
    return {"id": row["titular_id"], "nome": row["titular_nome"]}


def salvar_dominio(conn, dominio: str, titular: dict) -> None:
    dominio = (dominio or "").strip().lower()
    if not dominio:
        return
    titular = titular or {}
    conn.execute(
        "INSERT OR REPLACE INTO dominios_cache "
        "(dominio, titular_id, titular_nome, consultado_em) VALUES (?, ?, ?, ?)",
        (dominio, titular.get("id"), titular.get("nome"), _agora()),
    )
    conn.commit()


# ----------------------------------------------------------- índice de execuções
def registrar_execucao(conn, artefato: dict) -> str:
    """
    Grava (idempotente) a execução e suas participações para cruzamento entre
    editais. Retorna o id da execução.
    """
    ex = artefato.get("execution") or {}
    lic = artefato.get("licitacao") or {}
    score = artefato.get("score") or {}
    grafo = artefato.get("grafo") or {}
    eid = ex.get("id")
    if not eid:
        raise ValueError("artefato sem execution.id")
    edital = lic.get("numero")

    conn.execute("DELETE FROM participacoes WHERE execucao_id = ?", (eid,))
    conn.execute(
        "INSERT OR REPLACE INTO execucoes "
        "(id, criado_em, edital_numero, orgao, objeto, score_geral, nivel_risco, "
        " total_alertas, pdf_sha256, artefato_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (eid, ex.get("finished_at") or _agora(), edital, lic.get("orgao"),
         lic.get("objeto"), score.get("score_geral"), score.get("nivel_risco"),
         score.get("total_alertas"), ex.get("input_pdf_sha256"),
         ex.get("artifact_path")),
    )

    parts = []
    for e in grafo.get("empresas", []) or []:
        parts.append((eid, edital, "licitante",
                      _so_digitos(e.get("cnpj")), e.get("razao_social"), None))
    for chave, lst in (grafo.get("expansao_socios") or {}).items():
        doc, _, nome = chave.partition("|")
        parts.append((eid, edital, "socio", None, nome or chave, doc or None))
    for cnpj, v in (grafo.get("aprofundamento") or {}).items():
        parts.append((eid, edital, "externa",
                      _so_digitos(cnpj), v.get("razao_social"), None))

    conn.executemany(
        "INSERT INTO participacoes "
        "(execucao_id, edital_numero, papel, cnpj, nome, doc) VALUES (?, ?, ?, ?, ?, ?)",
        parts,
    )
    conn.commit()
    return eid


# ------------------------------------------------------ consultas entre editais
def editais_do_socio(conn, doc: str) -> list:
    """Editais distintos em que um sócio (por CPF mascarado/CNPJ) aparece."""
    rows = conn.execute(
        "SELECT DISTINCT edital_numero, execucao_id, nome FROM participacoes "
        "WHERE doc = ? AND doc IS NOT NULL ORDER BY edital_numero",
        (doc,),
    ).fetchall()
    return [dict(r) for r in rows]


def editais_da_empresa(conn, cnpj: str) -> list:
    """Editais distintos em que uma empresa (por CNPJ) aparece, com o papel."""
    cnpj = _so_digitos(cnpj)
    rows = conn.execute(
        "SELECT DISTINCT edital_numero, execucao_id, papel, nome FROM participacoes "
        "WHERE cnpj = ? AND cnpj != '' ORDER BY edital_numero",
        (cnpj,),
    ).fetchall()
    return [dict(r) for r in rows]


def recorrentes(conn, min_editais: int = 2) -> list:
    """
    Sócios/empresas que aparecem em >= min_editais editais distintos — os elos
    que reaparecem entre licitações (sinal forte para cartel sistêmico).
    """
    rows = conn.execute(
        "SELECT papel, COALESCE(cnpj, doc) AS chave, "
        "       MAX(nome) AS nome, COUNT(DISTINCT edital_numero) AS n_editais "
        "FROM participacoes "
        "WHERE COALESCE(cnpj, doc) IS NOT NULL AND COALESCE(cnpj, doc) != '' "
        "GROUP BY papel, chave HAVING n_editais >= ? "
        "ORDER BY n_editais DESC",
        (min_editais,),
    ).fetchall()
    return [dict(r) for r in rows]


def _expirado(consultado_em: str, max_idade_dias: int) -> bool:
    if not max_idade_dias:
        return False
    try:
        quando = datetime.datetime.fromisoformat(consultado_em)
    except (ValueError, TypeError):
        return True
    idade = datetime.datetime.now(datetime.timezone.utc) - quando
    return idade.days > max_idade_dias
