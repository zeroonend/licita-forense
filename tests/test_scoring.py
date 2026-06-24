"""Testes das regras determinísticas de scoring e dos normalizadores."""
from skills.scoring_conluio.skill import (
    calcular_score, _so_digitos, _normalizar_endereco, _parse_data, _parse_valor,
    _dominio_email, _classificar_nivel, RULESET_VERSION, PESOS,
)


def _grafo(empresas, socios_index=None, vinculos=None, expansao=None, aprof=None):
    g = {
        "empresas": empresas,
        "socios_index": socios_index or {},
        "vinculos_suspeitos": vinculos or [],
        "expansao_socios": expansao or {},
    }
    if aprof is not None:
        g["aprofundamento"] = aprof
    return g


# ---------- normalizadores ----------

def test_so_digitos():
    assert _so_digitos("11.111.111/0001-11") == "11111111000111"
    assert _so_digitos(None) == ""
    assert _so_digitos("abc") == ""


def test_normalizar_endereco_unifica_formatos():
    a = _normalizar_endereco("Rua das Flores, 100 - São Paulo/SP")
    b = _normalizar_endereco("RUA DAS FLORES  100  SAO PAULO SP")
    assert a == b == "RUA DAS FLORES 100 SAO PAULO SP"
    assert _normalizar_endereco(None) == ""


def test_parse_data():
    assert _parse_data("2013-09-24").isoformat() == "2013-09-24"
    assert _parse_data("19/06/2026").isoformat() == "2026-06-19"
    assert _parse_data("data ruim") is None
    assert _parse_data(None) is None


def test_classificar_nivel():
    assert _classificar_nivel(60) == "CRÍTICO"
    assert _classificar_nivel(30) == "ALTO"
    assert _classificar_nivel(15) == "MÉDIO"
    assert _classificar_nivel(0) == "BAIXO"


# ---------- calcular_score ----------

def test_score_vazio_tem_ruleset_version():
    r = calcular_score(_grafo([]))
    assert r["score_geral"] == 0
    assert r["nivel_risco"] == "BAIXO"
    assert r["ruleset_version"] == RULESET_VERSION


def test_socio_em_comum():
    g = _grafo(
        [{"cnpj": "11111111000111"}, {"cnpj": "22222222000122"}],
        vinculos=[{"socio": "JOAO", "cpf": "x", "empresas": ["11111111000111", "22222222000122"]}],
    )
    r = calcular_score(g)
    assert r["score_geral"] == PESOS["socio_em_comum"]
    assert r["alertas"][0]["tipo"] == "socio_em_comum"


def test_cnpj_vazio_nao_quebra():
    # Regressão: CNPJ vazio não deve estourar int() na regra de sequencial.
    g = _grafo([{"cnpj": "11111111000111"}, {"cnpj": ""}])
    r = calcular_score(g)  # não deve lançar
    assert r["score_geral"] == 0


def test_mesmo_endereco_fontes_diferentes():
    g = _grafo([
        {"cnpj": "11111111000111", "endereco": "Rua X, 1 - Goiânia/GO"},
        {"cnpj": "22222222000122", "endereco": "RUA X 1 GOIANIA GO"},
    ])
    r = calcular_score(g)
    assert r["score_geral"] == PESOS["mesmo_endereco"]
    assert r["alertas"][0]["tipo"] == "mesmo_endereco"


def test_cnpj_sequencial():
    g = _grafo([{"cnpj": "11111111000111"}, {"cnpj": "11111200000150"}])
    r = calcular_score(g)
    tipos = [a["tipo"] for a in r["alertas"]]
    assert "cnpj_sequencial" in tipos


def test_abertura_proxima():
    perto = _grafo([
        {"cnpj": "11111111000111", "data_abertura": "2013-09-24"},
        {"cnpj": "22222222000122", "data_abertura": "2013-11-19"},  # 56 dias
    ])
    assert "abertura_proxima" in [a["tipo"] for a in calcular_score(perto)["alertas"]]

    longe = _grafo([
        {"cnpj": "11111111000111", "data_abertura": "2013-01-01"},
        {"cnpj": "22222222000122", "data_abertura": "2014-01-01"},  # ~365 dias
    ])
    assert "abertura_proxima" not in [a["tipo"] for a in calcular_score(longe)["alertas"]]


def test_rede_externa_compartilhada():
    g = _grafo(
        [{"cnpj": "11111111000111"}, {"cnpj": "22222222000122"}],
        socios_index={"A|JOAO": ["11111111000111"], "B|MARIA": ["22222222000122"]},
        expansao={
            "A|JOAO": [{"cnpj": "99999999", "razao_social": "EXTERNA"}],
            "B|MARIA": [{"cnpj": "99999999", "razao_social": "EXTERNA"}],
        },
    )
    r = calcular_score(g)
    alerta = [a for a in r["alertas"] if a["tipo"] == "rede_externa_compartilhada"]
    assert alerta and alerta[0]["peso"] == PESOS["rede_externa_compartilhada"]
    assert set(alerta[0]["empresas"]) == {"11111111000111", "22222222000122"}


