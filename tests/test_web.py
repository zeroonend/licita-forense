"""Testes da camada web (FastAPI TestClient) — endpoints de leitura e upload.

Não dispara LLM/APIs reais: a função de pipeline é substituída por uma falsa
que grava no banco temporário, como o pipeline real faria.
"""
import os
import io
import json
import time

import pytest
from fastapi.testclient import TestClient

import db
from web import server


def _artefato(eid, edital="020/2026", artefato_path=None):
    return {
        "schema_version": "investigation_result.v1",
        "execution": {"id": eid, "finished_at": "2026-06-24T12:00:00+00:00",
                      "status": "success", "input_pdf_sha256": "abc",
                      "artifact_path": artefato_path,
                      "components": {"ruleset_version": "scoring_conluio.v4",
                                     "extractor_model": "m", "laudo_model": "m"}},
        "licitacao": {"numero": edital, "orgao": "HMTJ", "objeto": "serviços"},
        "score": {"score_geral": 100, "nivel_risco": "CRÍTICO", "total_alertas": 7,
                  "alertas": [{"tipo": "mesmo_telefone", "peso": 20, "descricao": "x",
                               "empresas": ["37083255000175", "22008248000131"]}]},
        "grafo": {"empresas": [
            {"cnpj": "37083255000175", "razao_social": "BRAIN CARE"},
            {"cnpj": "22008248000131", "razao_social": "GAMA"},
        ], "expansao_socios": {"***909901**|GUILHERME": [1, 2]}, "aprofundamento": {}},
        "laudo": {"text": "## Resumo\nRisco crítico."},
        "warnings": [],
    }


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    dbfile = str(tmp_path / "t.db")
    monkeypatch.setattr(db, "CAMINHO_PADRAO", dbfile)
    monkeypatch.setattr(server, "UPLOADS_DIR", str(tmp_path / "up"))
    monkeypatch.setattr(server, "LAUDOS_DIR", str(tmp_path / "laudos"))
    os.makedirs(tmp_path / "up", exist_ok=True)
    os.makedirs(tmp_path / "laudos", exist_ok=True)
    db.conectar(dbfile).close()  # cria o schema
    return TestClient(server.app)


def _semear(eid, edital="020/2026", artefato_path=None):
    conn = db.conectar()
    try:
        db.registrar_execucao(conn, _artefato(eid, edital, artefato_path))
    finally:
        conn.close()


def test_listar_execucoes(cliente):
    _semear("ex-1", "020/2026")
    _semear("ex-2", "031/2026")
    r = cliente.get("/api/investigacoes")
    assert r.status_code == 200
    editais = {e["edital_numero"] for e in r.json()}
    assert editais == {"020/2026", "031/2026"}


def test_cruzamento_recorrentes(cliente):
    _semear("ex-1", "020/2026")
    _semear("ex-2", "031/2026")
    r = cliente.get("/api/cruzamento/recorrentes?min=2")
    assert r.status_code == 200
    chaves = {x["chave"] for x in r.json()}
    assert "22008248000131" in chaves   # GAMA nos dois editais
    assert "***909901**" in chaves      # sócio nos dois editais


def test_upload_rejeita_nao_pdf(cliente):
    r = cliente.post("/api/investigacoes",
                     files={"arquivo": ("x.txt", io.BytesIO(b"oi"), "text/plain")})
    assert r.status_code == 400


def test_upload_dispara_job_e_indexa(cliente, monkeypatch):
    # pipeline falso: grava no banco e devolve o id, sem tocar em LLM/APIs.
    def fake_pipeline(caminho_pdf, aprofundar):
        eid = "job-exec-1"
        conn = db.conectar()
        try:
            db.registrar_execucao(conn, _artefato(eid, "099/2026"))
        finally:
            conn.close()
        return eid
    monkeypatch.setattr(server, "executar_pipeline", fake_pipeline)

    r = cliente.post("/api/investigacoes",
                     files={"arquivo": ("edital.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # acompanha o job até concluir
    for _ in range(40):
        j = cliente.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("concluido", "erro"):
            break
        time.sleep(0.1)
    assert j["status"] == "concluido", j
    assert j["execucao_id"] == "job-exec-1"
    # apareceu no histórico
    assert any(e["id"] == "job-exec-1" for e in cliente.get("/api/investigacoes").json())


def test_artefato_e_laudo_pdf(cliente, tmp_path):
    caminho = str(tmp_path / "art.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(_artefato("ex-art", "020/2026", artefato_path=caminho), f)
    _semear("ex-art", "020/2026", artefato_path=caminho)

    r = cliente.get("/api/investigacoes/ex-art/artefato")
    assert r.status_code == 200
    assert r.json()["licitacao"]["numero"] == "020/2026"

    r = cliente.get("/api/investigacoes/ex-art/laudo.pdf")
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"


def test_detalhe_404(cliente):
    assert cliente.get("/api/investigacoes/nao-existe").status_code == 404
