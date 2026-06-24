"""Testes da camada de cache/replay (sem rede — fn é uma função fake)."""
import pytest
import cache


def test_off_chama_sempre_e_registra():
    cache.configurar("off")
    chamadas = []
    fn = lambda: (chamadas.append(1), {"v": 1})[1]
    assert cache.executar("t", {"k": 1}, fn, rotulo="r") == {"v": 1}
    assert cache.executar("t", {"k": 1}, fn, rotulo="r") == {"v": 1}
    assert len(chamadas) == 2            # off não cacheia: chama toda vez
    assert cache.store() == {}           # nada gravado
    assert len(cache.registros()) == 2
    assert cache.registros()[0]["fonte"] == "rede"


def test_record_grava_e_replay_serve_sem_chamar():
    cache.configurar("record")
    chamadas = []
    fn = lambda: (chamadas.append(1), {"v": 42})[1]
    cache.executar("http_get", {"url": "x"}, fn)
    assert len(chamadas) == 1
    store = cache.store()
    assert len(store) == 1

    # replay com o store gravado: NÃO chama fn
    cache.configurar("replay", store=store)
    chamadas.clear()
    boom = lambda: (_ for _ in ()).throw(AssertionError("não deveria chamar"))
    assert cache.executar("http_get", {"url": "x"}, boom) == {"v": 42}
    assert chamadas == []
    assert cache.registros()[0]["fonte"] == "replay"


def test_replay_miss_levanta():
    cache.configurar("replay", store={})
    with pytest.raises(cache.ReplayMiss):
        cache.executar("http_get", {"url": "ausente"}, lambda: {"v": 0})


def test_chave_estavel_independe_da_ordem():
    cache.configurar("record")
    fn = lambda: {"v": 1}
    cache.executar("t", {"a": 1, "b": 2}, fn)
    # mesma chamada com params em ordem diferente → mesma chave (não regrava)
    cache.executar("t", {"b": 2, "a": 1}, lambda: {"v": 999})
    assert len(cache.store()) == 1


def test_modo_invalido():
    with pytest.raises(ValueError):
        cache.configurar("turbo")


class _FakeResp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200
    def raise_for_status(self):
        pass
    def json(self):
        return self._p


def test_http_get_record_e_replay(monkeypatch):
    chamadas = []
    def fake_get(url, headers=None, params=None, timeout=15):
        chamadas.append(url)
        return _FakeResp({"ok": True, "url": url})
    monkeypatch.setattr(cache.httpx, "get", fake_get)

    cache.configurar("record")
    body, status = cache.http_get("https://api/x", headers={"Authorization": "SECRETO"})
    assert body == {"ok": True, "url": "https://api/x"} and status == 200
    assert len(chamadas) == 1
    # headers (segredo) não vazam na trilha
    assert "SECRETO" not in str(cache.registros())

    store = cache.store()
    cache.configurar("replay", store=store)
    chamadas.clear()
    body2, _ = cache.http_get("https://api/x", headers={"Authorization": "SECRETO"})
    assert body2 == body
    assert chamadas == []  # replay não acessa a rede
