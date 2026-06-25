"""Testes da camada de persistência SQLite (cache + índice de execuções)."""
import db


def _conn():
    return db.conectar(":memory:")


def _artefato(eid="ex-1", edital="020/2026", score=100):
    return {
        "execution": {"id": eid, "finished_at": "2026-06-24T12:00:00+00:00",
                      "input_pdf_sha256": "abc123", "artifact_path": f"execucoes/{eid}.json"},
        "licitacao": {"numero": edital, "orgao": "HMTJ", "objeto": "serviços"},
        "score": {"score_geral": score, "nivel_risco": "CRÍTICO", "total_alertas": 7},
        "grafo": {
            "empresas": [
                {"cnpj": "37.083.255/0001-75", "razao_social": "BRAIN CARE"},
                {"cnpj": "22008248000131", "razao_social": "GAMA"},
            ],
            "expansao_socios": {
                "***909901**|GUILHERME SPOSITO": [1, 2, 3],
                "***035015**|PEDRO INACIO": [1, 2],
            },
            "aprofundamento": {
                "47334108000184": {"razao_social": "SEMPREVIDA SCP"},
            },
        },
    }


def test_cache_empresa_round_trip():
    conn = _conn()
    assert db.empresa_cacheada(conn, "37083255000175") is None
    dados = {"razao_social": "BRAIN CARE", "fonte": "cnpja", "qsa": [{"nome_socio": "X"}]}
    db.salvar_empresa(conn, "37.083.255/0001-75", dados)  # aceita formatado
    out = db.empresa_cacheada(conn, "37083255000175")
    assert out["razao_social"] == "BRAIN CARE"
    assert out["qsa"][0]["nome_socio"] == "X"


def test_cache_empresa_expira():
    conn = _conn()
    db.salvar_empresa(conn, "37083255000175", {"razao_social": "X", "fonte": "cnpja"})
    conn.execute("UPDATE empresas_cache SET consultado_em = '2000-01-01T00:00:00+00:00'")
    conn.commit()
    assert db.empresa_cacheada(conn, "37083255000175", max_idade_dias=30) is None
    assert db.empresa_cacheada(conn, "37083255000175") is not None  # sem limite, serve


def test_cache_dominio_sem_titular():
    conn = _conn()
    db.salvar_dominio(conn, "MEDFISCAL.COM.BR", {"id": None, "nome": None})
    out = db.dominio_cacheado(conn, "medfiscal.com.br")
    assert out == {"id": None, "nome": None}  # sentinela: consultado, sem titular


def test_cache_dominio_com_titular():
    conn = _conn()
    db.salvar_dominio(conn, "medfiscal.com.br", {"id": "997861", "nome": "JOSE DOMINGOS"})
    assert db.dominio_cacheado(conn, "medfiscal.com.br")["nome"] == "JOSE DOMINGOS"


def test_registrar_execucao_idempotente():
    conn = _conn()
    db.registrar_execucao(conn, _artefato())
    db.registrar_execucao(conn, _artefato())  # de novo: não duplica
    n_exec = conn.execute("SELECT COUNT(*) FROM execucoes").fetchone()[0]
    n_part = conn.execute("SELECT COUNT(*) FROM participacoes").fetchone()[0]
    assert n_exec == 1
    assert n_part == 5  # 2 licitantes + 2 sócios + 1 externa


def test_cruzamento_entre_editais():
    conn = _conn()
    db.registrar_execucao(conn, _artefato(eid="ex-1", edital="020/2026"))
    db.registrar_execucao(conn, _artefato(eid="ex-2", edital="031/2026"))
    # GAMA (mesmo CNPJ) aparece nos dois editais
    editais = db.editais_da_empresa(conn, "22008248000131")
    assert {e["edital_numero"] for e in editais} == {"020/2026", "031/2026"}
    # sócio recorrente também
    socio = db.editais_do_socio(conn, "***909901**")
    assert len(socio) == 2


def test_recorrentes():
    conn = _conn()
    db.registrar_execucao(conn, _artefato(eid="ex-1", edital="020/2026"))
    db.registrar_execucao(conn, _artefato(eid="ex-2", edital="031/2026"))
    rec = db.recorrentes(conn, min_ocorrencias=2)
    chaves = {r["chave"] for r in rec}
    assert "22008248000131" in chaves      # empresa em 2 execuções
    assert "***909901**" in chaves         # sócio em 2 execuções
    assert all(r["n_execucoes"] >= 2 for r in rec)
    assert all(r["n_editais"] >= 2 for r in rec)   # aqui os editais têm número


def test_recorrentes_robusto_a_edital_nulo():
    # Mesmo sem número de edital extraído (None), reincidência entre execuções
    # distintas deve aparecer — antes COUNT(DISTINCT edital) ignorava NULL.
    conn = _conn()
    db.registrar_execucao(conn, _artefato(eid="ex-1", edital=None))
    db.registrar_execucao(conn, _artefato(eid="ex-2", edital=None))
    rec = db.recorrentes(conn, min_ocorrencias=2)
    porchave = {r["chave"]: r for r in rec}
    assert "22008248000131" in porchave
    assert porchave["22008248000131"]["n_execucoes"] == 2
    assert porchave["22008248000131"]["n_editais"] == 0   # nenhum edital nomeado