def test_ponte_externa_aprofundada():
    empresas = [
        {"cnpj": "11111111000111", "razao_social": "ALFA", "qsa": [{"nome_socio": "LAZARO"}]},
        {"cnpj": "22222222000122", "razao_social": "BETA", "qsa": [{"nome_socio": "GUILHERME"}]},
    ]
    aprof = {
        "33333333000133": {"razao_social": "X SCP", "qsa": [
            {"nome_socio": "LAZARO"}, {"nome_socio": "FREDERICO"}]},
        "44444444000144": {"razao_social": "Y SCP", "qsa": [
            {"nome_socio": "GUILHERME"}, {"nome_socio": "FREDERICO"}]},
    }
    r = calcular_score(_grafo(empresas, aprof=aprof))
    ponte = [a for a in r["alertas"] if a["tipo"] == "ponte_externa_aprofundada"]
    assert ponte, "FREDERICO deveria ligar ALFA e BETA"
    assert "FREDERICO" in ponte[0]["descricao"]
    assert set(ponte[0]["empresas"]) == {"ALFA", "BETA"}


def test_parse_valor():
    assert _parse_valor("R$ 450.532,20") == 450532.20
    assert _parse_valor("1.000.000,00") == 1000000.0
    assert _parse_valor(1000) == 1000.0
    assert _parse_valor("abc") is None
    assert _parse_valor(None) is None


def test_lance_cobertura():
    g = _grafo([
        {"cnpj": "11111111000111", "lance": "R$ 450.000,00"},
        {"cnpj": "22222222000122", "lance": "R$ 450.500,00"},  # dif ~0,11%
    ])
    tipos = [a["tipo"] for a in calcular_score(g)["alertas"]]
    assert "lance_cobertura" in tipos


def test_lance_redondo():
    g = _grafo([
        {"cnpj": "11111111000111", "lance": "R$ 100.000,00"},
        {"cnpj": "22222222000122", "lance": "R$ 200.000,00"},  # ambos redondos, longe
    ])
    tipos = [a["tipo"] for a in calcular_score(g)["alertas"]]
    assert "lance_redondo" in tipos
    assert "lance_cobertura" not in tipos  # 50% de diferença


def test_lances_normais_nao_disparam():
    g = _grafo([
        {"cnpj": "11111111000111", "lance": "R$ 450.532,20"},
        {"cnpj": "22222222000122", "lance": "R$ 488.473,20"},
    ])
    tipos = [a["tipo"] for a in calcular_score(g)["alertas"]]
    assert "lance_cobertura" not in tipos and "lance_redondo" not in tipos


def test_dominio_email():
    assert _dominio_email("contato@EMPRESA.com.br") == "empresa.com.br"
    assert _dominio_email("sem-arroba") == ""
    assert _dominio_email(None) == ""


def test_mesmo_telefone():
    g = _grafo([
        {"cnpj": "11111111000111", "telefone": "(62) 3333-4444"},
        {"cnpj": "22222222000122", "telefone": "6233334444"},
    ])
    a = [x for x in calcular_score(g)["alertas"] if x["tipo"] == "mesmo_telefone"]
    assert a and a[0]["peso"] == PESOS["mesmo_telefone"]


def test_mesmo_email_dominio_ignora_provedor_generico():
    suspeito = _grafo([
        {"cnpj": "11111111000111", "email": "a@grupox.com.br"},
        {"cnpj": "22222222000122", "email": "b@grupox.com.br"},
    ])
    assert "mesmo_email_dominio" in [x["tipo"] for x in calcular_score(suspeito)["alertas"]]

    generico = _grafo([
        {"cnpj": "11111111000111", "email": "a@gmail.com"},
        {"cnpj": "22222222000122", "email": "b@gmail.com"},
    ])
    assert "mesmo_email_dominio" not in [x["tipo"] for x in calcular_score(generico)["alertas"]]


def test_mesmo_dono_dominio():
    g = _grafo([
        {"cnpj": "11111111000111", "dominio_dono": "99888777000166"},
        {"cnpj": "22222222000122", "dominio_dono": "99888777000166"},
    ])
    a = [x for x in calcular_score(g)["alertas"] if x["tipo"] == "mesmo_dono_dominio"]
    assert a and a[0]["peso"] == PESOS["mesmo_dono_dominio"]
    # sem enriquecimento (sem campo dominio_dono) → regra não dispara
    g2 = _grafo([{"cnpj": "11111111000111"}, {"cnpj": "22222222000122"}])
    assert "mesmo_dono_dominio" not in [x["tipo"] for x in calcular_score(g2)["alertas"]]


def test_ponte_nao_roda_sem_aprofundamento():
    empresas = [
        {"cnpj": "11111111000111", "razao_social": "ALFA", "qsa": [{"nome_socio": "LAZARO"}]},
    ]
    r = calcular_score(_grafo(empresas))  # sem aprofundamento
    assert "ponte_externa_aprofundada" not in [a["tipo"] for a in r["alertas"]]
