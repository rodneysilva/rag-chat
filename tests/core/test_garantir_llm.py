"""Ciclo FRIO do modelo de conversa (pedido do dono 10/09: "o llm só quando
for acionado e se ficar ocioso por mais de 5 minutos, pode derrubar e esperar
uma nova chamada para ligar").

A estação para o container do chat quando ocioso; quem religa é o
garantir_llm — TWO-STEP (POST /llm/ligar volta na hora; a espera é no
polling servido(forcar=True), porque a borda do Cloudflare corta ~100 s)."""
import pytest


def test_garantir_no_ar_nao_chama_agente(monkeypatch):
    """Modelo servindo → True imediato, zero chamadas ao agente."""
    from core import modelos
    chamadas = []
    monkeypatch.setattr(modelos, "servido",
                        lambda porta=None, forcar=False: "qwen2.5-coder-7b")
    monkeypatch.setattr(modelos, "_chamar_agente",
                        lambda cam, **kw: chamadas.append(cam) or {"ok": True})
    assert modelos.garantir_llm() is True
    assert chamadas == []


def test_garantir_frio_dois_passos_e_narra(monkeypatch):
    """Frio em container: POST /llm/ligar UMA vez (na hora) + polling até o
    alias servir — e o log do job narra o ligando→no ar."""
    from core import modelos
    ligados, logs = [], []
    estados = [None, None, "qwen2.5-coder-7b"]  # polling: 2× frio, 3ª no ar
    monkeypatch.setattr(modelos, "servido",
                        lambda porta=None, forcar=False:
                        (estados.pop(0) if forcar and estados else None))
    monkeypatch.setattr(modelos, "_chamar_agente",
                        lambda cam, **kw: ligados.append(cam) or {"ok": True})
    monkeypatch.setattr(modelos.config, "EM_CONTAINER", True)
    monkeypatch.setattr(modelos.time, "sleep", lambda s: None)
    assert modelos.garantir_llm(log=lambda m, g="modelo": logs.append(m)) is True
    assert ligados == ["/llm/ligar"]          # one-shot, não bloqueante
    assert any("FRIO" in m for m in logs)     # espera visível no job
    assert any("no ar" in m for m in logs)


def test_garantir_frio_que_nao_sobe_da_erro_claro(monkeypatch):
    from core import modelos
    # relógio FALSO: o `while time.time() - t0 < 300` mede tempo REAL —
    # com sleep em no-op ele giraria 300 s de relógio de verdade
    ticks = iter(range(0, 4000, 6))
    monkeypatch.setattr(modelos, "servido", lambda porta=None, forcar=False: None)
    monkeypatch.setattr(modelos, "_chamar_agente", lambda cam, **kw: {"ok": True})
    monkeypatch.setattr(modelos.config, "EM_CONTAINER", True)
    monkeypatch.setattr(modelos.time, "sleep", lambda s: None)
    monkeypatch.setattr(modelos.time, "time", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="não subiu na estação em 300 s"):
        modelos.garantir_llm(log=lambda m, g="modelo": None)


def test_servido_forcar_pula_a_leitura_do_cache(monkeypatch):
    """O None cacheado (TTL 10 s) não pode renascer no polling de 5 s —
    sem o forcar, garantir_llm esperaria para sempre 'vendo' o frio."""
    from core import modelos

    class _Resp:
        def json(self):
            return {"data": [{"id": "qwen2.5-coder-7b"}]}

    chamadas = []
    monkeypatch.setattr(modelos, "_servido_cache", {})
    monkeypatch.setattr(modelos.httpx, "get",
                        lambda *a, **kw: chamadas.append(1) or _Resp())
    monkeypatch.setattr(modelos.config, "LLM_BASE_URL",
                        "http://127.0.0.1:8090/v1")
    assert modelos.servido(modelos.CHAT_PORTA) == "qwen2.5-coder-7b"
    modelos.servido(modelos.CHAT_PORTA)          # dentro do TTL: cache
    assert len(chamadas) == 1
    modelos.servido(modelos.CHAT_PORTA, forcar=True)  # polling: consulta
    assert len(chamadas) == 2


def test_llm_factory_religa_local_e_pula_externo(monkeypatch):
    """A fábrica rag.llm() é o gargalo comum (reformulação, categorização,
    pesquisa) — garante o modelo local SEM override; com provedor externo
    a GPU da estação fica intocada."""
    from core import rag, modelos
    chamadas = []
    monkeypatch.setattr(modelos, "garantir_llm",
                        lambda log=None: chamadas.append(1))
    rag.set_override(None)
    rag.llm()
    assert len(chamadas) == 1
    rag.set_override({"provedor": "glm", "model": "glm-4.6",
                      "base_url": "https://api.example/v1", "api_key": "k"})
    rag.llm()
    rag.set_override(None)  # não vazar para outros testes (thread-local)
    assert len(chamadas) == 1
