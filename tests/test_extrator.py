"""Testes do chunking e da mesclagem da extração (sem LLM)."""
from extrator.extrator import _chunks, _chave_empresa, _merge_extracoes


def test_chunks_cobre_todo_o_texto_com_sobreposicao():
    texto = "".join(str(i % 10) for i in range(25_000))
    partes = list(_chunks(texto, 15_000, 1_000))
    assert len(partes) == 2
    assert partes[0] == texto[:15_000]
    assert partes[1] == texto[14_000:25_000]          # passo = 15000-1000
    assert partes[0][-1_000:] == partes[1][:1_000]     # sobreposição de 1000


def test_chunks_texto_curto_um_bloco():
    assert list(_chunks("abc", 15_000, 1_000)) == ["abc"]


def test_chave_empresa():
    assert _chave_empresa({"cnpj": "11.111.111/0001-11"}) == "cnpj:11111111000111"
    assert _chave_empresa({"razao_social": "Alfa Ltda"}) == "nome:ALFA LTDA"


def test_merge_dedup_por_cnpj_e_preenche_campos():
    r1 = {"meta": {"numero": "020/2026", "orgao": None},
          "empresas": [{"cnpj": "11.111.111/0001-11", "razao_social": "A", "lance": None}]}
    r2 = {"meta": {"numero": None, "orgao": "HMTJ"},
          "empresas": [
              {"cnpj": "11111111000111", "razao_social": "A", "lance": "R$ 10,00"},  # mesma raiz/dígitos
              {"cnpj": "22.222.222/0001-22", "razao_social": "B"}]}  # só no 2º bloco
    out = _merge_extracoes([r1, r2])
    assert out["meta"] == {"numero": "020/2026", "orgao": "HMTJ"}
    assert len(out["empresas"]) == 2                       # A deduplicada, B incluída
    a = [e for e in out["empresas"] if e["razao_social"] == "A"][0]
    assert a["lance"] == "R$ 10,00"                        # campo nulo preenchido pelo 2º bloco


def test_merge_descarta_empresa_sem_chave():
    out = _merge_extracoes([{"empresas": [{"cnpj": None, "razao_social": ""}]}])
    assert out["empresas"] == []
