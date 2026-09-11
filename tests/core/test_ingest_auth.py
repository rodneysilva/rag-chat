"""Auth Bearer das chamadas aos llama-server (chat/embed com --api-key).

Bug real: os servidores subiram com --api-key (túneis públicos
llm/embed.disroy.org) e o health-check `_require` chamava /v1/models SEM
header — 401 lia como 'embedding quebrado' com o servidor saudável no ar
(pesquisa/ingestão/preview caíam na primeira linha do job)."""
import pytest


class _Resp:
    status_code = 200


def test_require_envia_bearer_com_chave(monkeypatch):
    from core import ingest
    monkeypatch.setattr(ingest.config, "LLM_API_KEY", "chave-teste", raising=False)
    capturado = {}

    def _get(url, timeout=0, headers=None):
        capturado.update(url=url, headers=headers)
        return _Resp()

    monkeypatch.setattr(ingest.httpx, "get", _get)
    ingest._require("http://x/v1/models", "embedding")
    assert capturado["headers"].get("Authorization") == "Bearer chave-teste"


def test_require_sem_chave_nao_envia_header(monkeypatch):
    from core import ingest
    monkeypatch.setattr(ingest.config, "LLM_API_KEY", "", raising=False)
    capturado = {}

    def _get(url, timeout=0, headers=None):
        capturado.update(url=url, headers=headers)
        return _Resp()

    monkeypatch.setattr(ingest.httpx, "get", _get)
    ingest._require("http://x/v1/models", "embedding")
    assert not capturado["headers"]


def test_gateways_llm_embed_usam_a_mesma_chave():
    from core import gateways
    assert gateways.SERVICOS["llm"][2] == "LLM_API_KEY"
    assert gateways.SERVICOS["embed"][2] == "LLM_API_KEY"


def test_require_401_continha_subindo_erro(monkeypatch):
    """A mensagem de erro continua apontando o serviço e o código HTTP."""
    from core import ingest

    class _Err:
        status_code = 401

    monkeypatch.setattr(ingest.httpx, "get", lambda *a, **k: _Err())
    with pytest.raises(RuntimeError, match="respondeu HTTP 401"):
        ingest._require("http://x/v1/models", "Servidor de embedding (BGE-M3)")
