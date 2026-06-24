"""Testes dos utilitários do orquestrador: matriz de CNPJ, hash, persistência, aprofundamento."""
import json
import orquestrador.main as om


def test_cnpj_matriz_contra_cnpjs_conhecidos():
    # raiz de 8 dígitos → CNPJ completo da matriz (raiz + 0001 + DV)
    assert om._cnpj_matriz("37083255") == "37083255000175"
    assert om._cnpj_matriz("22008248") == "22008248000131"
    assert om._cnpj_matriz("18946109") == "18946109000181"


def test_cnpj_matriz_invalido():
    assert om._cnpj_matriz("123") == ""
    assert om._cnpj_matriz(None) == ""


def test_hash_arquivo(tmp_path):
    import hashlib
    p = tmp_path / "x.bin"
    conteudo = b"licita forense" * 1000
    p.write_bytes(conteudo)
    sha, n = om._hash_arquivo(str(p))
    assert sha == hashlib.sha256(conteudo).hexdigest()
    assert n == len(conteudo)


def test_persistir_artefato(tmp_path):
    artefato = {"execution": {"id": "abc-123"}, "x": 1}
    caminho = om._persistir_artefato(artefato, dir_saida=str(tmp_path))
    assert caminho.endswith("investigacao_abc-123.json")
    assert json.load(open(caminho)) == artefato


def test_exportar_frontend(tmp_path):
    artefato = {"execution": {"id": "z"}, "grafo": {}, "score": {}}
    caminho = om._exportar_frontend(artefato, base_dir=str(tmp_path))
    assert caminho.endswith("resultado-ultimo.json")
    assert json.load(open(caminho)) == artefato


def test_construir_grafo_detecta_socio_em_comum():
    dados = [
        {"cnpj": "11111111000111", "qsa": [{"nome_socio": "JOAO", "cpf_cnpj_socio": "***1**"}]},
        {"cnpj": "22222222000122", "qsa": [{"nome_socio": "JOAO", "cpf_cnpj_socio": "***1**"}]},
    ]
    g = om.construir_grafo(dados)
    assert len(g["vinculos_suspeitos"]) == 1
    assert set(g["vinculos_suspeitos"][0]["empresas"]) == {"11111111000111", "22222222000122"}


def test_aprofundar_rede_apenas_scp_e_limite(monkeypatch):
    # Evita rede: consultar_cnpj devolve QSA fake com a fonte conforme SCP/normal.
    def fake_consultar(cnpj, razao_social=None):
        scp = "SCP" in (razao_social or "").upper().split()
        return {"razao_social": razao_social, "qsa": [], "fonte": "brasilapi" if scp else "cnpja"}
    monkeypatch.setattr(om, "consultar_cnpj", fake_consultar)

    grafo = {
        "empresas": [{"cnpj": "11111111000111"}],
        "expansao_socios": {
            "k": [
                {"cnpj": "33333333", "razao_social": "FOO SCP 01"},
                {"cnpj": "44444444", "razao_social": "BAR SCP 02"},
                {"cnpj": "55555555", "razao_social": "EMPRESA NORMAL LTDA"},
                {"cnpj": "11111111", "razao_social": "LICITANTE SCP"},  # é licitante → ignora
            ]
        },
    }
    # apenas_scp=True ignora a normal e a licitante; limite corta em 1
    out = om.aprofundar_rede(grafo, limite=1, apenas_scp=True)
    assert len(out) == 1
    assert all(v["fonte"] == "brasilapi" for v in out.values())

    out2 = om.aprofundar_rede(grafo, limite=10, apenas_scp=True)
    razoes = {v["razao_social"] for v in out2.values()}
    assert razoes == {"FOO SCP 01", "BAR SCP 02"}  # normal e licitante fora
