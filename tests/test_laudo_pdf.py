"""Testes da geração de laudo em PDF (sem rede)."""
from skills.laudo_pdf.skill import gerar_pdf, _s


def _artefato():
    return {
        "execution": {"id": "test-1", "status": "success",
                      "input_pdf_sha256": "abcdef0123456789",
                      "components": {"ruleset_version": "scoring_conluio.v4",
                                     "extractor_model": "m", "laudo_model": "m"}},
        "licitacao": {"numero": "020/2026", "orgao": "Órgão X",
                      "objeto": "serviços", "data": "19/06/2026"},
        "grafo": {"empresas": [
            {"cnpj": "11111111000111", "razao_social": "ALFA LTDA",
             "lance": "R$ 1.000,00", "resultado": "VENCEDOR"},
            {"cnpj": "22222222000122", "razao_social": "BETA S.A.",
             "lance": "R$ 1.010,00", "resultado": "2º lugar"},
        ]},
        "score": {"score_geral": 25, "nivel_risco": "MÉDIO", "total_alertas": 1,
                  "alertas": [{"tipo": "mesmo_telefone", "peso": 20,
                               "descricao": "Mesmo telefone — vínculo",
                               "empresas": ["11111111000111", "22222222000122"]}]},
        "laudo": {"text": "## Resumo\nRisco médio detectado.\n\nDetalhe com acento: ção, ão."},
        "warnings": [],
    }


def test_gerar_pdf_cria_arquivo(tmp_path):
    out = str(tmp_path / "laudo.pdf")
    caminho = gerar_pdf(_artefato(), caminho_saida=out)
    assert caminho == out
    with open(out, "rb") as f:
        head = f.read(5)
    assert head == b"%PDF-"
    import os
    assert os.path.getsize(out) > 1000  # PDF com conteúdo real


def test_gerar_pdf_sem_alertas(tmp_path):
    art = _artefato()
    art["score"] = {"score_geral": 0, "nivel_risco": "BAIXO", "total_alertas": 0, "alertas": []}
    out = str(tmp_path / "vazio.pdf")
    gerar_pdf(art, caminho_saida=out)
    with open(out, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_s_sanitiza_latin1():
    assert _s("traço—e…reticências") == "traço-e...reticências"
    assert _s(None) == ""
