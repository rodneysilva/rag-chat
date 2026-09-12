"""🌐 API COMPATÍVEL OPENAI (/v1/*) — Fase 6 da consulta consolidada.

Spec core/specs/consulta_consolidada.md, regra 8: clientes SDK (openai-py,
Continue, LobeChat…) apontam para cá e recebem o MESMO motor do chat —
POST /v1/chat/completions e GET /v1/models. A consulta inteira nasce da
config da administração (🎯 Consulta): `model`/`temperature` do payload
são ACEITOS e IGNORADOS (regra 5 — o payload não manda), a última
mensagem `user` vira a pergunta e as anteriores o histórico (mesmas
truncagens do hx_chat). Fontes voltam como `citations` SEM o nome da
coleção (regra 6 — o cliente externo não vê infra). Autenticação = mesmo
Bearer do login, tratado NO MIDDLEWARE com 401 JSON no shape OpenAI
(SDK não segue redirect)."""
from api.base import *  # noqa: F401,F403 — contrato do split

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()


class _Msg(BaseModel):
    role: str = "user"
    content: str = ""


class ChatCompletionIn(BaseModel):
    messages: list[_Msg] = []
    model: str | None = None          # aceito e ignorado (config manda)
    temperature: float | None = None  # idem — TEMP do .env é a fonte
    stream: bool = False


def _erro(status: int, mensagem: str, tipo: str = "invalid_request_error",
          code: str | None = None) -> JSONResponse:
    """Erro no SHAPE OpenAI — {"error":{message,type[,code]}} (spec regra 8)."""
    corpo = {"message": mensagem, "type": tipo}
    if code:
        corpo["code"] = code
    return JSONResponse(status_code=status, content={"error": corpo})


def _historico(mensagens: list[_Msg], ate: int) -> list[dict] | None:
    """Mensagens ANTERIORES à pergunta viram `history` — mesmas truncagens
    do hx_chat (follow-up só precisa do FIO: últimas 4, resposta anterior
    em 220 chars, pergunta em 400). `system`/`tool` não têm papel aqui: o
    PROMPT_SYSTEM do .env é a fonte de instruções fixas (config manda)."""
    hist: list[dict] = []
    for m in mensagens[:ate][-4:]:
        if not (m.content or "").strip():
            continue
        if m.role == "assistant":
            hist.append({"role": "assistant",
                         "content": m.content[:220].rstrip()
                         + ("…" if len(m.content) > 220 else "")})
        elif m.role == "user":
            hist.append({"role": "user", "content": m.content[:400]})
    return hist or None


@router.post("/v1/chat/completions")
def v1_chat_completions(body: ChatCompletionIn):
    """🚪 única porta SDK: roda _processar_query (SÍNCRONO, threadpool) com
    a resolução consolidada — modo/escopo/MCPs vêm do 🎯 Consulta, nunca
    do payload."""
    # última mensagem user = pergunta; nada antes dela existe para nós
    idx = max((i for i, m in enumerate(body.messages)
               if m.role == "user" and (m.content or "").strip()),
              default=-1)
    if idx < 0:
        return _erro(400, "no user message found in 'messages'",
                     code="missing_user_message")
    if body.model or body.temperature is not None:
        print("🌐 /v1: model/temperature do payload IGNORADOS — a consulta "
              "nasce da config da administração (Sistema → 🎯 Consulta)")
    pergunta = body.messages[idx].content.strip()
    corpo = QueryIn(question=pergunta, history=_historico(body.messages, idx),
                    job=False)
    try:
        res = _processar_query(corpo, log=lambda m, g="geral": None)
    except HTTPException as e:
        detalhe = e.detail if isinstance(e.detail, str) else json.dumps(e.detail)
        # 503 da consulta consolidada (RAG+LLM off) e cia chegam com a CAUSA
        return _erro(e.status_code, detalhe, "server_error" if e.status_code >= 500
                     else "invalid_request_error")
    except Exception as e:
        return _erro(500, f"consulta falhou: {str(e)[:200]}", "server_error")
    finally:
        rag.set_override(None)  # thread do pool é reusada (padrão do query)

    modelo = res.get("model") or config.LLM_MODEL
    resposta = str(res.get("answer") or "")
    _tk = res.get("tokens") or {}
    # citations: fontes SEM coleção (regra 6 — cliente externo não vê infra)
    citations = [{k: v for k, v in d.items() if k != "colecao"}
                 for d in (res.get("docs") or []) if isinstance(d, dict)]
    cid = "chatcmpl-" + uuid.uuid4().hex[:12]
    criado = int(time.time())
    if not body.stream:
        return {
            "id": cid, "object": "chat.completion", "created": criado,
            "model": modelo,
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": resposta},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": _tk.get("entrada", 0),
                      "completion_tokens": _tk.get("saida", 0),
                      "total_tokens": _tk.get("total", 0)},
            "citations": citations,
        }

    # ⚡ STREAM: SSE FATIANDO a resposta final (a geração interna não é
    # token-a-token nesta iteração — o contrato [DONE]/chunk é o que o
    # cliente SDK exige; os pedaços saem imediatamente)
    def _sse(obj) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    def _gen():
        def _chunk(delta: dict, fim=None) -> str:
            return _sse({"id": cid, "object": "chat.completion.chunk",
                         "created": criado, "model": modelo,
                         "choices": [{"index": 0, "delta": delta,
                                      "finish_reason": fim}]})
        yield _chunk({"role": "assistant"})
        for i in range(0, len(resposta), 24):
            yield _chunk({"content": resposta[i:i + 24]})
        yield _chunk({}, fim="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store",
                                      "X-Accel-Buffering": "no"})


@router.get("/v1/models")
def v1_models():
    """Lista o modelo ATIVO (lido do servidor — mesma fonte do badge 🧠).
    Um único id: a consulta consolidada não tem seletor por cliente."""
    nome = modelos.servido(modelos.CHAT_PORTA) or config.LLM_MODEL
    return {"object": "list",
            "data": [{"id": nome, "object": "model", "created": 0,
                      "owned_by": "ragaroy",
                      "serving": bool(modelos.servido(modelos.CHAT_PORTA))}]}
