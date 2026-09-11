"""Agente do HOST — o que o container NÃO pode fazer, ele faz.

A API roda em container (compose); os processos de GPU (llama-server)
pertencem ao HOST. Este agente é um FastAPI mínimo na :8010 do host que
expõe exatamente essas operações, e a API-container chama por
http://host.docker.internal:8010 (config AGENTE_HOST_URL) — na VPS, pelo
TÚNEL público configurado no .env (ex.: https://agente.seu-dominio.com).

No BOOT ele mesmo ergue o chat (alias do .env) e o embedding — não existe
mais "llama-server não subiu": subir o agente é subir tudo.

SEGURANÇA: quando AGENTE_HOST_URL é público (túnel), TODA chamada exige
`Authorization: Bearer <AGENTE_TOKEN>` (mesmo valor no .env da estação E
da VPS). Sem AGENTE_TOKEN definido, aceita sem token (uso local).

Uso (host):  python -X utf8 -m api.agente_host
"""
import os
import threading

import uvicorn
from fastapi import FastAPI, Request
from pydantic import BaseModel

from core import config, modelos

app = FastAPI(title="RagChat · agente do host")


@app.middleware("http")
async def exigir_token(request: Request, call_next):
    from fastapi.responses import JSONResponse
    token = (os.getenv("AGENTE_TOKEN") or "").strip()
    if token and request.headers.get("authorization") != f"Bearer {token}":
        return JSONResponse({"detail": "token do agente inválido"}, status_code=401)
    return await call_next(request)


class AtivarIn(BaseModel):
    modelo: str


class PortaIn(BaseModel):
    porta: int


@app.api_route("/saude", methods=["GET", "POST"])
def saude():
    return {"ok": True,
            "chat": modelos.servido(modelos.CHAT_PORTA),
            "embed": modelos.embedding_no_ar(),
            "vram_mi": modelos._vram_uso_mi()}


@app.post("/ativar")
def ativar(body: AtivarIn):
    """Troca de modelo ASSÍNCRONA: a carga de um GGUF passa dos ~100 s de
    timeout da borda do Cloudflare (HTTP 524 matava a chamada no meio) —
    responde NA HORA e a troca roda em thread própria; o chamador faz
    polling em /saude até o modelo pedido estar no ar."""
    def _rodar():
        try:
            modelos.ativar(body.modelo)
        except Exception as e:
            print(f"❌ troca em background falhou ({body.modelo}): {e}")
    threading.Thread(target=_rodar, daemon=True,
                     name=f"troca-{body.modelo}").start()
    return {"ok": True, "iniciada": body.modelo}


@app.post("/embed/garantir")
def embed_garantir():
    ok = modelos.garantir_embedding()
    return {"ok": ok}


@app.post("/embed/ligar")
def embed_ligar():
    return modelos.ligar_embedding_manual()


@app.post("/embed/desligar")
def embed_desligar():
    return modelos.desligar_embedding_manual()


@app.post("/parar_tudo")
def parar_tudo_motores():
    """⏹ Desmonta TODOS os motores de GPU NO HOST (portas + zombies pelo
    nome do processo) — a API-container proxya para cá."""
    return modelos.derrubar_todos_motores()


@app.post("/porta/derrubar")
def derrubar(body: PortaIn):
    return {"pids": modelos.derrubar_porta(body.porta, "agente-host")}


@app.on_event("startup")
def _boot():
    # ergue o que o .env manda — sem depender de mão humana
    def _subir():
        try:
            if modelos.llm_manual_off():
                print("🧠 llama-server DESLIGADO manualmente — boot NÃO sobe "
                      "(religue no badge 🧠 da webui)")
            elif not modelos.servido(modelos.CHAT_PORTA):
                m = next((x for x in modelos.listar()
                          if x["nome"] == config.LLM_MODEL), None)
                # PADRÃO COMPATÍVEL COM A VRAM (pedido do dono): o modelo do
                # .env que NÃO cabe (ou não existe) é TROCADÌO pelo melhor
                # chat compatível — o boot nunca tenta carregar o que a
                # placa não aguenta (OOM na madrugada)
                if m and not m.get("compativel", True):
                    print(f"⚠️ '{config.LLM_MODEL}' {m.get('motivo', '')} — "
                          "trocando pelo maior modelo COMPATÍVEL")
                    m = None
                if not m:
                    cand = [x for x in modelos.listar()
                            if x.get("categoria") == "chat"
                            and x.get("compativel", True)]
                    if cand:
                        m = max(cand, key=lambda x: x.get("gb") or 0)
                        print(f"🧠 padrão VRAM-compatível: {m['nome']} "
                              f"({m.get('gb')} GB)")
                if m:
                    modelos._subir_chat(m["nome"], m["caminho"])
                    print(f"✅ chat {m['nome']} no ar (boot do agente)")
                else:
                    print("⚠️ nenhum modelo de chat compatível com a VRAM "
                          "encontrado em MODELS_DIR — só o embedding sobe")
        except Exception as e:
            print(f"⚠️ chat não subiu no boot: {e}")
        try:
            if modelos.embed_manual_off():
                print("🧬 embedding DESLIGADO manualmente — boot NÃO sobe "
                      "(religue no badge 🧬 da webui)")
            else:
                modelos.garantir_embedding()
        except Exception as e:
            print(f"⚠️ embedding não subiu no boot: {e}")
    threading.Thread(target=_subir, daemon=True).start()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8010)
