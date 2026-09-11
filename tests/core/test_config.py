"""reload() do config aplica TODAS as chaves no módulo.

Bug real (visto ao trocar o reranker para v2-m3 na VPS 11/09): RERANK_MODEL
não estava no `global` do reload — a linha `RERANK_MODEL = os.getenv(...)`
criava variável LOCAL e o atributo do módulo ficava para sempre no default
`bge-reranker-base`. Trocar o modelo pelo .env ou pela tela Sistema nunca
teve efeito (o snapshot `to_dict` mostrava o novo, o rerank usava o velho).
"""
import pytest

from core import config


@pytest.fixture
def env_de_mentira(tmp_path, monkeypatch):
    """Aponta o config para um .env temporário e RESTAURA o mundo no fim
    (reload mexe em estado global do módulo — não pode vazar p/ outros
    testes)."""
    original = config.ENV_FILE
    env = tmp_path / ".env"
    env.write_text("RERANKER=1\nRERANK_MODEL=BAAI/bge-reranker-v2-m3\n",
                   encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env)
    yield env
    config.ENV_FILE = original
    config.reload()


def test_reload_aplica_rerank_model_do_env(env_de_mentira):
    config.reload()
    assert config.RERANK_MODEL == "BAAI/bge-reranker-v2-m3"
