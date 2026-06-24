"""Testes da busca reversa: parser de /person e desambiguação por CPF mascarado."""
from skills.busca_reversa_socios.skill import _cpf_meio, _extrair_empresas


def test_cpf_meio():
    assert _cpf_meio("***620791**") == "620791"      # mascarado da Receita
    assert _cpf_meio("12345678901") == "456789"        # completo → 6 centrais
    assert _cpf_meio("123") == ""                       # parcial inválido
    assert _cpf_meio(None) == ""


def _resposta():
    return {"records": [{
        "taxId": "***620791**",
        "membership": [
            {"role": {"text": "Sócio"}, "since": "2019-08-02",
             "company": {"id": "32087951", "name": "MEDCORP"}},
            {"role": {"text": "Presidente"}, "since": "2022-07-01",
             "company": {"id": "37083255", "name": "BRAIN CARE"}},
        ],
    }]}


def test_extrair_empresas_retorna_raizes():
    out = _extrair_empresas(_resposta(), cpf_parcial=None)
    cnpjs = {e["cnpj"] for e in out}
    assert cnpjs == {"32087951", "37083255"}
    assert out[0]["razao_social"] in {"MEDCORP", "BRAIN CARE"}


def test_extrair_empresas_filtra_por_cpf_compativel():
    # CPF mascarado batendo → mantém
    assert _extrair_empresas(_resposta(), cpf_parcial="***620791**")
    # CPF mascarado divergente → descarta (homônimo)
    assert _extrair_empresas(_resposta(), cpf_parcial="***999999**") == []


def test_extrair_empresas_dedup():
    data = {"records": [{"taxId": "***1**", "membership": [
        {"company": {"id": "32087951", "name": "A"}},
        {"company": {"id": "32087951", "name": "A"}},  # duplicada
    ]}]}
    assert len(_extrair_empresas(data)) == 1
