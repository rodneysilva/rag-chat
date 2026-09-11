"""Agente do HOST — era dos CONTAINERS (reescrito 11/09).

A API roda em container na VPS; os llama-server são CONTAINERS GPU nesta
estação (ragchat-llm :8090 / ragchat-embed :8081, compose
~/infra/services/ragchat-llm). O que a API não pode fazer — docker
start/stop — este agente faz: FastAPI mínimo na :8010 do host, 100%
independente do core (lê o .env da raiz com um parser local; nada de
importar core.modelos, que fala de processos NATIVOS que não existem mais).
Sobe sozinho no logon do Windows (Task Scheduler "RagChatAgente").

CICLO DE ENERGIA (pedido do dono 10/09):
  • embedding  → SEMPRE no ar. O restart: always cobre queda/reboot; o
    watchdog cobre um docker stop manual (religa em ≤30 s).
  • chat (LLM) → SOB DEMANDA: /llm/ligar ergue o container; o watchdog
    DERRUBA após 5 min sem atividade — atividade = métricas llamacpp
    (tokens processados + gerados + requisições em voo/na fila), lidas
    por docker exec no /metrics (mesma porta do servidor, Bearer da
    LLM_API_KEY).

TWO-STEP na borda: a carga do modelo (~90 s) passa do timeout ~100 s do
Cloudflare — /llm/ligar responde NA HORA (docker start) e o chamador
(VPS, modelos.garantir_llm) faz o polling pelo próprio túnel
(llm.disroy.org/v1/models) até o alias servir.

SEGURANÇA: exposto no túnel público (agente.disroy.org → traefik →
host.docker.internal:8010) — TODA chamada exige
`Authorization: Bearer <AGENTE_TOKEN>` (mesmo valor no .env da estação E
da VPS). Sem AGENTE_TOKEN definido, aceita sem token (uso local).

Uso (estação):  .venv/Scripts/pythonw.exe -X utf8 -m api.agente_host
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from pydantic import BaseModel

RAIZ = Path(__file__).resolve().parents[1]
ENV = RAIZ / ".env"
LLM_CONTAINER, EMBED_CONTAINER = "ragchat-llm", "ragchat-embed"
CHAT_PORTA = 8090
OCIOSIDADE_S = 5 * 60          # dono: "ocioso por mais de 5 minutos, derruba"
VARRERURA_S = 30               # cadência do watchdog


# ───────── .env minimalista (o agente não importa nada do core) ─────────
def env_ler() -> dict:
    dados = {}
    if ENV.is_file():
        for ln in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                # aspas envolvendo o valor são SINTAXE do dotenv (o app usa
                # python-dotenv, que as tira) — parser ingênuo que não tira
                # mandava "Bearer 'chave'" e o servidor dava 401
                dados[k.strip()] = v.strip().strip('"').strip("'")
    return dados


def _token() -> str:
    """AGENTE_TOKEN do ambiente OU do .env (Task Scheduler não carrega .env)."""
    return (os.getenv("AGENTE_TOKEN") or env_ler().get("AGENTE_TOKEN") or "").strip()


# ─────────────────────────── docker (subprocess) ────────────────────────
# o agente roda sob pythonw (sem console): todo docker.exe spawned aqui
# ganharia uma janela de console NOVA que pisca na tela do dono —
# CREATE_NO_WINDOW (0x08000000) esconde (pedido: "por que está abrindo
# uma janela sempre? precisa ficar em background")
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _docker(*args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          timeout=timeout, creationflags=_NO_WINDOW)


def _estado(container: str) -> str | None:
    """Status cru do docker: 'running', 'exited', 'created', 'dead'… (None
    = container ausente/docker fora). ⚠️ NÃO existe 'stopped' — comparação
    ingênua com ele fazia o /llm/ligar pular o docker start (bug REAL: a
    API chamou, o agente respondeu 200 e o container continuou 'exited')."""
    try:
        r = _docker("inspect", "-f", "{{.State.Status}}", container, timeout=15)
        saida = (r.stdout or "").strip()
        return saida if r.returncode == 0 and saida else None
    except Exception:
        return None


def _ligado(container: str) -> bool:
    return _estado(container) == "running"


def _parado(container: str) -> bool:
    """Existe e NÃO serve (exited/created/dead) — seguro dar docker start.
    None (docker fora/alvo ausente) NÃO é 'parado': sem certeza, não mexe."""
    return _estado(container) not in (
        None, "running", "restarting", "paused", "removing")


def _saudavel(container: str) -> bool:
    """Healthcheck DO PRÓPRIO compose (curl :809x/health) — sem depender de
    porta publicada: o agente pergunta ao daemon, não ao serviço."""
    try:
        r = _docker("inspect", "-f", "{{.State.Health.Status}}", container,
                    timeout=15)
        return (r.stdout or "").strip() == "healthy"
    except Exception:
        return False


def _curl_llm(caminho: str) -> dict | None:
    """curl DENTRO do container do chat — as portas não são publicadas no
    host; /metrics e /v1/models exigem o Bearer da LLM_API_KEY."""
    chave = (os.getenv("LLM_API_KEY") or env_ler().get("LLM_API_KEY") or "").strip()
    args = ["exec", LLM_CONTAINER, "curl", "-s", "-m", "10",
            f"http://localhost:{CHAT_PORTA}{caminho}"]
    if chave:
        args[-1:-1] = ["-H", f"Authorization: Bearer {chave}"]
    try:
        r = _docker(*args, timeout=20)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout else None
    except Exception:
        return None


def _alias_chat() -> str | None:
    dados = _curl_llm("/v1/models") or {}
    ids = [m.get("id") for m in dados.get("data", []) if m.get("id")]
    return ids[0] if ids else None


def _metricas_get() -> dict | None:
    """Contadores Prometheus do llama-server (só com --metrics). Devolve
    None quando o endpoint não responde (container subindo / sem métricas)
    — o watchdog trata None como ATIVIDADE, nunca como ociosidade."""
    chave = (os.getenv("LLM_API_KEY") or env_ler().get("LLM_API_KEY") or "").strip()
    args = ["exec", LLM_CONTAINER, "curl", "-s", "-m", "10",
            f"http://localhost:{CHAT_PORTA}/metrics"]
    if chave:
        args[-1:-1] = ["-H", f"Authorization: Bearer {chave}"]
    try:
        r = _docker(*args, timeout=20)
        if r.returncode != 0 or not r.stdout:
            return None
        vals = {}
        for ln in r.stdout.splitlines():
            partes = ln.split()
            if len(partes) == 2 and partes[0].startswith("llamacpp:"):
                try:
                    vals[partes[0]] = float(partes[1])
                except ValueError:
                    pass
        pegar = lambda k: vals.get(f"llamacpp:{k}")
        if pegar("prompt_tokens_total") is None:
            return None  # métrica básica ausente = resposta não é o /metrics
        return {"prompt": pegar("prompt_tokens_total"),
                "gerados": pegar("tokens_predicted_total"),
                "processando": pegar("requests_processing") or 0.0,
                "na_fila": pegar("requests_deferred") or 0.0}
    except Exception:
        return None


# ─────────────────────────── app FastAPI ────────────────────────────────
app = FastAPI(title="RagChat · agente do host (containers)")


@app.middleware("http")
async def exigir_token(request: Request, call_next):
    from fastapi.responses import JSONResponse
    token = _token()
    if token and request.headers.get("authorization") != f"Bearer {token}":
        return JSONResponse({"detail": "token do agente inválido"}, status_code=401)
    return await call_next(request)


class AtivarIn(BaseModel):
    modelo: str


@app.api_route("/saude", methods=["GET", "POST"])
def saude():
    return {"ok": True,
            "chat": _alias_chat() if _ligado(LLM_CONTAINER) else None,
            "chat_container": _estado(LLM_CONTAINER),
            "embed": _ligado(EMBED_CONTAINER) and _saudavel(EMBED_CONTAINER),
            "embed_container": _estado(EMBED_CONTAINER),
            "ocioso_s": _ocioso_s()}


@app.post("/llm/ligar")
def llm_ligar():
    """Ergue o container do chat e VOLTA NA HORA (two-step: a carga de ~90 s
    estouraria o timeout da borda — quem chama faz polling no túnel)."""
    if _parado(LLM_CONTAINER):
        r = _docker("start", LLM_CONTAINER, timeout=60)
        if r.returncode != 0:
            return {"ok": False, "erro": (r.stderr or "docker start falhou")[:200]}
        print(f"🧠 {LLM_CONTAINER} iniciado (chamada da API) — carga ~90 s")
    _marcar_atividade()  # boot conta como atividade: carência até esquentar
    return {"ok": True, "ligando": True, "estado": _estado(LLM_CONTAINER)}


@app.post("/llm/derrubar")
def llm_derrubar():
    _docker("stop", LLM_CONTAINER, timeout=120)
    print(f"⏹ {LLM_CONTAINER} parado (chamada da API)")
    return {"ok": True, "estado": _estado(LLM_CONTAINER)}


@app.post("/embed/garantir")
def embed_garantir():
    """Embedding SEMPRE no ar (pedido do dono) — religa e espera o health
    (carga <75 s; o chamador VPS aceita esperar até 180 s)."""
    if _parado(EMBED_CONTAINER):
        r = _docker("start", EMBED_CONTAINER, timeout=60)
        if r.returncode != 0:
            return {"ok": False, "erro": (r.stderr or "docker start falhou")[:200]}
        print(f"🧬 {EMBED_CONTAINER} religado pelo watchdog/garantir")
    t0 = time.time()
    while time.time() - t0 < 150:
        if _saudavel(EMBED_CONTAINER):
            return {"ok": True}
        time.sleep(5)
    return {"ok": _saudavel(EMBED_CONTAINER), "detalhe": "health não ficou verde em 150 s"}


@app.post("/ativar")
def ativar(body: AtivarIn):
    """Compat com a troca de modelo da UI — em containers o modelo é fixo do
    compose: serve para RELIGAR o container; alias divergente falha claro
    (trocar = editar o compose da estação e recriar o serviço llm)."""
    if _ligado(LLM_CONTAINER):
        atual = _alias_chat()
        if atual and atual.lower() != body.modelo.lower():
            return {"ok": False,
                    "erro": f"o container serve '{atual}' — troca de modelo em "
                            "containers = editar o compose (~/infra/services/"
                            "ragchat-llm) e recriar o serviço llm"}
    return llm_ligar()


# ─────────────────────────── watchdog ───────────────────────────────────
_ultimo_sinal: dict = {}     # último (métricas) visto do chat
_ultima_atividade: dict = {"t": time.time()}


def _marcar_atividade() -> None:
    _ultima_atividade["t"] = time.time()


def _ocioso_s() -> int | None:
    if not _ligado(LLM_CONTAINER):
        return None
    return int(time.time() - _ultima_atividade["t"])


def _varrer() -> None:
    """Um loop, duas regras do dono: embed nunca cai; chat cai ocioso."""
    while True:
        try:
            # 1. embedding SEMPRE no ar (docker stop manual / queda)
            if _parado(EMBED_CONTAINER):
                _docker("start", EMBED_CONTAINER, timeout=60)
                print(f"🧬 {EMBED_CONTAINER} religado (regra: sempre ativo)")

            # 2. chat: ocioso (métricas paradas E nada em voo) → derruba
            if _ligado(LLM_CONTAINER):
                m = _metricas_get()
                if m is None:
                    _marcar_atividade()   # subindo/métricas fora ≠ ocioso
                else:
                    sinal = (m["prompt"], m["gerados"])
                    if sinal != _ultimo_sinal.get("chat"):
                        _ultimo_sinal["chat"] = sinal
                        _marcar_atividade()
                    em_voo = (m["processando"] + m["na_fila"]) > 0
                    ocioso = time.time() - _ultima_atividade["t"] >= OCIOSIDADE_S
                    if ocioso and not em_voo:
                        _docker("stop", LLM_CONTAINER, timeout=120)
                        _ultimo_sinal.pop("chat", None)
                        print(f"💤 chat ocioso {OCIOSIDADE_S // 60} min — "
                              f"{LLM_CONTAINER} parado (religa na próxima "
                              "chamada)")
        except Exception as e:
            print(f"⚠️ watchdog: {e}")
        time.sleep(VARRERURA_S)


@app.on_event("startup")
def _boot():
    # sem spawns nativos: o boot só GARANTE o embedding (regra "sempre
    # ativo") — o chat nasce quando a primeira chamada chegar
    def _garantir_embed_boot():
        if _parado(EMBED_CONTAINER):
            _docker("start", EMBED_CONTAINER, timeout=60)
            print(f"🧬 boot: {EMBED_CONTAINER} religado (sempre ativo)")
    try:
        _garantir_embed_boot()
    except Exception as e:
        print(f"⚠️ boot embed: {e}")
    threading.Thread(target=_varrer, daemon=True, name="watchdog").start()


if __name__ == "__main__":
    # Task Scheduler roda sem cwd → ancora o processo na raiz do repo
    # (o .env e os imports de 'api.' dependem dela)
    os.chdir(RAIZ)
    # pythonw (sem console) zera stdout/stderr — watchdog/uvicorn narram
    # em arquivo (buffering=1: linha a linha, para ler com tail)
    if sys.stdout is None or sys.stderr is None:
        (RAIZ / "logs").mkdir(exist_ok=True)
        _dest = open(RAIZ / "logs" / "agente_host.log", "a", buffering=1,
                     encoding="utf-8")
        sys.stdout = sys.stderr = _dest
    uvicorn.run(app, host="127.0.0.1", port=8010)
