# Presença deste arquivo na raiz garante que o diretório do projeto entre no
# sys.path do pytest, permitindo os imports de pacote (skills, llm, etc.).
import pytest
import cache


@pytest.fixture(autouse=True)
def _cache_off():
    """Isola cada teste: zera o estado global do cache antes de rodar."""
    cache.configurar("off")
    yield
    cache.configurar("off")
