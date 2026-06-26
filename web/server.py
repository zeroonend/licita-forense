"""
Camada web (FastAPI) sobre o pipeline existente — para funcionários operarem
sem terminal. Reaproveita investigar(), o banco SQLite e o organograma.

Duas frentes:
- Operar: subir um PDF e disparar a investigação (em background, com status).
- Consultar: histórico de execuções e cruzamento entre editais (lê o banco).

Sem login/multi-tenant de propósito (isso é coisa do "vira SaaS"); a estrutura
deixa espaço pra eles entrarem por cima depois, sem reescrever.

Rodar:  uvicorn web.server:app --reload   (ou  python -m web.server)
"""
import os
import sys
import json
import uuid
import shutil
import threading

# Garante a raiz do repo no sys.path para os imports de pacote.
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import db

FRONTEND_DIR = os.path.join(_RAIZ, "frontend")
UPLOADS_DIR = os.path.join(_RAIZ, "uploads")
LAUDOS_DIR = os.path.join(_RAIZ, "laudos")
os.makedirs(UPLOADS_DIR, exist_ok=True)

app = FastAPI(title="Licita Forense", version="1.0")

# Jobs de investigação em andamento (memória; reinício perde os in-flight — ok
# para uso local/poucos usuários, vira fila de jobs quando virar SaaS).
_jobs = {}
_jobs_lock = threading.Lock()


# ------------------------------------------------------------- pipeline (job)
def executar_pipeline(caminho_pdf: str, aprofundar: bool, nome_original: str = None,
                      certidoes_pdfs: list = None) -> str:
    """
    Roda a investigação completa e devolve o id da execução. Isolada para os
    testes poderem substituir sem disparar LLM/APIs reais.
    """
    from orquestrador.main import investigar
    art = investigar(caminho_pdf, aprofundar=aprofundar, usar_banco=True,
                     nome_original=nome_original, certidoes_pdfs=certidoes_pdfs)
    return art["execution"]["id"]


def _rodar_job(job_id: str, caminho_pdf: str, aprofundar: bool, nome_original: str = None,
               certidoes_pdfs: list = None):
    try:
        eid = executar_pipeline(caminho_pdf, aprofundar, nome_original, certidoes_pdfs)
        _set_job(job_id, status="concluido", execucao_id=eid)
    except Exception as e:  # noqa: BLE001 — superfície para o painel
        _set_job(job_id, status="erro", erro=str(e))


def _set_job(job_id, **campos):
    with _jobs_lock:
        _jobs.setdefault(job_id, {})
        _jobs[job_id].update(campos)


# ------------------------------------------------------------------ endpoints
@app.post("/api/investigacoes")
async def criar_investigacao(arquivo: UploadFile = File(...),
                             aprofundar: bool = Form(False),
                             certidoes: list[UploadFile] = File(default=[])):
    """
    Recebe o edital + certidões (opcionais), dispara a investigação em background.
    """
    if not (arquivo.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Envie um arquivo PDF.")
    job_id = str(uuid.uuid4())
    destino = os.path.join(UPLOADS_DIR, f"{job_id}.pdf")
    with open(destino, "wb") as f:
        shutil.copyfileobj(arquivo.file, f)

    cert_paths = []
    for i, cert in enumerate(certidoes or []):
        if not (cert.filename or "").lower().endswith(".pdf"):
            continue  # ignora campos vazios / não-PDF
        cpath = os.path.join(UPLOADS_DIR, f"{job_id}_cert_{i}.pdf")
        with open(cpath, "wb") as f:
            shutil.copyfileobj(cert.file, f)
        cert_paths.append(cpath)

    _set_job(job_id, status="rodando", arquivo=arquivo.filename, execucao_id=None,
             erro=None, n_certidoes=len(cert_paths))
    threading.Thread(target=_rodar_job,
                     args=(job_id, destino, aprofundar, arquivo.filename, cert_paths),
                     daemon=True).start()
    return {"job_id": job_id, "status": "rodando", "n_certidoes": len(cert_paths)}


@app.get("/api/jobs/{job_id}")
async def status_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado.")
    return {"job_id": job_id, **job}


@app.get("/api/investigacoes")
async def listar():
    conn = db.conectar()
    try:
        return db.listar_execucoes(conn)
    finally:
        conn.close()


@app.get("/api/investigacoes/{eid}")
async def detalhe(eid: str):
    conn = db.conectar()
    try:
        ex = db.execucao(conn, eid)
    finally:
        conn.close()
    if not ex:
        raise HTTPException(404, "Execução não encontrada.")
    ex["artefato_existe"] = bool(ex.get("artefato_path") and
                                 os.path.exists(os.path.join(_RAIZ, ex["artefato_path"])))
    return ex


@app.get("/api/investigacoes/{eid}/artefato")
async def artefato(eid: str):
    """Artefato completo (para o organograma via ?data= e para o detalhe)."""
    caminho = _caminho_artefato(eid)
    with open(caminho, encoding="utf-8") as f:
        return JSONResponse(json.load(f))


@app.get("/api/investigacoes/{eid}/laudo.pdf")
async def laudo_pdf(eid: str):
    """Gera o laudo em PDF sob demanda (se ainda não existir) e devolve."""
    from skills.laudo_pdf.skill import gerar_pdf
    saida = os.path.join(LAUDOS_DIR, f"laudo_{eid}.pdf")
    if not os.path.exists(saida):
        with open(_caminho_artefato(eid), encoding="utf-8") as f:
            art = json.load(f)
        gerar_pdf(art, caminho_saida=saida)
    return FileResponse(saida, media_type="application/pdf",
                        filename=f"laudo_{eid}.pdf")


@app.get("/api/cruzamento/recorrentes")
async def cruzamento(min: int = 2):
    conn = db.conectar()
    try:
        return db.recorrentes(conn, min_ocorrencias=min)
    finally:
        conn.close()


@app.get("/api/empresas/{cnpj}/editais")
async def empresa_editais(cnpj: str):
    conn = db.conectar()
    try:
        return db.editais_da_empresa(conn, cnpj)
    finally:
        conn.close()


@app.get("/api/socios/{doc}/editais")
async def socio_editais(doc: str):
    conn = db.conectar()
    try:
        return db.editais_do_socio(conn, doc)
    finally:
        conn.close()


@app.get("/", response_class=HTMLResponse)
async def painel():
    with open(os.path.join(FRONTEND_DIR, "dashboard.html"), encoding="utf-8") as f:
        return f.read()


# Estáticos (organograma.html e afins) sob /static.
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


def _caminho_artefato(eid: str) -> str:
    conn = db.conectar()
    try:
        ex = db.execucao(conn, eid)
    finally:
        conn.close()
    if not ex or not ex.get("artefato_path"):
        raise HTTPException(404, "Execução sem artefato.")
    caminho = os.path.join(_RAIZ, ex["artefato_path"])
    if not os.path.exists(caminho):
        raise HTTPException(404, "Arquivo de artefato ausente.")
    return caminho


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.server:app", host="0.0.0.0", port=8000, reload=True)
