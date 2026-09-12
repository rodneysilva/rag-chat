"""🌐 API compatível OpenAI (/v1 — spec consulta_consolidada.md, regra 8).

Shape OpenAI de resposta e de ERRO, mesmo Bearer do login (401 JSON,
nunca redirect), stream SSE com [DONE], citations SEM coleção (regra 6) e
payload model/temperature aceito e ignorado (regra 5). O happy path roda
com MOCK_LLM — a máquina inteira pode estar desligada."""
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.base import auth, config


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def cab():
    """Bearer do login (token stateless emitido para o admin do .env —
    mesma validação do middleware, sem passar pela rota de senha)."""
    return {"Authorization": "Bearer " + auth.emitir_token(
        config.AUTH_ADMIN_USER)}


class TestAuth:
    def test_401_sem_token_shape_openai(self, client):
        r = client.get("/v1/models", follow_redirects=False)
        assert r.status_code == 401
        j = r.json()
        assert j["error"]["type"] == "invalid_request_error"
        assert j["error"]["code"] == "invalid_api_key"
        assert "location" not in r.headers      # SDK não segue redirect

    def test_models_lista_o_ativo(self, client, cab):
        r = client.get("/v1/models", headers=cab)
        assert r.status_code == 200
        j = r.json()
        assert j["object"] == "list"
        assert j["data"] and j["data"][0]["id"]


class TestCompletions:
    def test_sem_mensagem_user_400(self, client, cab):
        r = client.post("/v1/chat/completions", headers=cab, json={
            "messages": [{"role": "assistant", "content": "oi"}]})
        assert r.status_code == 400
        assert r.json()["error"]["type"] == "invalid_request_error"

    def test_shape_completion(self, client, cab, monkeypatch):
        monkeypatch.setattr(config, "MOCK_LLM", True)
        r = client.post("/v1/chat/completions", headers=cab, json={
            "model": "gpt-4o", "temperature": 0.9,   # aceitos e ignorados
            "messages": [{"role": "system", "content": "instruções"},
                         {"role": "user", "content": "pergunta"},
                         {"role": "assistant", "content": "resposta"},
                         {"role": "user", "content": "o que é o vatapá?"}]})
        assert r.status_code == 200
        j = r.json()
        assert j["object"] == "chat.completion"
        escolha = j["choices"][0]
        assert escolha["finish_reason"] == "stop"
        assert escolha["message"]["role"] == "assistant"
        assert isinstance(escolha["message"]["content"], str)
        assert set(j["usage"]) == {"prompt_tokens", "completion_tokens",
                                   "total_tokens"}
        assert "citations" in j                    # campo extra do RagAroy

    def test_stream_sse_termina_done(self, client, cab, monkeypatch):
        monkeypatch.setattr(config, "MOCK_LLM", True)
        r = client.post("/v1/chat/completions", headers=cab, json={
            "stream": True,
            "messages": [{"role": "user", "content": "o que é o vatapá?"}]})
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        assert "chat.completion.chunk" in r.text
        assert '"delta"' in r.text
        assert r.text.strip().endswith("data: [DONE]")

    def test_ambos_off_503_shape_openai(self, client, cab, monkeypatch):
        monkeypatch.setattr(config, "MOCK_LLM", False)
        monkeypatch.setattr(config, "RAG_ATIVO", False)
        monkeypatch.setattr(config, "LLM_ATIVO", False)
        r = client.post("/v1/chat/completions", headers=cab, json={
            "messages": [{"role": "user", "content": "o que é o vatapá?"}]})
        assert r.status_code == 503
        j = r.json()
        assert "error" in j and "detail" not in j   # shape OpenAI, não FastAPI
        assert "Consulta indisponível" in j["error"]["message"]

    def test_citations_sem_colecao(self, client, cab, monkeypatch):
        """Regra 6: fontes continuam visíveis, o NOME da coleção não —
        o cliente externo não vê infra interna."""
        from api.routers import openai_compat as oc

        def _fake(body, log=None):
            return {"answer": "resp", "model": "alias-x", "mode": "rag",
                    "tokens": {"entrada": 1, "saida": 2, "total": 3},
                    "docs": [{"titulo": "Vatapá", "score": 0.6,
                              "colecao": "culinaria", "content": "…"}]}
        monkeypatch.setattr(oc, "_processar_query", _fake)
        r = client.post("/v1/chat/completions", headers=cab, json={
            "messages": [{"role": "user", "content": "o que é o vatapá?"}]})
        cit = r.json()["citations"][0]
        assert "colecao" not in cit
        assert cit["titulo"] == "Vatapá"           # a fonte segue visível


class TestHistorico:
    """Última mensagem user = pergunta; anteriores = histórico com as
    MESMAS truncagens do hx_chat (últimas 4, assistant 220, user 400);
    system não tem papel (PROMPT_SYSTEM do .env é a fonte de instruções)."""

    def test_truncagens_e_system_fora(self):
        from api.routers.openai_compat import _Msg, _historico
        mensagens = [
            _Msg(role="system", content="instruções fixas"),
            _Msg(role="user", content="u" * 500),
            _Msg(role="assistant", content="a" * 300),
            _Msg(role="user", content="a pergunta de agora"),
        ]
        h = _historico(mensagens, ate=3)
        assert [m["role"] for m in h] == ["user", "assistant"]  # system fora
        assert h[0]["content"] == "u" * 400
        assert h[1]["content"].endswith("…") and len(h[1]["content"]) <= 221

    def test_vazio_devolve_none(self):
        from api.routers.openai_compat import _historico
        assert _historico([], 0) is None
