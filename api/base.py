"""Infraestrutura compartilhada da API (helpers, templates, estado).

Gerado no split Fase 1: TUDO que não é rota vive aqui; os routers
fazem `from api.base import *` (contrato: __all__ explícito abaixo).
Mudança de comportamento NÃO acontece aqui sem prova de paridade
(docs/arquitetura.md).
"""
import asyncio
import json
import os
import re
import uuid
from itertools import count
from pathlib import Path
from typing import Literal
import threading
import time
import httpx
from dotenv import set_key
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from core import agent, auth, bussola, catalog, config, contadores, executor, grafo, hf, limpeza, modelos, mcp_registry, rag, rerank, sessions
from core import historico, resolucoes, telemetria
from core.linguagens import LINGUAGENS
from core.auto import responde_auto, _web_aprofundado
from core.analyze import analyze_all
from core.enrich import enrich_collection
from core.higieniza import higienizar_colecao
from core.ingest import ingest_docs, ingest_folder
from core.seed import seed_collection
from fastapi.templating import Jinja2Templates  # noqa: E402

__all__ = [
    "PASTA_LOGS_JOBS",
    "JobRegistry",
    "_novo_job",
    "_podar_concluidos",
    "asyncio",
    "json",
    "os",
    "re",
    "uuid",
    "count",
    "Path",
    "Literal",
    "threading",
    "time",
    "httpx",
    "set_key",
    "FastAPI",
    "File",
    "Form",
    "HTTPException",
    "Request",
    "UploadFile",
    "CORSMiddleware",
    "FileResponse",
    "HTMLResponse",
    "JSONResponse",
    "PlainTextResponse",
    "RedirectResponse",
    "Response",
    "StaticFiles",
    "BaseModel",
    "QdrantClient",
    "PointStruct",
    "agent",
    "auth",
    "bussola",
    "catalog",
    "config",
    "contadores",
    "executor",
    "grafo",
    "hf",
    "limpeza",
    "modelos",
    "mcp_registry",
    "rag",
    "rerank",
    "sessions",
    "historico",
    "resolucoes",
    "telemetria",
    "LINGUAGENS",
    "responde_auto",
    "_web_aprofundado",
    "analyze_all",
    "enrich_collection",
    "higienizar_colecao",
    "ingest_docs",
    "ingest_folder",
    "seed_collection",
    "Jinja2Templates",
    "_hl",
    "RAIZ_PROJETO",
    "_despachar",
    "_subir_executor",
    "_preaquecer_modelos",
    "_ROTAS_PUBLICAS",
    "COOKIE_TOKEN",
    "_LOGIN_TENTATIVAS",
    "_LOGIN_JANELA_S",
    "_LOGIN_MAX",
    "_usuario",
    "_usuario_ok",
    "_auth_middleware",
    "LoginIn",
    "_limpar_tentativas",
    "_cookie",
    "_exigir_admin",
    "IngestIn",
    "HigienizarIn",
    "VarreduraIn",
    "SeedIn",
    "QueryIn",
    "MCP_WEB",
    "ModeloAtivarIn",
    "SessionIn",
    "McpIn",
    "DocEditIn",
    "DocDeleteIn",
    "SettingsIn",
    "_ENV_PROIBIDAS",
    "_RE_ENV_OK",
    "COLECOES_SISTEMA",
    "BASE_UNIFICADA",
    "_check",
    "TEMPLATES",
    "_jinja_strftime",
    "SESSAO_COOKIE",
    "_versao_static",
    "_card_codigo",
    "_md_basico",
    "_md_fallback",
    "_paginas_ctx",
    "_sessao_id",
    "_msgs_da_sessao",
    "SandboxIn",
    "_proxy_app_api",
    "_pag_fora",
    "_RE_CHAVE_APP",
    "_job_ativo_ctx",
    "_palco_response",
    "_campos_config",
    "_DICAS_CAMPO",
    "_RE_ANSI",
    "_RE_BARRA",
    "_RE_PCT",
    "_linhas_visual",
    "_scroll_todos",
    "trocos_label",
    "_jobs_ativos",
    "_SCAN_CACHE",
    "_SCAN_CACHE_TTL",
    "_scan_collections",
    "_scan_invalidar",
    "_ATIVOS_CACHE",
    "modelos_ativos",
    "_STATUS_CACHE",
    "UPLOAD_MAX",
    "_EXTS_UPLOAD",
    "_manutencao",
    "ManutencaoIn",
    "_manutencao_disparar",
    "_MASCARA",
    "_INGEST_ETAPAS",
    "_ingest",
    "_ingest_log",
    "HfIn",
    "_preview",
    "PreviewIn",
    "PreviewAplicarIn",
    "_preview_disparar",
    "WebSalvarIn",
    "_pesquisa",
    "PesquisaIn",
    "SnapshotRestaurarIn",
    "_higieniza",
    "_limpeza",
    "_sbx",
    "_LOGS_DIR",
    "_LOGS_FONTES",
    "LOG_TAIL_LINHAS",
    "_mais_recente",
    "_sanear_caminho",
    "ZipIn",
    "_EXTS_ANEXO",
    "ANEXO_MAX_CHARS",
    "_extrair_anexo",
    "_erro_modelo",
    "_seed",
    "_varredura",
    "_bases_consultadas",
    "_query",
    "_conv",
    "_APAGANDO",
    "_apagando_do_usuario",
    "_query_log",
    "ProvedorIn",
    "_RE_TEMPO",
    "_e_pergunta_tempo",
    "_resposta_relogio",
    "_RE_PEDE_WEB",
    "_pede_web",
    "_processar_query",
    "_RE_SID",
    "_sid_valido",
    "SESSOES_QDRANT",
    "_embed_sessao",
    "McpTestarIn",
    "_mcp",
    "McpInstalarEntradaIn",
    "McpInstalarIn",
]


# ═══ CACHE-BUSTING dos estáticos ═════════════════════════════════════
# O Cloudflare cacheia /static/* agressivamente (HIT mesmo após deploy).
# Versão = hash curto do CONTEÚDO: qualquer mudança no CSS muda a URL
# (?v=abc123) e o CDN busca do container na hora — sem purgar nada.
import hashlib as _hl

# domínio de jobs (extraído no split — re-export p/ compat)
from core.jobs import PASTA_LOGS_JOBS, JobRegistry, TODOS_JOBS, _novo_job, _podar_concluidos, JobNaoEncontrado  # noqa: F401
"""
API FastAPI: status dos serviços, configurações (.env), ingestão e consulta.
Também serve a webui (build React em webui/dist/; sem build, cai na antiga
webui/legacy.html, acessível também em /legacy).

Rodar a partir da raiz do projeto (rag-llama):
    python -m uvicorn api.app:app --port 8000
Depois abrir: http://localhost:8000
"""


RAIZ_PROJETO = Path(__file__).resolve().parent.parent  # (webui React removida — UI é HTMX+Jinja)


auth.bootstrap_admin()  # cria o usuário inicial do .env (uma vez)


def _despachar(fabricar, kind: str, payload: dict,
               reg: "JobRegistry | None" = None) -> None:
    """Executa um job no EXECUTOR ASYNC; sem event loop (scripts CLI) cai
    para thread direta. Com `reg` informado, a entrada de status já existe
    ANTES do return (status nunca dá 404 entre despacho e pickup).

    `fabricar(payload)` devolve o runner (closure) — contrato inalterado
    das 21 fábricas do sistema."""
    jid = payload.get("job") or uuid.uuid4().hex
    payload = {**payload, "job": jid}
    if reg is not None:
        reg.iniciar(jid)
        try:
            from core import executor as _exec
            na_frente = getattr(_exec.fila, "qsize", lambda: 0)()
            if na_frente:
                reg.log(jid, f"⏳ fila: {na_frente} job(s) na frente "
                             "(execução serial — um por vez pela GPU)",
                        etapa="geral")
        except Exception:
            pass

    # HISTÓRICO: embrulha a FÁBRICA — cobre o caminho async E o de thread
    fabricar_puro = fabricar

    def fabricar_com_historico(p: dict):
        rodar_puro = fabricar_puro(p)

        def rodar():
            t0 = time.time()
            try:
                return rodar_puro()
            finally:
                try:
                    est = (reg.jobs.get(p.get("job")) if reg else None) or {}
                    resumo = est.get("result")
                    # caminho do log COMPLETO em disco (logs/jobs/{job}.jsonl)
                    caminho_log = (f"logs/jobs/{p.get('job')}.jsonl"
                                   if reg and (PASTA_LOGS_JOBS
                                               / f"{p.get('job')}.jsonl").exists()
                                   else None)
                    historico.registrar(
                        kind, f"{kind} {p.get('job')}", time.time() - t0,
                        job=p.get("job"), ok=not est.get("error"),
                        erro=(est.get("error") or None),
                        linhas=len(est.get("lines") or []),
                        log=caminho_log,
                        resumo=(json.dumps(resumo, ensure_ascii=False)[:300]
                                if resumo else None))
                except Exception:
                    pass
        return rodar

    fabricar = fabricar_com_historico
    rodar = fabricar(payload)
    if not callable(rodar):
        # 🚨 fábrica FORA DO CONTRATO (executa no corpo em vez de devolver
        # rodar): o corpo JÁ RODOU nesta thread — enfileirar executaria
        # TUDO DE NOVO (bug real do sandbox 2x). Não despacha; avisa alto.
        print(f"🚨 fábrica de '{kind}' executou no corpo (devolve "
              f"{type(rodar).__name__} em vez de runner) — corrigir para "
              "def fabricar(p): …; return rodar. Job NÃO enfileirado "
              "(evitaria execução dupla)")
        return
    if executor.despachar(kind, jid, payload, fabricar):
        if reg is not None:
            reg.jobs[jid]["picked"] = True   # entregue ao executor
        return
    # sem event loop (CLI/testes): thread direta, como sempre foi
    if reg is not None:
        reg.jobs[jid]["picked"] = True
    threading.Thread(target=rodar, daemon=True).start()


async def _subir_executor():
    """Sobe o worker async DENTRO do event loop do uvicorn."""
    from core import executor as _exec
    _exec.iniciar(log=lambda m: print(f"⚙️ {m}"))


# ⏱️ PRÉ-AQUECIMENTO dos modelos de CPU (pedido do dono — "por que demorou
# tanto?"): reranker (~2,3 GB) e tradutor (~300 MB) são LAZY e a 1ª pergunta
# pagava o download + carga. Uma thread daemon aquece no BOOT (5 s de folga
# para a API subir primeiro); falha em silêncio — o comportamento lazy
# original segue como fallback.
def _preaquecer_modelos() -> None:
    def _aq():
        time.sleep(5)
        try:
            if rerank.disponivel() and getattr(config, "RERANKER", True):
                rerank.notas_de("aquecimento", ["texto de aquecimento"],
                                log=lambda m, g="": print(f"🎛️ {m}"))
                print("🎛️ reranker pré-aquecido no boot — a 1ª pergunta "
                      "não paga o carregamento")
        except Exception as e:
            print(f"🎛️ pré-aquecimento do reranker pulado: {str(e)[:80]}")
        try:
            from core import tradutor as _tradutor
            if _tradutor.disponivel() and getattr(config, "TRADUTOR", True):
                # o resultado confere sucesso DE VERDADE — traduzir devolve
                # None em erro engolido e o "pré-aquecido" não pode mentir
                if _tradutor.traduzir("kitchen",
                                      log=lambda m, g="": print(m)):
                    print(_tradutor.palavra(
                        "MSG_PREAQUECIDO",
                        "⇄ tradutor pré-aquecido no boot — trechos EN saem "
                        "traduzidos sem pagar a 1ª carga"))
        except Exception as e:
            print(f"⇄ pré-aquecimento do tradutor pulado: {str(e)[:80]}")
    threading.Thread(target=_aq, daemon=True,
                     name="preaquecer-modelos").start()


_preaquecer_modelos()


# rotas que não exigem login: auth em si, status (o lock da LLM funciona
# pré-login) e os arquivos estáticos/mídia (aceitam ?token= também)
_ROTAS_PUBLICAS = {"/api/auth/login", "/api/auth/register", "/api/status"}


# cookie da sessão (httpOnly): <img>/<video> não mandam header Authorization
# — com o cookie a mídia autentica sozinha e o token sai da query string
COOKIE_TOKEN = "ragchat_token"


# rate limit do login: {chave ip|usuário: [timestamps das tentativas]}
_LOGIN_TENTATIVAS: dict[str, list[float]] = {}


_LOGIN_JANELA_S = 300   # 5 min


_LOGIN_MAX = 8          # tentativas por janela


def _usuario(request: Request) -> str:
    """Usuário autenticado da requisição (header Bearer, cookie ou ?token=)."""
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip() or \
        request.cookies.get(COOKIE_TOKEN, "") or \
        request.query_params.get("token", "")
    user = auth.usuario_do_token(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="faça login para usar o sistema")
    return user


def _usuario_ok(request: Request) -> bool:
    """Mesma checagem SEM levantar exceção (rotas com auth alternativo,
    como o preview da sandbox via token HMAC do subdomínio)."""
    try:
        return bool(_usuario(request))
    except HTTPException:
        return False


async def _auth_middleware(request: Request, call_next):
    caminho = request.url.path
    if caminho.startswith("/api/") and caminho not in _ROTAS_PUBLICAS \
            and not caminho.startswith("/api/auth/"):
        try:
            _usuario(request)
        except HTTPException:
            return JSONResponse(status_code=401,
                                content={"detail": "faça login para usar o sistema"})
    if not caminho.startswith(("/api/", "/static", "/sandbox/")) and caminho != "/entrar":
        # páginas e /hx/*: sem login → volta para o /entrar (HTMX segue o
        # redirect). /sandbox/* TEM AUTH PRÓPRIO (token HMAC curto do
        # subdomínio sandbox.disroy.org — cookie não atravessa subdomínios)
        try:
            _usuario(request)
        except HTTPException:
            return RedirectResponse("/entrar", status_code=303)
    resposta = await call_next(request)
    # o frontend detecta 401 e volta para o login
    # ── RESGATE de URLs ABSOLUTAS do app temporário: o Flask/FastAPI gera
    #    /static/x.css e Location: /login SEM a chave da URL pública — o
    #    pedido cai em 404 na API. Se o REFERER aponta para um link de app
    #    válido, o pedido vai PARA O APP (o navegador está "dentro" dele).
    if resposta.status_code == 404:
        ref = request.headers.get("referer", "")
        # aceita COM e SEM slug de sessão: /sandbox/app/{sid}/{chave}/…
        m = re.search(r"/sandbox/app/(?:[\w\-]+/)?(\d+\.\d+\.[0-9a-f]+)", ref)
        if m:
            from core import sandbox as _sb
            porta = _sb.chave_app_ok(m.group(1))
            if porta and request.method in ("GET", "POST", "HEAD"):
                try:
                    return await _proxy_app_api(porta, request,
                                                request.url.path,
                                                chave=m.group(1))
                except HTTPException:
                    pass   # app caiu no meio: segue o 404 original
    return resposta


class LoginIn(BaseModel):
    user: str
    senha: str


def _limpar_tentativas(agora: float) -> None:
    """Descarta janelas velhas (o dicionário não cresce para sempre)."""
    for chave, ts in list(_LOGIN_TENTATIVAS.items()):
        vivos = [t for t in ts if agora - t < _LOGIN_JANELA_S]
        if vivos:
            _LOGIN_TENTATIVAS[chave] = vivos
        else:
            _LOGIN_TENTATIVAS.pop(chave, None)


def _cookie(dados: dict, token: str) -> JSONResponse:
    """Resposta JSON com a sessão também em cookie httpOnly (mesma validade
    do token — <img>/<video> autenticam sozinhos, sem token na query)."""
    resp = JSONResponse(dados)
    resp.set_cookie(COOKIE_TOKEN, token, max_age=auth.TOKEN_DIAS * 86400,
                    httponly=True, samesite="lax")
    return resp


def _exigir_admin(request: Request) -> str:
    """Configurações e troca de modelo são exclusivas do operador dono
    (AUTH_ADMIN_USER) — os demais perfis usam o sistema, não o administram."""
    user = _usuario(request)
    if user != config.AUTH_ADMIN_USER:
        raise HTTPException(status_code=403,
                            detail="apenas o administrador altera configurações "
                                   "e modelos")
    return user



class IngestIn(BaseModel):
    folder: str
    collection: str | None = None  # categoria/coleção (padrão: a do .env)
    rapido: bool = True  # modo lote (DEFAULT — pedido do dono: ingestão é


class HigienizarIn(BaseModel):
    collection: str  # coleção a limpar (ruído de página, duplicados, re-embed)


class VarreduraIn(BaseModel):
    collection: str  # coleção a varrer com a LLM (lixo claro é apagado)


class SeedIn(BaseModel):
    assunto: str  # qualquer tema: "psicanálise", "medicina", um framework…
    colecao: str | None = None  # nome da coleção (padrão: slug do assunto)
    fontes: int = 8  # máximo de fontes aprovadas na curadoria


class QueryIn(BaseModel):
    question: str
    collection: str | None = None  # uma coleção (compatibilidade)
    collections: list[str] | None = None  # várias coleções no mesmo contexto
    mode: Literal["rag", "hibrido", "livre", "auto"] = "rag"  # 422 se inventar modo
    mcps: list[str] | None = None  # servidores MCP que participam do híbrido
    history: list[dict] | None = None  # mensagens anteriores do chat
    sessao: str | None = None  # id da sessão do chat (trava enquanto processa)
    estado_agente: dict | None = None  # retomada: estado devolvido num "pendente"
    aprovacao: dict | None = None  # {ferramenta, argumento, decisao: uma_vez|sessao|negar}
    aprovacoes_sessao: dict | None = None  # {ferramenta: "sessao"} — não perguntar mais
    model: str | None = None  # modelo de conversa solicitado (troca se diferente)
    provider: str | None = None  # sempre enviado junto (hoje: llama-server)
    job: bool = False  # True → roda em 2º plano e devolve {job} (webui: logs em tempo real, imune ao timeout do proxy — mata o 524)


# 🔎 "MCP" NATIVO de busca web: aparece no seletor do chat junto dos
# servidores registrados; marcado = o motor de busca do RagAroy entra no
# contexto da resposta (páginas INTEIRAS, não snippets — pedido do dono:
# "selecionar o mcp de motor de busca para contextualizar a sessão").
MCP_WEB = "pesquisa-web"


class ModeloAtivarIn(BaseModel):
    modelo: str  # alias do registro (core/modelos.py)
    provider: str | None = None  # informativo (hoje só llama-server)


class SessionIn(BaseModel):
    id: str | None = None  # null = nova sessão
    titulo: str = ""  # vazio = usa a primeira pergunta
    modo: str = ""
    colecoes: list[str] | None = None
    aprovacoes: dict | None = None  # {ferramenta: "sessao"} liberadas pelo operador
    messages: list[dict]  # [{role, content}]
    raw: list[dict] | None = None  # mensagens COMPLETAS (docs/fontes, tokens, mídia)


class McpIn(BaseModel):
    nome: str
    transport: str  # "stdio" | "http" | "sse"
    command: str = ""  # stdio: executável (ex.: python, npx)
    args: list[str] = []  # stdio: argumentos do comando
    url: str = ""  # http/sse: endereço do servidor


class DocEditIn(BaseModel):
    collection: str
    id: str
    page_content: str | None = None  # novo texto (re-embeda o vetor)
    metadata: dict | None = None  # campos de metadata a atualizar/merjar


class DocDeleteIn(BaseModel):
    collection: str
    ids: list[str]


class SettingsIn(BaseModel):
    values: dict[str, str]


# chaves do .env que NUNCA podem vir de um instalador de MCP (permitem
# sequestrar a auth/infra: AUTH_SECRET forja token de admin, LLM_* redireciona
# o chat etc.) — além destas, só maiúsculas/underline simples
_ENV_PROIBIDAS = {"AUTH_SECRET", "AUTH_ADMIN_USER", "AUTH_ADMIN_PASS",
                  "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY",
                  "EMBED_BASE_URL", "EMBED_MODEL",
                  "QDRANT_URL", "RAGAROY_CONTAINER", "MODELS_DIR",
                  "LLAMA_BIN", "SERPER_API_KEY"}


_RE_ENV_OK = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")


# Coleções de SISTEMA: funcionam por dentro mas não aparecem na webui
# (catálogo, contexto de mídia, prompts de mídia, sessões de chat indexadas
# e a base unificada — que entra AUTOMÁTICA nas buscas por linguagem).
COLECOES_SISTEMA = {"meta_colecoes", "midia_gerada", "prompts_midia",
                    "arquitetura_unificada", "sessoes_chat"}


BASE_UNIFICADA = "arquitetura_unificada"


def _check(name: str, url: str) -> dict:
    """Tenta acessar uma URL de saúde e retorna online/offline (exige HTTP 200)."""
    try:
        r = httpx.get(url, timeout=1.5)
        return {"name": name, "ok": r.status_code == 200, "detail": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"name": name, "ok": False, "detail": str(e)[:120]}


TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _jinja_strftime(ts, fmt="%d/%m %H:%M"):
    """Epoch → data legível (o conteúdo do cache mostra QUANDO foi guardado)."""
    try:
        from datetime import datetime
        return datetime.fromtimestamp(int(ts)).strftime(fmt)
    except Exception:
        return ""


TEMPLATES.env.filters["strftime"] = _jinja_strftime


TEMPLATES.env.filters["basename"] = lambda s: str(s).split("\\")[-1].split("/")[-1]


SESSAO_COOKIE = "rc_sessao"


def _versao_static(nome: str) -> str:
    try:
        p = Path(__file__).resolve().parent.parent / "static" / nome
        return _hl.md5(p.read_bytes()).hexdigest()[:8]
    except Exception:
        return "0"


TEMPLATES.env.globals["v_css"] = _versao_static("app.css")


TEMPLATES.env.globals["v_fav"] = _versao_static("favicon.svg")


TEMPLATES.env.globals["v_js"] = _versao_static("htmx.min.js")


TEMPLATES.env.globals["v_tw"] = _versao_static("vendor/tailwind.js")


def _card_codigo(corpo: str, lingua: str) -> str:
    """Bloco de código como CARD (o "quote" pedido): rótulo da linguagem +
    botão COPIAR (clique delegado em base.html — funciona em qualquer swap
    HTMX) + realce de sintaxe Pygments INLINE (sem CSS externo)."""
    import html as _h
    rotulo = lingua or "código"
    try:
        from pygments import highlight as _realce
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import TextLexer, get_lexer_by_name
        from pygments.util import ClassNotFound
        try:
            lexer = get_lexer_by_name(lingua or "text", stripall=False)
        except ClassNotFound:
            lexer = TextLexer()
        dentro = _realce(corpo, lexer,
                         HtmlFormatter(noclasses=True, nowrap=True))
    except Exception:
        dentro = _h.escape(corpo)
    cls = f"language-{lingua}" if lingua else ""
    return ('<figure class="cod"><figcaption><span class="cod-ling">'
            + _h.escape(rotulo)
            + '</span><span class="cod-acoes">'
            + '<button type="button" class="cod-btn" data-testar '
            + 'title="executar este código na sandbox (leva TODOS os códigos '
            + 'da conversa como contexto — python, rust, c#, java, node, go, '
            + 'ruby, php, dart)">&#9654; testar</button>'
            + '<button type="button" class="cod-btn" data-copiar>'
            + "&#128203; copiar</button></span></figcaption><pre><code"
            + (f' class="{cls}"' if cls else "") + ">" + dentro
            + "</code></pre></figure>")


def _md_basico(texto: str) -> str:
    """Markdown COMPLETO no servidor (lib `markdown`) SEM escape duplo e
    SEM buraco de XSS. Blocos de código viram CARD (figure) com copiar.

    v4 — fences que FUGIAM da regex e renderizavam como texto corrido:
    CRLF (stream), linguagem seguida de espaço (```python ␊) e
    abertura com 4+ backticks. Tudo normalizado antes de extrair."""
    import html as _h
    import re as _re
    if not texto:
        return ""

    # NORMALIZAÇÃO de fences (modelos 7B): CRLF -> LF; 4+ backticks -> 3;
    # indentado -> coluna 0; colado no texto ("Estrutura:```html") -> quebra
    # antes; último aberto -> fecha.
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = _re.sub(r"`{4,}", "```", texto)
    texto = _re.sub(r"(?m)^[ \t]{1,8}(```)", r"\1", texto)
    texto = _re.sub(r"(?m)^(?!\s*```)([^\n`]{1,200}?)(```[\w+\-#.]*)[ \t]*$",
                    r"\1\n\2", texto)
    if texto.count("```") % 2:
        texto += "\n```"

    # 1) extrai os blocos de código (conteúdo INTACTO) -> CARD de cada um
    blocos: list[str] = []

    def _guarda(m):
        blocos.append(_card_codigo(m.group(2), (m.group(1) or "").strip().lower()))
        return f"\x00BLOCO{len(blocos) - 1}\x00"

    texto = _re.sub(r"```([\w+\-#.]*)[ \t]*\n(.*?)```", _guarda,
                    texto, flags=re.S)

    # 2) o RESTO é texto seguro: escapa e deixa a lib montar markdown
    try:
        import markdown as _mk
        saida = _mk.markdown(_h.escape(texto, quote=False), extensions=[
            "tables", "sane_lists", "nl2br"])
    except ImportError:
        saida = _md_fallback(texto)

    # 3) devolve os cards (nos DOIS caminhos — o fallback recebe o texto
    #    com placeholders e NÃO os perdeu mais)
    for n, bloco in enumerate(blocos):
        saida = saida.replace(f"\x00BLOCO{n}\x00", bloco)
    return saida


def _md_fallback(texto: str) -> str:
    """Parser mínimo (usado só sem a lib markdown): recebe o texto JÁ com os
    blocos extraídos em placeholders \x00BLOCOn\x00 (substituídos pelo
    chamador) — inline, negrito, títulos e listas.

    ⚠️ SEGURANÇA: ESCAPA o HTML de entrada ANTES de tudo (os testes de XSS
    pegaram o fallback deixando <script> passar cru — qualquer ambiente sem
    a lib `markdown` virava buraco de XSS; os placeholders \x00 não são
    afetados pelo escape)."""
    import html as _h
    import re as _re
    p = _h.escape(texto, quote=False)
    p = _re.sub(r"`([^`\n]+)`", r"<code>\1</code>", p)
    p = _re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", p)
    p = _re.sub(r"(?m)^#{1,3}\s+(.+)$", r"<h3>\1</h3>", p)
    p = _re.sub(r"(?m)^\s*[-*]\s+(.+)$", r"<li>\1</li>", p)
    p = _re.sub(r"(?m)^\s*\d+[.)]\s+(.+)$", r"<li>\1</li>", p)
    p = _re.sub(r"(https?://[^\s<)]+)",
                r'<a href="\1" target="_blank" rel="noreferrer">\1</a>', p)
    return p.replace("\n", "<br>")


# markdown disponível AO TEMPLATE (itens do histórico multimídia renderizam
# a análise formatada — pedido do dono: "retorno das informações não estão
# formatadas para exibição na tela")
TEMPLATES.env.globals["_md_basico"] = _md_basico


def _paginas_ctx(request: Request, aba: str) -> dict:
    user = _usuario(request)
    return {"request": request, "aba": aba, "usuario": user,
            "admin": user == config.AUTH_ADMIN_USER}


def _sessao_id(request: Request, resposta=None, criar: bool = False) -> str | None:
    """Sessão do chat via cookie (a última conversa volta ao recarregar)."""
    sid = request.cookies.get(SESSAO_COOKIE)
    # criar = cria SE NAO EXISTIR cookie (nao substitui o valido!). O bug:
    # hx_chat passava criar=True e CADA mensagem virava sessao nova —
    # o historico anterior ficava orfao noutra sessao (o chat 'perdia'
    # a conversa ao enviar a mensagem seguinte).
    if not sid and resposta is not None:
        sid = str(uuid.uuid4())
        resposta.set_cookie(SESSAO_COOKIE, sid, max_age=30 * 86400,
                            httponly=True, samesite="lax")
    return sid


def _msgs_da_sessao(sid: str | None, owner: str) -> list[dict]:
    """Mensagens completas (com tokens/pensamentos) da sessão, para render."""
    if not sid:
        return []
    try:
        dados = sessions.get_session(sid) or {}
        bruto = dados.get("raw") or []
        saida = []
        for m in bruto:
            item = {"role": m.get("role", "user"),
                    "content": m.get("content", "")}
            for campo in ("tokens", "modelo", "docs", "pensamentos",
                          "pensamentos_sintetizados", "cache",
                          "segundos"):
                if m.get(campo):
                    item[campo] = m[campo]
            if m.get("role") != "user":
                item["html"] = m.get("html") or _md_basico(m.get("content", ""))
            saida.append(item)
        return saida
    except Exception:
        return []


class SandboxIn(BaseModel):
    """Teste de código na sandbox: TODO o contexto (todos os arquivos da
    conversa/da RESPOSTA) para cross-file compilar. `principal` vazio =
    o SERVIDOR escolhe o entry point (Program.cs > Main > top-level >
    site > primeiro executável) — pedido do dono: "testar a resposta
    completa"."""
    principal: str = ""
    arquivos: list[dict] = []
    timeout: int = 300


async def _proxy_app_api(porta: int, request: Request,
                         resto: str = "/", chave: str = "") -> Response:
    """Repassa o pedido ao app VIVO na sandbox (mesma rede do compose).

    Segue redirect? NÃO: o Location volta ao BROWSER (mesma chave na URL
    base — /sandbox/app/{chave}/login continua válido); redirects absolutos
    (/login, /static/x.css) que caem fora da chave são RESGATADOS pelo
    middleware 404-por-Referer."""
    from core import sandbox as _sb
    url = f"{_sb._base()}/app/{porta}{resto}"
    if request.url.query:
        url += "?" + request.url.query
    corpo = await request.body()
    try:
        r = httpx.request(request.method, url, content=corpo or None,
                          headers=({"Content-Type": request.headers["content-type"]}
                                   if corpo and request.headers.get("content-type")
                                   else {}),
                          timeout=30, follow_redirects=False)
        # no-store: o Cloudflare faz NEGATIVE caching (404 do app fica ~3 min
        # no edge — o app é TEMPORÁRIO, nada dele pode ser cacheado)
        # 🧭 404 do APP (navegação HTML): página amigável em vez do 404 cru
        # do Flask/Werkzeug (bug real do dono: rota inexistente no app
        # GERADO — aba/link morto no código do modelo — vazava o "Not
        # Found… check your spelling" sem contexto). JSON 404 passa reto
        # (apps de API seguem com a semântica deles).
        # ⚡ 404 na RAIZ: app gerado às vezes nasce SEM rota "/" (só
        # /api/...) — antes de mostrar a página morta, tenta o /docs
        # (Swagger automático do FastAPI): respondendo, o browser é
        # REDIRECIONADO para a documentação interativa do app.
        if r.status_code == 404 and resto in ("/", "") and chave:
            try:
                d = httpx.get(f"{_sb._base()}/app/{porta}/docs", timeout=5)
                if d.status_code == 200:
                    print(f"⚡ app :{porta} sem rota / — redirecionando ao "
                          "/docs (Swagger) do app")
                    return RedirectResponse(f"/sandbox/app/{chave}/docs",
                                            status_code=302)
            except Exception:
                pass
        if (r.status_code == 404
                and "text/html" in (r.headers.get("Content-Type") or "")):
            home = f"/sandbox/app/{chave}/" if chave else ".."
            corpo = ("<!doctype html><html lang=pt-BR><head><meta charset=utf-8>"
                     "<title>rota não existe neste app</title><style>"
                     "body{font-family:Segoe UI,sans-serif;background:#f6f7f9;"
                     "color:#1a1d21;display:grid;place-items:center;min-height:100vh;"
                     "margin:0}.c{max-width:32rem;margin:1rem;padding:2rem;background:#fff;"
                     "border:1px solid #e2e8f0;border-radius:14px;text-align:center}"
                     "a{display:inline-block;margin-top:1rem;padding:.55rem 1.2rem;"
                     "border-radius:10px;background:#2563eb;color:#fff;"
                     "text-decoration:none;font-weight:600}</style></head><body>"
                     "<div class=c><div style=font-size:2.4rem>🧭</div>"
                     "<h2>esta rota não existe no aplicativo</h2>"
                     "<p>O app de teste não tem a página que você abriu — "
                     "geralmente um <b>link/aba morto</b> no código gerado. "
                     "Volte à home do app ou peça no chat para corrigir a "
                     "rota.</p>"
                     f"<a href='{home}'>← home do aplicativo</a></div></body></html>")
            print(f"🧭 app :{porta} 404 em {resto[:80]} (rota ausente no app "
                  "gerado — página amigável devolvida)")
            return Response(content=corpo, status_code=404,
                            media_type="text/html",
                            headers={"Cache-Control": "no-store"})
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("Content-Type", "text/html"),
                        headers={"Cache-Control": "no-store"})
    except httpx.HTTPError:
        return _pag_fora(request, "app_caiu")


def _pag_fora(request: Request, caso: str) -> HTMLResponse:
    """Página AMIGÁVEL em vez de JSON/404 cru (bug real do dono: "deu erro
    404 em outra aba" sem explicação). Dois casos: link expirado/substituído
    e app fora do ar — ambos com o que fazer."""
    casos = {
        "expirou": ("⏳", "este link expirou",
                    "Os aplicativos de teste ficam hospedados por <b>~30 "
                    "minutos</b>. O tempo deste acabou — ou um teste novo do "
                    "mesmo projeto o substituiu.", 410),
        "app_caiu": ("🔌", "este app saiu do ar",
                     "O servidor do aplicativo parou de responder dentro da "
                     "hospedagem temporária — pode ter caído sozinho ou o "
                     "tempo acabou.", 502),
        "raiz": ("📦", "sandbox do RagAroy",
                 "Aqui aparecem os <b>aplicativos temporários</b> gerados "
                 "pelos testes de código — cada um tem um link próprio, "
                 "válido por ~30 minutos.", 200),
    }
    emo, titulo, detalhe, status = casos.get(caso, casos["app_caiu"])
    return TEMPLATES.TemplateResponse(
        request, "_sandbox_fora.html",
        {"titulo": titulo, "emo": emo, "detalhe": detalhe,
         "extras": "Abra a conversa no RagAroy e rode o <b>▶ testar "
                   "resposta</b> de novo para gerar um link novo."
         if caso != "raiz" else ""},
        status_code=status,
        headers={"Cache-Control": "no-store"})


# ═══ variante COM SLUG da sessão (pedido do dono 27/08: "incluir como slug
# o id da sessão na uri… também na geração do sandbox"): a URL nasce
# /sandbox/app/{sid}/{chave}/… — a chave continua sendo a autoridade; o
# slug identifica de QUAL conversa o app veio. Compat: formato antigo
# (sem slug) segue valendo. ═══
_RE_CHAVE_APP = __import__("re").compile(r"^\d+\.\d+\.[0-9a-f]+$")


def _job_ativo_ctx(sid: str) -> dict:
    """Contexto do JOB EM CURSO da sessão (para o _palco re-renderizar o
    polling após um refresh — pedido do dono: nada se perde). Job morto
    (concluído sem poll/registro evaporado) é LIMPO da sessão na hora."""
    try:
        ja = (sessions.get_session(sid) or {}).get("job_ativo")
    except Exception:
        return {}
    if not ja or not ja.get("job"):
        return {}
    try:
        if ja.get("kind") == "chat":
            s = _query.status(ja["job"], 0, "")
        else:
            s = None
    except Exception:
        s = None
    if not s or not s.get("running"):
        # terminou sem ninguém pollar (ou registro foi embora): limpa e segue
        try:
            an = sessions.get_session(sid) or {}
            sessions.save_session(an.get("raw") or [], sid=sid,
                                  owner=an.get("owner", ""),
                                  aprovacoes=an.get("aprovacoes", {}),
                                  raw=an.get("raw"), job_ativo=None)
        except Exception:
            pass
        return {}
    linhas = _linhas_visual(s.get("lines") or [])
    return {"job_ativo": {"kind": "chat", "job": ja["job"]},
            "job": ja["job"], "linhas": linhas, "running": True,
            "parcial": s.get("parcial") or "",
            "parcial_md": _md_basico(s.get("parcial") or "")}


def _palco_response(request: Request, sid: str | None, usuario: str):
    """Partial da conversa (swap no #palco, SEM reload) com o cookie já
    setado na resposta."""
    msgs = _msgs_da_sessao(sid, usuario)
    ctx = {"request": request, "mensagens": msgs, **_job_ativo_ctx(sid)}
    resp = TEMPLATES.TemplateResponse(request, "_palco.html", ctx)
    if sid:
        resp.set_cookie(SESSAO_COOKIE, sid, max_age=90 * 24 * 3600,
                        httponly=True, samesite="lax")
    return resp


def _campos_config() -> dict:
    """FIELDS + campos DINÂMICOS dos provedores externos (mesma lista na
    tela Sistema e no /hx/settings — sem isto o form enviava campos que o
    save ignorava)."""
    campos = dict(config.FIELDS)
    try:
        from core import provedores as _prov
        for _pid in _prov.ids():
            for _suf, _rot, _tp in (
                    ("BASE_URL", "URL da API (OpenAI-compatible)", "str"),
                    ("API_KEY", "Chave da API", "secret"),
                    ("MODELOS", "Modelos (lista manual, vírgula — reserva)",
                     "str")):
                campos.setdefault(
                    f"PROV_{_pid.upper()}_{_suf}",
                    (f"Provedor {_pid.upper()}", _rot, _tp))
    except Exception:
        pass
    return campos


# ⓘ dicas PRÁTICAS por campo (tooltip do Sistema — pedido do dono 28/08:
# "me fala na prática todos os campos e descreva como tooltip"): o que faz,
# quando mexer e exemplo. A chave nunca viu um dica aplicável antes.
_DICAS_CAMPO = {
    "LLM_BASE_URL": "Endereço do servidor de CONVERSA (llama-server). Só mexa se trocar porta/máquina — ex.: http://host.docker.internal:8090 no container ou https://llm.disroy.org pelo túnel.",
    "LLM_API_KEY": "Chave Bearer exigida pelos servidores llama-server (chat + embedding) iniciados com --api-key — protege os túneis públicos llm/embed.disroy.org. Mesma chave do ~/infra/.env da estação; /health continua público. Vazio = servidores sem --api-key.",
    "LLM_MODEL": "GGUF servido AGORA. Na prática troque pelo seletor do CHAT (troca a quente e grava aqui); editar à mão é só para consertar.",
    "EMBED_BASE_URL": "Endereço do embedding (bge-m3) — quem indexa e busca no Qdrant chama isto. Padrão: http://…:8081 (ligado sempre).",
    "EMBED_MODEL": "Nome do modelo de embedding. ⚠️ Trocar por um de dimensão diferente exige REINGESTAR todas as coleções.",
    "QDRANT_URL": "Onde o Qdrant (banco vetorial) responde. No container: http://qdrant:6333.",
    "SERPER_API_KEY": "Chave do serper.dev (Google) usada na pesquisa aprofundada (modo Auto/Pesquisa/Seed). Sem chave cai no DuckDuckGo automaticamente.",
    "LLM_PROVIDERS": "Ids EXTRA de provedores externos, vírgula (glm,deepseek…). Na prática quase não precisa: o cadastro ☁️ do Sistema (PROV_*_BASE_URL) já auto-descobre.",
    "HF_TOKEN": "Token do HuggingFace: datasets PRIVADOS da sua conta e rate-limit maior. Cole aqui e salve — aplica na hora.",
    "CHUNK_SIZE": "Tamanho do pedaço ao INGERIR documento (caracteres). 900–1200 funciona bem; menor = trechos mais precisos, mais pedaços.",
    "CHUNK_OVERLAP": "Sobreposição entre pedaços para não cortar ideia no meio. ~10% do CHUNK_SIZE.",
    "TOP_K": "Quantos fragmentos buscar por consulta. 4–8; subir aumenta contexto e custo de tokens.",
    "SCORE_MIN": "Similaridade mínima para o fragmento entrar (0–1). Subir = mais rígido: menos ruído, mas pode achar menos.",
    "SCORE_DIRETO": "Score em que o MELHOR fragmento responde sozinho, SEM consultar a LLM (economia total de tokens). 0.65 calibrado.",
    "SCORE_FRACO": "Abaixo disto o fragmento é FRACO e nem entra no prompt (híbrido responde só com o modelo). 0.55.",
    "TEMPERATURE": "Criatividade (0 = determinístico). 0.1–0.3 para fatos/código/matÉmtica; 0.5+ só para escrita criativa — alto ERRA contas.",
    "PROMPT_SYSTEM": "Instruções extras fixas em TODAS as respostas (tom, idioma, proibições). Ex.: 'Responda em português, direto, sem repetir a pergunta.'",
    "RERANKER": "1 = reordena os achados com cross-encoder local (precisão melhor, +~2 s por busca). 0 = desliga.",
    "RERANK_MODEL": "Modelo do reranker no HuggingFace. base = leve (1,1 GB); v2-m3 = melhor em PT (2,3 GB) — compare no bench antes de trocar.",
    "TRADUTOR": "1 = trechos EN do digest rag saem em PT (opus-mt via ctranslate2 int8 na CPU — rápido; torch puro era minutos). 0 = desliga (fica no idioma original).",
    "TRADUTOR_MODEL": "Modelo do tradutor (HuggingFace, Marian EN→PT — convertido p/ int8 no 1º uso). Padrão opus-mt-tc-big-en-pt (~450 MB); só troque por outro Marian EN→PT.",
    "CONSOLIDA": "1 = antes de incluir um pedaço, busca semelhante na MESMA coleção: ≥ CONSOLIDA_SCORE funde/complementa o ponto existente; novo ganha id determinístico (reingestão sobrepõe, não empilha). 0 = comportamento antigo (append puro).",
    "CONSOLIDA_SCORE": "Similaridade (0–1) em que o pedaço novo conta como a MESMA informação de um ponto existente → consolida. Padrão 0.92 (quase-duplicado).",
}


_RE_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# barras de progresso do sd.cpp (todas as formas: |##| n/n · |==> n/n s/it
# · n/n - xMB/s) — o % vive na barra REAL do card, não no log
_RE_BARRA = re.compile(
    r"^\s*\|[#=>\s.]*\|?\s*\d+\s*/\s*\d+"          # |####| 138/138 / |==> 8/20
    r"|^\s*\d+\s*/\s*\d+\s*-\s*[\d.]+\s*[KM]B/s"   # 744/780 - 778.14MB/s
    r"|^\s*\|.*\d+\s*/\s*\d+.*s/it"                # |====> 8/20 - 13.33s/it
    r"|s/it\s*$"                                   # 12/20 - 13.40s/it (s/it no fim)
)


_RE_PCT = re.compile(r"^\s*\d+/\d+|\s+\d+(\.\d+)?(MB|GB|ms|s)/s\s*$", re.I)


def _linhas_visual(lines: list) -> list:
    """Log LIMPO para o card: tira códigos ANSI, descarta linhas de BARRA de
    progresso (o % vive na barra do card), restos de carriage-return do
    sd.cpp, loader técnico e ruído vazio — só o que importa ao operador."""
    saida = []
    for l in lines:
        msg = str(l.get("msg", l) if isinstance(l, dict) else l)
        msg = _RE_ANSI.sub("", msg).replace("\r", "\n")
        # sd.cpp pinta barra por cima: sobra lixo após o \r — fica a última
        for parte in msg.split("\n"):
            parte = parte.strip()
            if not parte or _RE_BARRA.match(parte):
                continue
            # loader técnico do sd.cpp: mantém só o resumo "completed, taking"
            if "model_loader.cpp" in parte and "completed" not in parte:
                continue
            if parte in ("[INFO ]", "[INFO]", "[DEBUG]", "save:", "compute"):
                continue
            saida.append({"msg": parte,
                          "etapa": (l.get("etapa") if isinstance(l, dict) else None)})
    return saida


def _scroll_todos(client, colecao: str, limite: int, filtro=None):
    """Scroll paginado da coleção (gerador de lotes de Record).

    `filtro` (opcional): Filter do qdrant-client — o modal da Biblioteca
    usa para trazer TODOS os chunks de um documento (arquivo|source).
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    offset = None
    while limite > 0:
        lote, offset = client.scroll(collection_name=colecao,
                                     limit=min(100, limite),
                                     offset=offset, with_payload=True,
                                     with_vectors=False,
                                     scroll_filter=filtro)
        yield lote
        limite -= len(lote)
        if offset is None or not lote:
            break


def trocos_label(n: int) -> str:
    return f"{n} campo(s) foram"


def _jobs_ativos() -> dict[str, int]:
    """Jobs de fundo em andamento, por tipo ({ingestão: 2, seed: 1, …}).
    Trocar modelo/embedding no meio derruba a LLM que o job está usando —
    chat em curso também conta (usa a mesma LLM)."""
    ativos: dict[str, int] = {}
    for reg in TODOS_JOBS:  # uma lista única — novo tipo de job entra sozinho
        n = reg.ativos()
        if n:
            ativos[reg.rotulo] = n
    return ativos


# cache do scan de coleções (~30 s): /api/status roda a cada 15 s na webui e
# o scan é N+1 no Qdrant (1 get_collection por coleção) — sem cache, cada
# consulta paga o preço cheio
_SCAN_CACHE: dict = {"t": 0.0, "data": {}}


_SCAN_CACHE_TTL = 30.0


def _scan_invalidar():
    """Zera o cache do scan de coleções — chamado após APAGAR coleção.

    Sem isso a grade da Biblioteca 'fantasiava' a coleção excluída por até
    30 s ao recarregar a página (a exclusão no Qdrant já tinha terminado,
    mas o cache servia a lista de antes — parecia exclusão inacabada)."""
    _SCAN_CACHE.update(t=0.0, data={})


def _scan_collections(client, incluir_sistema: bool = False, forcar: bool = False) -> dict:
    """{nome: {points, dim}} lendo a configuração de cada coleção do Qdrant.

    Por padrão esconde as coleções de sistema (só a webui lista — internamente
    quem precisa consulta direto pelo nome). Usa cache de 30 s (o scan é
    N+1: uma chamada get_collection por coleção)."""
    agora = time.time()
    if not forcar and not incluir_sistema and agora - _SCAN_CACHE["t"] < _SCAN_CACHE_TTL:
        return _SCAN_CACHE["data"]
    info = {}
    for c in client.get_collections().collections:
        if not incluir_sistema and c.name in COLECOES_SISTEMA:
            continue
        try:
            col = client.get_collection(c.name)
            vec = col.config.params.vectors
            dim = next(iter(vec.values())).size if isinstance(vec, dict) else vec.size
            info[c.name] = {"points": col.points_count, "dim": dim}
        except Exception:
            info[c.name] = {"points": None, "dim": None}
    # SÓ a variante SEM sistema escreve no cache: o scan com
    # incluir_sistema=True (webui) não pode poluí-lo — senão
    # /api/collections e o seletor do chat servem meta_colecoes/
    # sessoes_chat como coleções comuns por até 30 s
    if not incluir_sistema:
        _SCAN_CACHE.update(t=agora, data=info)
    return info


_ATIVOS_CACHE = {"t": 0.0, "dados": None}


def modelos_ativos() -> dict:
    """FONTE ÚNICA (SOLID) do que está NO AR AGORA — lida dos SERVIDORES
    (nunca do .env, que envelhece após trocas na estação): chat :8090 e
    embedding :8081. Serve o topbar (badge 🧠), a página Sistema e o
    dashboard — um conceito, um lugar.
    CACHE 10 s (o badge consulta a cada troca de tipo; a 1ª chamada
    cruzava o túnel até o agente e a UI ficava "…" pendurado)."""
    agora = time.time()
    if _ATIVOS_CACHE["dados"] is not None and agora - _ATIVOS_CACHE["t"] < 10:
        return _ATIVOS_CACHE["dados"]
    ativos = {"chat": None, "embed": None, "vram_mi": None}
    try:
        ativos["chat"] = modelos.servido(modelos.CHAT_PORTA)
    except Exception:
        pass
    try:
        ativos["embed"] = bool(modelos.embedding_no_ar())
    except Exception:
        pass
    try:
        if config.EM_CONTAINER:
            s = modelos._chamar_agente("/saude", timeout=3)
            ativos["vram_mi"] = s.get("vram_mi")
        else:
            ativos["vram_mi"] = modelos._vram_uso_mi()
    except Exception:
        pass
    _ATIVOS_CACHE.update(t=agora, dados=ativos)
    return ativos


_STATUS_CACHE: dict = {"t": 0.0, "dados": None}


UPLOAD_MAX = 30 * 1024 * 1024


_EXTS_UPLOAD = {".txt", ".md", ".mdx", ".rst", ".pdf",
                ".cs", ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".go",
                ".rs", ".java", ".rb", ".kt", ".swift", ".php", ".c", ".cpp",
                ".h", ".hpp", ".sh", ".ps1", ".vue", ".svelte", ".sql",
                ".csproj", ".json", ".yaml", ".yml", ".toml"}


_manutencao = JobRegistry("man", "manutenção")


class ManutencaoIn(BaseModel):
    acao: str  # "analisar" | "agrupar" | "dividir"
    colecao: str | None = None
    apagar_original: bool = False


def _manutencao_disparar(acao: str, colecao: str | None = None,
                         apagar_original: bool = False) -> dict:
    if acao not in ("analisar", "agrupar", "dividir"):
        raise HTTPException(status_code=400, detail=f"ação '{acao}' inválida")
    if acao == "dividir" and not colecao:
        raise HTTPException(status_code=400, detail="dividir exige uma coleção")
    job = _manutencao.novo_id()

    def fabricar(p: dict):
        jid = p["job"]

        def rodar():
            contadores.set_servico("manutencao")
            _manutencao.iniciar(jid)
            try:
                if acao == "analisar":
                    _manutencao.log(jid, "🤖 A LLM está lendo amostras de cada coleção…")
                    _manutencao.concluir(jid, result={"resultados": analyze_all()})
                elif acao == "agrupar":
                    _manutencao.log(jid, "🗂️ A LLM está agrupando as coleções por objetivo…")
                    client = QdrantClient(url=config.QDRANT_URL, timeout=60,
                                          check_compatibility=False)
                    _manutencao.concluir(jid, result=catalog.agrupar(client))
                else:
                    _manutencao.log(jid, f"📦 Dividindo '{colecao}' por tema "
                                         "(uma chamada de LLM por arquivo)…")
                    _manutencao.concluir(jid, result=enrich_collection(
                        colecao, apagar_original))
            except Exception as e:
                print(f"❌ Erro na manutenção ({acao}): {e}")
                _manutencao.concluir(jid, error=str(e)[:300])
        return rodar

    _despachar(fabricar, "manutencao", {"job": job}, _manutencao)
    return {"job": job, "acao": acao, "status": f"/api/manutencao/status/{job}"}


_MASCARA = "••••••••"  # valor devolvido p/ segredos (PUT ignora quem mandar de volta)


_INGEST_ETAPAS = (  # emoji inicial da linha -> etapa do wizard
    ("📂", "ler"), ("📄", "ler"), ("🏷️", "categorizar"), ("✂️", "dividir"),
    ("🧮", "embedding"), ("🆕", "colecao"), ("♻️", "colecao"), ("⬆️", "indexar"),
    ("🗂️", "catalogo"), ("✅", "fim"),
)


_ingest = JobRegistry("ing", "ingestão")


def _ingest_log(job: str, msg: str):
    """Callback de log da ingestão: guarda a linha + a etapa correspondente."""
    etapa = next((nome for emoji, nome in _INGEST_ETAPAS
                  if msg.lstrip().startswith(emoji)), None)
    _ingest.log(job, msg, etapa=etapa)


class HfIn(BaseModel):
    query: str
    colecao: str | None = None
    limite: int = 12


_preview = JobRegistry("prev", "pré-visualização")


class PreviewIn(BaseModel):
    fonte: str = "pasta"        # "pasta" (caminho no servidor) | "hf"
    pasta: str = ""
    query: str = ""             # hf: o que buscar no Hub
    limite: int = 8             # hf: máx. de datasets
    ids: list[str] | None = None  # hf: datasets MARCADOS na UI (seleção explícita)
    colecao: str | None = None  # alvo do gate de tema (opcional)


class PreviewAplicarIn(BaseModel):
    preview: str
    ids: list[int]
    colecao: str


def _preview_disparar(docs_fn, colecao_alvo: str | None) -> str:
    """Job de dry-run: docs_fn(log) devolve os Documents; o resultado traz o
    `preview` (pid) para a webui abrir o painel de revisão."""
    from core import preview as _pv
    job = _preview.novo_id()

    def fabricar(p: dict):
        jid = p["job"]

        def rodar():
            contadores.set_servico("ingestao")
            _preview.iniciar(jid)
            try:
                docs = docs_fn(lambda m, g='': _preview.log(jid, m, grupo=g or 'geral'))
                preparados, resp = _pv.analisar(
                    docs, colecao_alvo, log=lambda m, g='': _preview.log(jid, m, grupo=g or 'geral'))
                pid = uuid.uuid4().hex[:10]
                _pv.guardar(pid, preparados, resp)
                _preview.concluir(jid, result={"preview": pid, **resp["resumo"]})
            except Exception as e:
                print(f"❌ Erro na pré-visualização: {e}")
                _preview.concluir(jid, error=str(e)[:300])
        return rodar

    _despachar(fabricar, "preview", {"job": job}, _preview)
    return job


class WebSalvarIn(BaseModel):
    """Ensinar a base com as FONTES de uma resposta do chat (pedido do
    dono: 'o que precisa para o qdrant ficar inteligente' — o conhecimento
    que a 🌐 pesquisa-web trouxe ficava só NA CONVERSA e se perdia)."""
    colecao: str
    documentos: list[dict] = []   # [{titulo, url, content}]


_pesquisa = JobRegistry("pesq", "pesquisa profunda")


class PesquisaIn(BaseModel):
    assunto: str
    colecao: str | None = None   # alvo do gate de tema na revisão
    fontes: int = 6              # máx. de fontes baixadas


class SnapshotRestaurarIn(BaseModel):
    arquivo: str
    colecao: str | None = None  # padrão: a do snapshot


_higieniza = JobRegistry("hig", "higienização")


_limpeza = JobRegistry("lim", "limpeza")


# sandbox como JOB (imune ao 524 da borda): registro + rota de status
_sbx = JobRegistry("sbx", "sandbox")


_LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"


_LOGS_FONTES = {
    "chat": lambda: _mais_recente("llama-chat-*.log"),
    "embed": lambda: (_LOGS_DIR / "llama-embed.log"),
    "api": lambda: (_LOGS_DIR / "api-8000.log"),
}


LOG_TAIL_LINHAS = 120


def _mais_recente(padrao: str) -> Path:
    candidatos = sorted(_LOGS_DIR.glob(padrao), key=lambda p: p.stat().st_mtime)
    return candidatos[-1] if candidatos else None


def _sanear_caminho(nome: str) -> str:
    """Normaliza o nome PRESERVANDO a estrutura de pastas do retorno
    ('src/domain/News.cs' continua src/domain/News.cs no zip) — mas sem
    traversal (remove .., drive, absolutos) e sem separadores repetidos."""
    partes = [p for p in re.split(r"[\\/]+", str(nome))
              if p not in ("", ".", "..") and ":" not in p]
    caminho = "/".join(partes)
    return (caminho[:120] or "arquivo.txt")


class ZipIn(BaseModel):
    arquivos: list[dict]  # [{nome, conteudo}] — saiu da própria resposta do chat


_EXTS_ANEXO = {".txt", ".md", ".mdx", ".rst", ".pdf"}


ANEXO_MAX_CHARS = 12000  # contexto por anexo (cabe no histórico do chat)


def _extrair_anexo(caminho: str) -> str:
    """Lê pdf/txt/md de um arquivo temporário (threadpool)."""
    if caminho.lower().endswith(".pdf"):
        from langchain_community.document_loaders import PyPDFLoader
        return "\n".join(p.page_content for p in PyPDFLoader(caminho).load())
    return Path(caminho).read_text(encoding="utf-8", errors="replace")


def _erro_modelo(modelo_pedido: str) -> HTTPException:
    """409 informando o modelo ATUAL, pesquisado na API na hora."""
    atual = modelos.servido(modelos.CHAT_PORTA)
    detalhe = (f"modelo divergente: a sessão pediu '{modelo_pedido}', mas o modelo "
               f"atual na :{modelos.CHAT_PORTA} é "
               f"'{atual or 'nenhum (chat pausado)'}'")
    return HTTPException(status_code=409, detail=detalhe)



_seed = JobRegistry("seed", "seed")

# FIM de job que MEXE em coleções ⇒ cache do scan cai na hora (criação de
# coleção aparecia só 30 s depois; o mesmo fantasma da exclusão, ao
# contrário). Registries de leitura (query/pesquisa/sandbox/mcp) ficam de
# fora — invalidar a cada resposta do chat seria desperdício.
for _reg in (_manutencao, _ingest, _higieniza, _limpeza, _seed):
    _reg.ao_concluir(lambda jid: _scan_invalidar())


_varredura = JobRegistry("var", "varredura")


def _bases_consultadas(client, colecoes) -> str | None:
    """Cabeçalho do contexto: o que cada coleção selecionada é (área · tema:
    descrição), lido do catálogo — é o que faz a LLM compreender o domínio
    das RAGs selecionadas antes de ler os fragmentos."""
    try:
        meta = catalog.list_meta(client)
    except Exception:
        return None
    linhas = []
    for nome in colecoes:
        m = meta.get(nome)
        if not m:
            continue
        rotulo = " · ".join(x for x in (m.get("area"), m.get("categoria")) if x)
        linha = f"- {nome}" + (f" ({rotulo})" if rotulo else "")
        if m.get("descricao"):
            linha += f": {m['descricao']}"
        linhas.append(linha)
    if not linhas:
        return None
    return ("Bases consultadas nesta conversa (o que cada uma contém):\n"
            + "\n".join(linhas))


_query = JobRegistry("qry", "chat")


# ── exclusão de conversa como JOB (fila Rabbit): a lista nunca trava e a
#    UX mostra "⏳ apagando…" até o job concluir (pedido do dono) ──
_conv = JobRegistry("conv", "exclusão de conversa")


# sids com exclusão EM CURSO: {sid: {job, owner}} — alimenta o estado da
# lista (item desabilitado + polling) e a idempotência do clique duplo
_APAGANDO: dict[str, dict] = {}


def _apagando_do_usuario(owner: str) -> set[str]:
    """Sids em exclusão em curso pertencentes ao usuário (estado da lista)."""
    return {s for s, v in _APAGANDO.items() if v.get("owner") == owner}


def _query_log(job: str, msg: str, grupo: str = "geral"):
    """Linha de execução do chat (o 'pensando…' da webui mostra em tempo real)."""
    _query.log(job, msg, grupo=grupo, ts=time.strftime("%H:%M:%S"))


class ProvedorIn(BaseModel):
    """Cadastro de provedor cloud PELA UI (pedido do dono: 'preciso ter um
    cadastro de provedores cloud') — grava PROV_<ID>_* no .env na hora."""
    id: str
    base_url: str
    nome: str = ""
    api_key: str = ""
    modelos: str = ""   # opcional: lista manual separada por vírgula


_RE_TEMPO = __import__("re").compile(
    r"(que\s+dia\s+(?:é|e|eh)\s+hoje|qual\s+(?:é\s+|e\s+)?(?:a\s+)?data"
    r"(?:\s+de)?\s+hoje|dia\s+de\s+hoje|que\s+horas?\s+s(?:ã|a)o|"
    r"hora\s+(?:agora|atual)|data\s+atual|hoje\s+(?:é|e|eh)\s+que\s+dia|"
    r"em\s+que\s+(?:dia|data)\s+(?:estamos|estamos\s+hoje)|"
    r"que\s+dia\s+(?:estamos|é\s+hoje))",
    __import__("re").IGNORECASE)


def _e_pergunta_tempo(pergunta: str) -> bool:
    """Pergunta CLARAMENTE sobre data/hora AGORA (curta — pergunta longa
    tem outro assunto junto e não deve ser interceptada)."""
    p = (pergunta or "").strip().lower()
    return len(p) <= 120 and bool(_RE_TEMPO.search(p))


def _resposta_relogio() -> dict:
    """Resposta de data/hora pelo RELÓGIO DO SERVIDOR (fonte da verdade —
    zero LLM, zero busca, zero alucinação de '29 de outubro de 2023')."""
    from datetime import datetime
    _DS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
           "sexta-feira", "sábado", "domingo")
    _MS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho",
           "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")
    a = datetime.now()
    extenso = f"{_DS[a.weekday()]}, {a.day} de {_MS[a.month - 1]} de {a.year}"
    texto = (f"Hoje é **{extenso}** — {a.strftime('%d/%m/%Y')}." + "\n\n"
             + f"🕐 Agora são **{a.strftime('%H:%M')}** no relógio do servidor "
             "RagAroy.")
    return {"answer": texto, "docs": [], "mode": "relogio", "model": None,
            "tokens": {"entrada": 0, "saida": 0, "chamadas": 0, "total": 0},
            "cache": None}


_RE_PEDE_WEB = __import__("re").compile(
    r"(pesquis\w*|busqu\w*|busca(?:r)?|procure|procurar|consult\w*|"
    r"olh\w*|ach\w*|encontr\w*)[^.!?]{0,48}"
    r"(internet|web\b|online|google|duckduckgo|na rede)"
    r"|(internet|web\b|online|google)[^.!?]{0,48}"
    r"(pesquis\w*|busqu\w*|busca(?:r)?|procure|procurar|consult\w*)",
    __import__("re").IGNORECASE)


def _pede_web(pergunta: str) -> bool:
    """Pedido EXPLÍCITO de busca na internet NA PRÓPRIA mensagem (pedido do
    dono 28/08: "pode pesquisar na internet" — o modelo respondia "não
    consigo pesquisar" porque a busca dependia do MCP marcado)."""
    return bool(_RE_PEDE_WEB.search(pergunta or ""))


def _processar_query(body: QueryIn, log=None, on_token=None):
    """Processa uma consulta (compartilhada entre a rota síncrona e o job).
    `log(msg, grupo)` recebe as etapas — cache, busca, geração, tokens."""
    log = log or (lambda m, g="geral": None)
    contadores.set_servico("chat")
    contadores.balanco_reset()  # tokens DESTA resposta: balanço local (sem
    # cruzar com totais globais de outros processos — fim da divergência)
    # 🌐 PROVEDOR EXTERNO ("glm:glm-4.6" no model): override desta EXECUÇÃO
    # — a LLM sai do llama-server e vai para o endpoint configurado no .env.
    # A limpeza (set_override(None)) é feita nos CHAMADORES (finally) porque
    # o worker do Rabbit REUSA a thread entre jobs.
    if ":" in str(body.model or ""):
        _pid, _nome = str(body.model).split(":", 1)
        from core import provedores as _prov
        _pv = _prov.resolver(_pid.strip(), _nome.strip())
        if not _pv:
            raise HTTPException(
                status_code=400,
                detail=f"provedor '{_pid}' não configurado no .env — "
                       "defina PROV_%s_BASE_URL/API_KEY" % _pid.upper())
        rag.set_override(_pv)
        log(f"🌐 provedor externo [{_pv['provedor']}] {_pv['model']} — "
            "a resposta vem da API configurada (GPU local intocada)", "modelo")
    else:
        rag.set_override(None)
    # 🧪 MOCK_LLM (F1b-5): ANTES de tudo — sem cache, sem Qdrant, sem LLM,
    # sem os guards de sessão/estúdio (o objetivo é validar a UI com a
    # máquina toda desligada; o job em si roda de verdade, com log ao vivo)
    if getattr(config, "MOCK_LLM", False):
        from core import mock as _mock
        return _mock.responder(body, log)
    # 📅 PERGUNTA DE DATA/HORA → RELÓGIO DO SERVIDOR (pedido do dono 28/08).
    # A fonte da verdade é ESTA máquina; busca web (DuckDuckGo/Serper) já
    # existe para perguntas de EVENTOS (modo web/Auto/Pesquisa).
    if _e_pergunta_tempo(str(body.question or "")):
        _rel = _resposta_relogio()
        log("📅 pergunta de data/hora — respondida pelo RELÓGIO do servidor "
            "(LLM não consultada: a data do treinamento do modelo mente)",
            "resposta")
        return _rel
    # 🧠 CICLO FRIO DA ESTAÇÃO (pedido do dono 10/09): o container do chat é
    # derrubado após 5 min ocioso (economia de GPU) e religado AQUI — antes
    # de cache/Qdrant/roteador, para a espera de carga (~90 s) aparecer no
    # log DE CARA, não depois das etapas de busca. Provedor externo (override
    # setado acima) não toca a GPU da estação. Falha aqui = estação
    # inalcançável: o job morre com o motivo claro em vez de erro de conexão
    # críptico lá na geração.
    # ⚡ MODO RAG PURO (pedido do dono 11/09: "só deve ligar a gpu se for
    # usar a gpu, quando seleciono só a base, não precisa consultar a llm"):
    # nada neste fluxo acorda o container do chat — a resposta é o digest
    # dos fragmentos (embedding + Qdrant + rerank apenas).
    if rag.usa_llm_local() and body.mode != "rag":
        modelos.garantir_llm(log=log)
    # 🌐 WEB POR INTENÇÃO: o pedido de busca na MENSAGEM ativa o mesmo
    # motor do MCP "pesquisa-web" (DuckDuckGo → Serper, páginas inteiras
    # como fragmentos [n]) — sem depender de marcar nada no composer.
    if MCP_WEB not in (body.mcps or []) and _pede_web(str(body.question or "")):
        body.mcps = list(body.mcps or []) + [MCP_WEB]
        log("🌐 pedido de PESQUISA NA WEB detectado na mensagem — busca "
            "ativada (DuckDuckGo → Serper)", "mcp")
    # escopo efetivo da consulta (TRI-ESTADO explícito — regra do dono):
    #   collections=[] (webui sem nada marcado) → SEM coleções: NÃO busca
    #   collections=None (CLI/API antiga)        → TODAS as visíveis
    #   collection="x" (compat)                  → uma
    # A regra vive NO BACKEND; a webui só mostra o estado.
    log(f"mensagem recebida (modo {body.mode})", "mensagem")
    if body.collections is not None and body.collections:
        colecoes = list(body.collections)
    elif body.collections == [] and not body.collection:
        colecoes = []  # seleção VAZIA explícita: sem busca na base
    elif body.collection:
        colecoes = [body.collection]
    else:
        try:
            client0 = QdrantClient(url=config.QDRANT_URL, timeout=10,
                                   check_compatibility=False)
            colecoes = list(_scan_collections(client0))
        except Exception:
            colecoes = [config.COLLECTION]
    log("escopo: " + (", ".join(colecoes) if colecoes
                      else "SEM coleções — sem busca na base (seleção vazia)"),
        "mensagem")
    # 👋 SAUDAÇÃO/PERGUNTA TRIVIAL (sem conteúdo recuperável): buscar contexto
    # para "oi tudo bem?" é desperdício puro (3k tokens e fragmentos
    # aleatórios anexados). Responde direto, com o porquê no log.
    # Detecção por TOKENS: mensagem curta cujas TODAS as palavras são de
    # saudação/identidade ("oi tudo bem?", "quem é você", "obrigado").
    _TRIVIAIS = {
        "oi", "olá", "ola", "opa", "eai", "e", "aí", "ai", "hey", "hi",
        "hello", "bom", "boa", "dia", "tarde", "noite", "tudo", "bem",
        "bom", "como", "vai", "voce", "você", "é", "e", "um", "uma",
        "robo", "robô", "ia", "quem", "o", "que", "faz", "qual", "seu",
        "nome", "obrigado", "obrigada", "valeu", "vlw", "thanks", "thank",
        "you", "beleza", "com", "está", "esta", "tchau", "adeus",
    }
    _palavras = re.findall(r"[a-zà-ú]+", (body.question or "").lower())
    # 🧭 LANGGRAPH — A INTELIGÊNCIA VEM ANTES (pedido do dono): o grafo
    # roteia a pergunta ANTES de cache/Qdrant/rerank — pedido de CRIAÇÃO
    # em modo rag é orientado na hora (antes: pagava ~7 s de busca para
    # no fim recusar), saudação responde direto. "fluxo" não toca em nada.
    # ⚡ RAG PURO pula o roteador (é LLM — e a escalada automática para
    # híbrido também acordaria a GPU): criação em modo rag recebe a recusa
    # ORIENTADA do fim do fluxo, como sempre recebeu
    if body.mode == "rag":
        _rota = {"rota": "fluxo", "tipo": "",
                 "motivo": "modo rag (LLM não consultada)"}
        log("🧭 roteador PULADO (modo rag — só a base, LLM de conversa "
            "não consultada)", "mensagem")
    elif not colecoes:
        # ⚡ SEM coleções = SEM roteador (pedido do dono 28/08: com provedor
        # externo a classificação pagava ~4 s de ida-e-volta à API antes da
        # resposta; sem base nada a rotear — a saudação trivial segue pelo
        # heurístico sem LLM logo abaixo).
        _rota = {"rota": "fluxo", "tipo": "", "motivo": "sem coleções"}
        log("🧭 roteador PULADO (sem coleções) — direto ao modelo", "mensagem")
    else:
        try:
            _rota = grafo.rotear(body.question, body.mode, log=log,
                                 historia=body.history)
        except Exception as _e:
            _rota = {"rota": "fluxo", "tipo": "",
                     "motivo": f"erro: {str(_e)[:40]}"}
    if _rota["rota"] == "criar_como_hibrido":
        # 🧭 ESCALADA AUTOMÁTICA (pedido do dono: "como ele não sabe o que
        # estou falando?"): criação é impossível no rag (só o que está na
        # base) — em vez de recusar com um texto genérico, ESTA pergunta
        # sobe para o híbrido sozinha: a base orienta o estilo e o modelo
        # ESCREVE o que foi pedido. O modo escolhido segue salvo para as
        # próximas (perguntas factuais continuam no rag).
        log("🧭 pedido de CRIAÇÃO no modo rag — respondendo no modo "
            "HÍBRIDO automaticamente (a base orienta o estilo)", "mensagem")
        body.mode = "hibrido"
    if _rota["rota"] == "conversa" and body.mode != "livre":
        log("👋 roteador: saudação — resposta direta, SEM busca", "busca")
        contadores.set_etapa("resposta (roteador)")
        answer = rag.answer_free(body.question, body.history, on_token=on_token)
        contadores.set_etapa(None)
        return {"question": body.question, "mode": body.mode,
                "collections": colecoes, "docs": [], "answer": answer,
                "erros": {}, "ferramentas": [], "mcp_erros": {},
                "pendente": None, "aprovacoes_sessao": body.aprovacoes_sessao or {},
                "pergunta_busca": "", "bussola": None,
                "model": modelos.servido(modelos.CHAT_PORTA) or config.LLM_MODEL,
                "provider": body.provider or "llama-server",
                "tokens": contadores.balanco_ler(), "busca": None}
    # MCP_WEB não conta como "ferramenta MCP" para a trivialidade: saudação
    # com busca marcada continua saudação (não se pesquisa "oi" na web)
    _mcps_reais = [m for m in (body.mcps or []) if m != MCP_WEB]
    eh_trivial = (body.mode == "hibrido" and not body.history and not _mcps_reais
                  and not body.estado_agente and 0 < len(_palavras) <= 6
                  and all(w in _TRIVIAIS for w in _palavras))
    if eh_trivial:
        log("👋 saudação/mensagem trivial — SEM busca na base (economia de "
            "contexto: nada recuperável numa saudação)", "busca")
        contadores.set_etapa("resposta (híbrido, sem busca)")
        answer = rag.answer_free(body.question, body.history, on_token=on_token)
        contadores.set_etapa(None)
        return {"question": body.question, "mode": body.mode,
                "collections": colecoes, "docs": [], "answer": answer,
                "erros": {}, "ferramentas": [], "mcp_erros": {},
                "pendente": None, "aprovacoes_sessao": body.aprovacoes_sessao or {},
                "pergunta_busca": "", "bussola": None,
                "model": modelos.servido(modelos.CHAT_PORTA) or config.LLM_MODEL,
                "provider": body.provider or "llama-server",
                "tokens": contadores.balanco_ler()}
    # (cache semântico Redis REMOVIDO por decisão do dono 27/08 — a 🧭
    # bússola (Qdrant, coleção sessoes_chat) continua cobrindo perguntas
    # repetidas cross-sessão com escopo por owner)
    _motivos_bussola = []
    if body.mode not in ("rag", "livre", "hibrido"):
        _motivos_bussola.append(f"modo {body.mode}")
    if body.mcps:
        _motivos_bussola.append("ferramentas MCP")
    if body.aprovacao:
        _motivos_bussola.append("aprovação pendente")
    if body.estado_agente:
        _motivos_bussola.append("estado do agente")
    cacheavel = not _motivos_bussola
    # DONO da sessão (guardrail de escopo da bússola — por usuário).
    try:
        owner = (sessions.get_session(body.sessao) or {}).get("owner", "") \
            if body.sessao else ""
    except Exception:
        owner = ""
    owner = owner or getattr(config, "AUTH_ADMIN_USER", "") or ""
    # 🧭 F3 — BÚSSOLA PRÉ-TOKEN: "já respondi isso numa sessão passada?"
    # embedding contra a coleção de sistema sessoes_chat (escopo por owner).
    # GUARDRAIL (pedido do dono): a bússola NUNCA responde sozinha com o
    # assunto de outra sessão — outro assunto não pode DIRIGIR a conversa.
    # Ela apenas SUGERE ("isto lembra a conversa X") e a resposta é gerada
    # normal; o cruzamento de sessões fica VISÍVEL, nunca automático.
    bussola_sugestao = None
    if cacheavel and not getattr(config, "MOCK_LLM", False):
        b = bussola.consultar(body.question, owner, log=log)
        if b and b["similaridade"] >= bussola.SUGESTAO:
            log(f"🧭 bússola: pergunta parecida com a conversa "
                f"“{b['titulo'][:50]}” ({b['similaridade']:.2f}) — "
                f"SUGESTÃO anexada (a resposta é gerada normal)", "cache")
            bussola_sugestao = {"similaridade": b["similaridade"],
                                "sessao": b["sessao"], "titulo": b["titulo"]}
    # modelo solicitado ≠ modelo no ar → troca antes de responder. A
    # comparação é NORMALIZADA (alias↔stem, minúsculo): o servidor pode
    # reportar o nome do arquivo enquanto a UI manda o alias — sem
    # normalizar, o MESMO modelo era recarregado a cada mensagem.
    _servido_agora = modelos.servido(modelos.CHAT_PORTA)
    # 🌐 EXTERNO ("prov:modelo") NÃO troca nada local — o override desta
    # execução já aponta a LLM para o endpoint externo (o valor com ":"
    # nunca é alias do REGISTRO; sem isto a estação ficava "carregando"
    # um modelo que não existe)
    if body.mode == "rag":
        pass  # rag puro: nenhum modelo é consultado — nada de troca/ativação
    elif body.model and ":" in str(body.model):
        pass
    elif body.model and modelos.normalizar(body.model) != modelos.normalizar(_servido_agora):
        log(f"🔁 trocando modelo para {body.model} (libera VRAM, ~1 min)…", "modelo")
        try:
            troca = modelos.ativar(body.model,
                                   log=lambda m, g="modelo": log(m, g))
            print(f"🔁 Troca na chamada: {troca['modelo']}"
                  f"{' em ' + str(troca.get('segundos', '?')) + 's' if troca['trocou'] else ' (já estava no ar)'}")
            log(f"✅ {body.model} no ar"
                + (f" em {troca.get('segundos', '?')}s" if troca.get("trocou") else ""),
                "modelo")
        except Exception as e:
            # 🛟 A TROCA NUNCA MATA A RESPOSTA (caso tacacá: agente da estação
            # fora → o job morria no 🔁 e a mensagem ficava "(sem resposta)").
            # Responde com o modelo ATUAL e segue — a próxima mensagem tenta
            # de novo quando a estação voltar.
            motivo = str(e).strip() or "estação com a GPU não respondeu"
            if len(motivo) > 160 or motivo.lstrip().startswith("<"):
                motivo = "estação com a GPU não respondeu (agente offline?)"
            log(f"⚠️ troca para {body.model} falhou ({motivo[:140]}) — "
                f"respondendo com o modelo atual "
                f"({_servido_agora or config.LLM_MODEL})", "modelo")
    elif body.model:
        pass  # modelo já no ar: silêncio (linha "🧠 ... sem recarga" era ruído —
              # pedido do dono; trocas/recargas seguem logadas acima)
    modelo_usado = _servido_agora or modelos.servido(modelos.CHAT_PORTA) or config.LLM_MODEL
    # com override externo, o modelo desta resposta (cache/telemetria) é o
    # ESCOLHIDO — não o servido localmente
    _ov = rag._override()
    if _ov:
        modelo_usado = f"[{_ov['provedor']}] {_ov['model']}"
    provider = body.provider or "llama-server"
    if body.mode == "livre":
        log("✍️ gerando resposta (conhecimento do modelo, sem busca)…", "geração")
        contadores.set_etapa("resposta (livre)")
        resposta = rag.answer_free(body.question, body.history, on_token=on_token)
        contadores.set_etapa(None)
        # 🧭 F3: caminho EARLY-RETURN do livre registra a resposta na bússola
        # (cache semântico removido — a bússola cobre repetições)
        if resposta and not getattr(config, "MOCK_LLM", False):
            bussola.registrar(body.question, resposta, body.sessao, owner,
                              "livre", colecoes, log=log)
        print(f"\n🧠 Pergunta (modo livre): {body.question}\n🤖 Resposta: {resposta}\n")
        return {"question": body.question, "mode": "livre", "collections": [],
                "docs": [], "answer": resposta, "erros": {},
                "model": modelo_usado, "provider": provider,
                "tokens": contadores.balanco_ler()}
    if body.mode == "auto":  # roteador decide: base / web / livre (+crítica)
        log("🤖 roteador decidindo (base / web / livre)…", "auto")
        try:
            client = QdrantClient(url=config.QDRANT_URL, timeout=30)
            out = responde_auto(client, body.question, body.history, log=log)
        except Exception as e:
            print(f"❌ Erro no modo auto: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        print(f"\n🤖 Pergunta (modo auto): {body.question}\n📚 {len(out['found'])} "
              f"fragmento(s)\n🤖 Resposta: {out['answer']}\n")
        return {"question": body.question, "mode": "auto",
                "collections": out["decisao"].get("colecoes", []),
                "docs": out["found"], "answer": out["answer"], "erros": {},
                "ferramentas": [], "mcp_erros": {}, "pendente": None,
                "aprovacoes_sessao": body.aprovacoes_sessao or {},
                "pergunta_busca": out["consulta"],
                "decisao": {"acao": out["decisao"]["acao"],
                            "motivo": out["decisao"]["motivo"]},
                "model": modelo_usado, "provider": provider,
                "tokens": contadores.balanco_ler()}
    # `colecoes` já foi resolvido no topo (tri-estado: [] = sem busca);
    # na retomada de aprovação o contexto já vem no estado do agente
    found, docs, erros, bases = [], [], {}, None
    resposta_direta = None  # texto que responde por si (score alto; já sanitizado)
    sem_sinal_topo = None   # rag puro: reranker OLHOU e nada é relevante (topo)
    pergunta_busca = body.question  # reformulada na busca (quando há histórico)
    # 🗄️ métrica da busca p/ o rodapé (None = não houve busca: cache/sem coleções)
    busca_stats = None
    if body.estado_agente:
        colecoes = body.collections or colecoes
    elif not colecoes:
        # seleção VAZIA explícita: sem reformulação, sem Qdrant, sem rerank
        # — vai direto para a geração (rag dirá "não possuo dados…",
        # híbrido responde só com o modelo)
        log("📚 sem coleções selecionadas — SEM busca na base "
            "(marque coleções ou 'todas' para consultar)", "busca")
    else:
        try:
            t_busca0 = time.time()  # 🗄️ métrica do QDRANT no rodapé
            client = QdrantClient(url=config.QDRANT_URL, timeout=30)
            if body.history and body.mode != "rag":
                log("🔎 reformulando a pergunta com o histórico…", "busca")
                contadores.set_etapa("reformulação")
            else:
                log("🔎 consultando a base…", "busca")
            # rag puro: a reformulação é LLM — a pergunta original busca direto
            pergunta_busca = (rag.reformula(body.question, body.history)
                              if body.mode != "rag" else body.question)
            contadores.set_etapa(None)
            if pergunta_busca != body.question:
                print(f"🔎 Busca reformulada: {pergunta_busca}")
                log(f"consulta efetiva: {pergunta_busca[:220]}", "busca")
            # seleção velha do navegador (coleção apagada/renomeada no
            # Qdrant) NÃO é erro de infra: sai do escopo em silêncio —
            # mesmo critério de "coleções com problema não derrubam a
            # busca" do rag.search. Escopo todo morto = busca vazia
            # (modo rag responde "sem dados"; híbrido responde só com
            # o modelo), NUNCA 503.
            vivas = [c for c in colecoes if client.collection_exists(c)]
            if len(vivas) != len(colecoes):
                mortas = [c for c in colecoes if c not in vivas]
                log("🗑️ fora do escopo (não existem mais): "
                    + ", ".join(mortas), "busca")
                colecoes = vivas
            # base unificada: buscando qualquer coleção de linguagem de
            # programação, a visão unificada entra JUNTA automaticamente
            escopo = list(colecoes)
            if (any(c in LINGUAGENS for c in escopo)
                    and BASE_UNIFICADA not in escopo
                    and client.collection_exists(BASE_UNIFICADA)):
                escopo.append(BASE_UNIFICADA)
            if not escopo:
                log("📚 escopo vazio (nada existe) — seguindo sem "
                    "contexto da base", "busca")
            achados, erros = rag.search(client, escopo, pergunta_busca,
                                        log=lambda m, g="busca": log(m, g))
            # ⚠️ top_score NASCE AQUI (0 quando a densa não traz nada): os
            # RESGATES adiante (rerank/EN/versão) podem REABASTECER achados
            # depois do `if achados` — e o rodapé lê top_score fora dele
            # (bug real: ".NET 10" com densa vazia + resgate por versão
            # preenchendo → UnboundLocalError matava a resposta)
            top_score = (max(float(s) for _, s, _ in achados)
                         if achados else 0.0)
            # 🔁 RESGATE PT→EN (bug real do dono: "Cria uma api no padrão
            # .net 10" → 0 fragmentos numa coleção dotnet de 28k docs): a
            # pergunta em PORTUGUÊS contra base EM INGLÊS afunda o score
            # denso E o full-text (termos PT não existem no texto EN; o
            # termo técnico "api" caía no filtro >3 chars). A pesquisa da
            # Biblioteca SEMPRE normalizou p/ inglês (idioma.py) — o chat
            # não tinha. NADA acima do corte → 1 chamada barata (temp 0)
            # traduz a pergunta e REBUSCA; só roda sem histórico (com
            # histórico a reformulação já cumpre o papel) e 1x.
            if (not achados and not body.history and escopo
                    and body.mode == "hibrido"):
                try:
                    from core import idioma as _idioma
                    pergunta_en = _idioma.para_busca_inglesa(
                        pergunta_busca, log=lambda m, g="busca": log(m, g))
                    if pergunta_en.strip().lower() != pergunta_busca.strip().lower():
                        log(f"🔁 resgate: rebuscando com a pergunta em "
                            f"inglês “{pergunta_en[:80]}”…", "busca")
                        achados2, _ = rag.search(
                            client, escopo, pergunta_en,
                            log=lambda m, g="busca": log(m, g))
                        if achados2:
                            achados = achados2
                            pergunta_busca = pergunta_en
                            log(f"🔁 resgate trouxe {len(achados)} "
                                "fragmento(s) — seguindo com eles", "busca")
                except Exception as e:
                    log(f"⚠️ resgate PT→EN indisponível ({str(e)[:60]})",
                        "busca")
            # TODAS as coleções EXISTENTES falharam (embedding desligado,
            # Qdrant fora): resposta vazia não ajuda — erro claro com a CAUSA
            if escopo and erros and not achados and len(erros) >= len(escopo):
                causa = next(iter(erros.values()))
                raise HTTPException(status_code=503, detail=causa)
            bases = _bases_consultadas(client, escopo)
            por_colecao = {}
            for _, _, c in achados:
                por_colecao[c] = por_colecao.get(c, 0) + 1
            log(f"📚 {len(achados)} fragmento(s): "
                + ", ".join(f"{c} ({n})" for c, n in por_colecao.items()), "busca")
            # 🎛️ reranker (F2-7): com contexto largo, o cross-encoder local
            # reordena os top por relevância real e devolve os 4 melhores
            # (menos ruído no prompt). Degrada em silêncio sem torch/flag.
            # ⚡ TOP-8 (era 15): ~1 s/par na CPU de 2 vCPUs da VPS — 15 pares
            # eram 15 s por pergunta; o top-4 sai de 8 candidatos fácil e o
            # gate fraco revalida os MESMOS 8 (cache de pares = grátis).
            # ⚡ RAG PURO reranka SEMPRE (≥2, pedido do dono 12/09: "mais
            # certeiro"): aqui a ORDEM do digest É a resposta — sem o
            # cross-encoder bilíngue a busca densa deprimia PT×EN e o dono
            # "fazia uma pergunta e recebia outra". Custo: CPU da VPS.
            if body.mode in ("rag", "hibrido") and (
                    len(achados) >= 6
                    or (body.mode == "rag" and len(achados) >= 2)):
                rr = rerank.rerank(pergunta_busca, achados[:8], top_n=4,
                                   log=lambda m, g="busca": log(m, g))
                if rr:
                    ordenados, topo = rr
                    log(f"🎛️ rerank {len(achados)}→{len(ordenados)} "
                        f"(top {topo:.3f})", "busca")
                    achados = ordenados
                elif body.mode == "rag":
                    # ⚠️ RESPOSTA HONESTA no rag puro (pedido do dono 12/09:
                    # "fiz uma pergunta e ele me deu outra resposta"): rerank
                    # devolve None também quando INDISPONÍVEL — as notas
                    # distinguem (cache hit: os pares acabaram de ser
                    # pontuados). Topo sem sinal = NADA na base responde à
                    # pergunta → o digest AVISA em vez de entregar o mais
                    # próximo como se fosse a resposta certa.
                    _notas = rerank.notas_de(
                        pergunta_busca,
                        [d.page_content for d, _, _ in achados[:8]])
                    if _notas is not None and max(_notas) < rerank.SINAL_MIN:
                        sem_sinal_topo = float(max(_notas))
                        log("🚫 rerank SEM SINAL para esta pergunta — a base "
                            "não tem material relevante; a resposta vai "
                            "AVISAR em vez de apresentar o mais próximo "
                            "como se fosse o pedido", "busca")
            # 🎯 SCORE COMO GUARDRAIL (pedido do dono): o score do melhor
            # fragmento diz o que fazer com ele —
            #   ≥ SCORE_DIRETO: a base RESPONDE por si → resposta direta do
            #     fragmento, SEM consultar a LLM (economia total de tokens);
            #   < SCORE_FRACO: fragmentos fracos NÃO sustentam a pergunta →
            #     fora do prompt (o modelo responde sozinho em vez de
            #     alucinar em cima de contexto irrelevante — caso vatapá:
            #     Fabada asturiana 0.470 virava "receita" de vatapá);
            #   entre os dois: RAG normal (base + modelo).
            if achados:
                top_score = max(float(s) for _, s, _ in achados)
                if not body.history and top_score >= config.SCORE_DIRETO:
                    doc_top = max(achados, key=lambda t: float(t[1]))[0]
                    conteudo = doc_top.page_content
                    # 🧹 HTML CRU (página mal ingerida que virou chunk): a
                    # resposta direta NUNCA devolve marcação — extrai o texto
                    # legível; sem conteúdo aproveitável, segue para o modelo.
                    # ⚠️ BLINDADO: isto roda DENTRO do try da busca e um erro
                    # aqui era mascarado como "Qdrant indisponível" — a
                    # sanitização falhou = entrega o texto cru ao modelo.
                    try:
                        if limpeza.parece_pagina_html(conteudo):
                            texto = limpeza.html_para_texto(conteudo)
                            if texto:
                                log(f"🧹 fragmento era HTML cru — texto extraído "
                                    f"({len(texto)} chars) para a resposta direta",
                                    "geração")
                                resposta_direta = texto
                            else:
                                log("🧹 fragmento era HTML cru sem texto "
                                    "aproveitável — seguindo para o modelo",
                                    "geração")
                        else:
                            # 🧹 HEADER DE CHUNK fora (bug real do dono: a
                            # resposta-direta abria com "[frango ao leite
                            # passo a passo]" — o cabeçalho contextual do
                            # chunk é METADADO de indexação, não conteúdo)
                            limpo = re.sub(r"^\s*\[[^\]\n]{1,260}\][ \t]*\r?\n",
                                           "", conteudo, count=1)
                            resposta_direta = (limpo.strip() or conteudo).strip()
                        # ⛳ PEDIDO DE CÓDIGO na resposta direta (mesma
                        # regra 3 da spec rag_puro.md — validado ao vivo:
                        # "hello world em python" top 0.673 devolvia a prosa
                        # INTEIRA do fragmento): o bloco cercado É a resposta
                        if resposta_direta:
                            _blocos = rag.bloco_de_codigo(
                                body.question, resposta_direta)
                            if _blocos:
                                resposta_direta = _blocos
                                log("⛳ pedido de código — a resposta direta "
                                    "é o BLOCO extraído da base (verbatim)",
                                    "geração")
                    except Exception as e:
                        log(f"⚠️ sanitização do fragmento falhou "
                            f"({str(e)[:80]}) — seguindo para o modelo",
                            "geração")
                    if resposta_direta is not None:
                        log(f"🎯 score {top_score:.3f} ≥ {config.SCORE_DIRETO} — "
                            "a base responde por si: resposta DIRETA do fragmento "
                            "(sem consulta à LLM)", "geração")
                elif top_score < config.SCORE_FRACO:
                    # 🛟 RESGATE pelo RERANKER (pedido "deve ser real"):
                    # pergunta PT × base EN deprime o score DENSO — o
                    # chunk REAL do Tucupi pontuava 0.547 e o gate
                    # descartava contexto verdadeiro (o modelo respondia
                    # sozinho e alucinava "Nordeste" em vez de Pará). O
                    # cross-encoder é BILÍNGUE (lê pergunta×texto JUNTOS):
                    # nota alta = relevante de verdade → MANTÉM (reordenado
                    # pela nota); nota baixa = descarta como antes (é o
                    # que separa Tucupi 0.7 do Fabada irrelevante 0.003).
                    notas = None
                    _limiar_resgate = 0.8 * config.SCORE_FRACO
                    if top_score < _limiar_resgate:
                        # ⚡ MUITO abaixo do fraco (pedido do dono 28/08:
                        # "esse pensando não deveria ser rápido?") — o
                        # cross-encoder (~1,5 s/fragmento na CPU da VPS)
                        # raramente resgata um 0.35; borderline (0.44–0.55,
                        # caso bilíngue real 0.547) SEGUE com o resgate
                        log(f"⚡ score {top_score:.3f} muito abaixo do "
                            f"fraco ({config.SCORE_FRACO}) — resgate do "
                            "reranker PULADO (economia de ~6 s de CPU)",
                            "busca")
                    else:
                        try:
                            notas = rerank.notas_de(
                                pergunta_busca,
                                [d.page_content for d, _, _ in achados[:8]],
                                log=lambda m, g="busca": log(m, g))
                        except Exception:
                            notas = None
                    if notas and max(notas) >= 0.10:
                        pares = sorted(zip(achados[:len(notas)], notas),
                                       key=lambda t: -t[1])
                        achados = [a for a, n in pares if n >= 0.05][:4]
                        log(f"🎛️ rerank RESGATOU {len(achados)} fragmento(s) "
                            f"(top {max(notas):.2f}) — score denso deprimido "
                            "(pergunta e base em idiomas diferentes?) — "
                            "contexto real mantido", "busca")
                    elif body.mode == "rag":
                        # ⚡ RAG PURO: o descarte abaixo protege o PROMPT da
                        # LLM (contexto fraco = alucinação) — mas aqui não há
                        # prompt: o material recuperado É a resposta, e zerar
                        # deixaria o usuário sem "só a base" que ele pediu.
                        # Os fracos (acima do SCORE_MIN da busca) seguem no
                        # digest, ordenados; quem julga relevância é o dono.
                        log(f"💡 top {top_score:.3f} abaixo do corte "
                            f"{config.SCORE_FRACO}, mas modo rag MOSTRA o que "
                            "a base tem (LLM não consultada)", "busca")
                    else:
                        log(f"⚠️ fragmentos fracos (top {top_score:.3f} < "
                            f"{config.SCORE_FRACO}) — a base não sustenta esta "
                            "pergunta; descartados do contexto", "busca")
                        achados = []
                        # 🔁 2º resgate PT→EN: o rerank bilíngue também não
                        # salvou — última carta é traduzir a PERGUNTA e
                        # rebuscar (conhecimento real que caiu na zona fraca
                        # por idioma; criação/mistura de assuntos não salva —
                        # a recusa orientada cuida desses)
                        if not body.history and body.mode == "hibrido":
                            try:
                                from core import idioma as _idioma2
                                _en = _idioma2.para_busca_inglesa(
                                    pergunta_busca,
                                    log=lambda m, g="busca": log(m, g))
                                if _en.strip().lower() != pergunta_busca.strip().lower():
                                    achados2, _ = rag.search(
                                        client, escopo, _en,
                                        log=lambda m, g="busca": log(m, g))
                                    if achados2 and max(float(s) for _, s, _ in achados2) >= config.SCORE_FRACO:
                                        achados = achados2
                                        pergunta_busca = _en
                                        log(f"🔁 resgate tardio (EN) trouxe "
                                            f"{len(achados)} fragmento(s) "
                                            "relevantes", "busca")
                            except Exception:
                                pass
        except HTTPException:
            raise  # 503 já traz a CAUSA — não re-empacota como "Qdrant indisponível"
        except Exception as e:
            print(f"❌ Erro na consulta: {e}")
            raise HTTPException(status_code=503, detail=f"Qdrant indisponível: {e}")
        # 🎯 RESGATE POR VERSÃO CITADA (fora do try da busca — roda com os
        # ACHADOS FINAIS; caso real do dono: 978 pontos de ".NET 10" na
        # coleção dotnet e NENHUM vinha — a pergunta multi-assunto
        # "gastronomia + .NET 10" dilui o vetor denso e os slots iam para
        # o outro assunto). Versão citada ausente dos recuperados →
        # busca LEXICAL (com ÍNDICE full-text criado lazy pelo
        # rag._busca_lexical — scroll cru SEM índice é full-scan e
        # SATUROU o Qdrant em produção) SÓ nas coleções DEV do escopo.
        if body.mode in ("rag", "hibrido") and escopo:
            try:
                from core.linguagens import EH_DEV as _EH_DEV
                docs_atuais = [d for d, _, _ in (achados or [])]
                # sem docs recuperados, TODA versão citada é "ausente" (a
                # base pode ter o material mesmo com a densa vazia — era o
                # caso e o guard `not docs` calava o resgate)
                ausentes = (rag.versoes_ausentes(body.question, docs_atuais)
                            or sorted(rag._pares_versao(body.question)))
                if ausentes:
                    termos_crus = [m.group(0) for m in
                                   rag._RE_TECH_VERSAO.finditer(body.question or "")]
                    extras = []
                    vistos = {d.page_content for d in docs_atuais}
                    for termo in termos_crus[:2]:
                        for col in escopo:
                            if col not in _EH_DEV:
                                continue  # versão de TECH busca em coleção DEV
                            for d in rag._busca_lexical(
                                    client, col, termo, limite=3):
                                if d.page_content and d.page_content not in vistos:
                                    vistos.add(d.page_content)
                                    extras.append((d, config.SCORE_MIN, col))
                    if extras:
                        achados = list(achados or []) + extras[:4]
                        # top_score honesto: os extras trazem score próprio
                        top_score = max([top_score]
                                        + [float(s) for _, s, _ in extras[:4]])
                        log(f"🎯 resgate por versão: +{min(len(extras), 4)} "
                            "fragmento(s) do material específico de "
                            f"{', '.join(termos_crus[:2])} (full-text "
                            "indexado — a busca densa multi-assunto não os "
                            "trouxe)", "busca")
            except Exception as e:
                log(f"⚠️ resgate por versão falhou: {str(e)[:60]}", "busca")
        found = [
            {
                "score": round(float(score), 4),
                "source": d.metadata.get("source"),
                "titulo": d.metadata.get("titulo"),
                "secao": d.metadata.get("secao"),
                "categoria": d.metadata.get("categoria"),
                "descricao": d.metadata.get("descricao"),
                "resumo_pt": d.metadata.get("resumo_pt") or d.metadata.get("proposito"),
                "linguagem": d.metadata.get("linguagem"),
                "qualidade": d.metadata.get("qualidade"),
                "colecao": colecao,
                "content": d.page_content,
            }
            for d, score, colecao in achados
        ]
        docs = [d for d, _, _ in achados]
        # 🗄️ MÉTRICA DA BUSCA (pedido do dono: tokens/velocidade SEMPRE no
        # rodapé — e "isso se aplica ao qdrant também"): tempo real da
        # consulta (Qdrant + rerank), nº de fragmentos e o top score —
        # visível inclusive na resposta-direta (que não gasta LLM)
        busca_stats = {"ms": int((time.time() - t_busca0) * 1000),
                       "fragmentos": len(found),
                       "top": (round(top_score, 3)
                               if achados else None)}
    # 🔎 PESQUISA-WEB (NATIVA) marcada no seletor do chat: o motor de busca
    # do RagAroy roda AGORA e as páginas INTEIRAS baixadas (DuckDuckGo/
    # Serper → download real via Trafilatura — não snippets) entram como
    # fragmentos numerados [n]: citáveis na resposta e visíveis no painel
    # de fontes. Contextualiza a sessão com informação ATUAL.
    if MCP_WEB in (body.mcps or []):
        try:
            log("🌐 pesquisa-web (nativa) marcada — buscando páginas "
                "completas na web…", "mcp")
            web_docs = _web_aprofundado(
                body.question, pergunta_busca or body.question, log=log)
            if web_docs:
                docs = list(docs or []) + web_docs
                found += [{
                    "score": None,
                    "source": d.metadata.get("source"),
                    "titulo": d.metadata.get("titulo"),
                    "secao": None, "categoria": None,
                    "descricao": d.metadata.get("descricao"),
                    "resumo_pt": None, "linguagem": None, "qualidade": None,
                    "colecao": "🌐 web", "content": d.page_content,
                } for d in web_docs]
                log(f"🌐 {len(web_docs)} página(s) da web no contexto — "
                    "cite [n]; as origens entram no painel de fontes", "mcp")
                # ⚡ RAG PURO RECONSIDERA COM A WEB (pedido do dono 12/09:
                # "não está considerando a pesquisa que fiz na web"): as
                # páginas eram anexadas DEPOIS dos fragmentos da base e o
                # digest (limite 4) as descartava — segundos de download
                # invisíveis na resposta. O MESMO cross-encoder do rerank
                # pontua base+web JUNTOS (pares da base = cache hit, custo
                # só das páginas novas) e a ordem do digest sai dali: a
                # receita baixada disputa com a base em igualdade. Sem LLM.
                if body.mode == "rag" and len(docs) >= 2:
                    rr2 = rerank.rerank(
                        pergunta_busca or body.question,
                        [(d, None, d.metadata.get("colecao", ""))
                         for d in docs[:8]],
                        top_n=6,
                        log=lambda m, g="busca": log(m, g))
                    if rr2:
                        ordenados, topo2 = rr2
                        docs = [d for d, _, _ in ordenados]
                        if sem_sinal_topo is not None \
                                and topo2 >= rerank.SINAL_MIN:
                            sem_sinal_topo = None  # a web trouxe o sinal
                        log(f"🎛️ rerank base+web → {len(docs)} fragmento(s) "
                            f"no digest (top {topo2:.3f})", "busca")
            else:
                log("⚠️ a busca web não trouxe nada — seguindo sem ela", "mcp")
        except Exception as e:
            log(f"⚠️ pesquisa-web falhou: {str(e)[:120]}", "mcp")
    usos, mcp_erros, pendente, aprovacoes = [], {}, None, body.aprovacoes_sessao or {}
    # 🛡️ GUARDA DE VERSÃO (dinâmica, contra o Qdrant — pedido do dono): a
    # pergunta cita "C# 14/.NET 10/python 3.12" e NENHUM fragmento traz?
    # O contexto do prompt ganha o aviso (rag proíbe inventar; híbrido
    # exige declarar) — e o "pensando…" mostra o porquê da resposta curta
    try:
        _ausentes = rag.versoes_ausentes(body.question, docs or [])
        if _ausentes:
            log(f"⚠️ versão citada ({', '.join(_ausentes)}) não está nos "
                "fragmentos — modelo instruído a não inventar (responda "
                "com o que a base cobre)", "busca")
    except Exception:
        pass
    # 📦 TRANSPARÊNCIA DO PROMPT (pedido: "sem ruídos — specs, digitado,
    # cache e rag"): o que EXATAMENTE vai para o modelo, em tokens
    # estimados — dá para ver de onde vem o tamanho antes de gerar.
    # (rag puro não tem prompt — não há o que estimar)
    if body.mode != "rag":
        try:
            from core.specs import spec as _spec_txt
            _partes = []
            _nome_spec = "chat" if body.mode == "rag" else (
                "hibrido" if body.mode == "hibrido" else "")
            if _nome_spec:
                _partes.append(f"spec ~{len(_spec_txt(_nome_spec)) // 4}")
            if docs:
                _partes.append(f"rag ~{len(rag.format_docs(docs)) // 4} ({len(docs)} frag.)")
            if body.history:
                _hc = sum(len(str(m.get('content') or '')) for m in body.history)
                _partes.append(f"histórico ~{_hc // 4} ({len(body.history)} msg)")
            _partes.append(f"pergunta ~{len(body.question) // 4}")
            log("📦 prompt: " + " · ".join(_partes) + " tokens (estimativa)", "geração")
        except Exception:
            pass
    # 🔎 busca web marcada = o usuário quer síntese com o motor de busca;
    # a resposta-direta-da-base (score alto) ficaria pela metade
    if resposta_direta is not None and MCP_WEB in (body.mcps or []):
        resposta_direta = None
    if resposta_direta is not None:
        # 🎯 resposta DIRETA da base: o fragmento já é a resposta — zero
        # chamada à LLM, sai na hora (as fontes seguem em `found`/painel)
        log("✍️ devolvendo o fragmento da base como resposta (0 chamada à "
            "LLM)", "geração")
        answer = resposta_direta
    elif body.mode == "hibrido" and _mcps_reais:  # servidores MCP marcados: ferramentas entram na resposta
        log(f"🔌 conectando {len(_mcps_reais)} servidor(es) MCP…", "mcp")
        ferramentas, mcp_erros = mcp_registry.carregar_ferramentas(
            _mcps_reais, log=lambda m: log(m, "mcp"))
        if ferramentas:
            log(f"🔧 agente ReAct com {len(ferramentas)} ferramenta(s)…", "mcp")
            answer, usos, pendente, aprovacoes = agent.responde(
                body.question, docs, ferramentas, body.history,
                body.estado_agente, body.aprovacao, body.aprovacoes_sessao,
                bases=bases, log=lambda m: log(m, "mcp"))
        else:  # nenhum servidor respondeu: híbrido comum
            log("⚠️ nenhum MCP respondeu — respondendo sem ferramentas", "mcp")
            answer = rag.answer_hybrid(body.question, docs, body.history, bases, on_token=on_token)
    elif body.mode == "hibrido":
        log(f"✍️ gerando resposta (base + modelo, {len(docs)} fragmento(s))…", "geração")
        contadores.set_etapa("resposta (híbrido)")
        # ⚡ STREAM AO VIVO (pedido do dono 28/08: "o pensando fica mudo"):
        # com on_token a resposta aparece SENDO ESCRITA desde o 1º token —
        # o TTFB do provedor deixa de ser um card parado
        answer = rag.answer_hybrid(body.question, docs, body.history, bases,
                                   on_token=on_token)
        contadores.set_etapa(None)
    else:
        # ⚡ RAG PURO (pedido do dono 11/09): a resposta é o DIGEST dos
        # fragmentos — a LLM de conversa NÃO é consultada (o container do
        # chat nem acorda na estação; só embedding + Qdrant + rerank rodaram)
        log(f"✍️ montando a resposta dos {len(docs)} fragmento(s) — modo rag "
            "PURO: LLM de conversa não consultada", "geração")
        if found:
            contadores.set_etapa("resposta (rag)")
            # limite acompanha o conjunto CURADO (rerank top-4 base, top-6
            # com web, +resgate por versão): o corte fixo de 4 jogava fora
            # páginas da web e extras de versão que a busca trouxe de propósito
            answer = rag.digest_rag(body.question, docs,
                                    limite=min(len(docs), 8))
            contadores.set_etapa(None)
            if sem_sinal_topo is not None:
                # o reranker (bilíngue) leu a pergunta × cada fragmento e
                # nenhum pontuou como relevante — mostrar o resto como
                # "resposta" era entregar OUTRO assunto (caso real:
                # "receita de frango" → churrasco/picanha). O TEXTO vem da
                # spec rag_puro.md (palavras ao usuário fora do código).
                from core.specs import valor as _valor_spec
                answer = _valor_spec(
                    "rag_puro", "MSG_SEM_SINAL",
                    "⚠️ **Nada na base responde a esta pergunta** — o "
                    "reranker analisou os fragmentos recuperados e nenhum "
                    "tem relação real com o pedido (a base não parece conter "
                    "este assunto).\n\nO material abaixo é apenas o mais "
                    "próximo que a busca encontrou, por referência:\n\n"
                ) + answer
        else:
            # spec restritiva (F2-8): SEM contexto não há o que responder —
            # a frase exata, sem gastar chamada de LLM.
            # 💡 PEDIDO DE CRIAÇÃO em modo rag (bug real do dono: "quero uma
            # página em .net 10 sobre culinária" → recusa nua): criar algo
            # novo é trabalho do HÍBRIDO (base orienta o estilo, modelo
            # escreve) — a recusa ORIENTA em vez de só negar
            _RE_CRIAR = re.compile(
                r"\b(quer[oa]|cri[ae]|criar|faç|faz|fazer|mont[ae]|montar|"
                r"ger[ae]|gerar|escrev|desenvolv|implement|constru|code|"
                r"program)\w*", re.I)
            _RE_COISA = re.compile(
                r"\b(p[áa]gina|site|c[óo]digo|api|app|aplica|projeto|"
                r"programa|script|componente|aba|tela|formul[áa]rio|"
                r"banco|tabela|servidor|fun[çc][ãa]|classe)\w*", re.I)
            if body.mode == "rag" and _RE_CRIAR.search(body.question or "") \
                    and _RE_COISA.search(body.question or ""):
                answer = ("Não possuo dados confiáveis o suficiente nos "
                          "documentos para responder.\n\n💡 Seu pedido parece "
                          "ser de **criação** (página, código, API…): troque "
                          "para o modo **híbrido** — a base orienta o estilo "
                          "e o modelo escreve. Dica: para código, selecione "
                          "só a coleção da tecnologia (ex.: dotnet) — misturar "
                          "assuntos dilui a busca.")
            else:
                answer = ("Não possuo dados confiáveis o suficiente nos "
                          "documentos para responder.")
    if pendente:
        log(f"🔐 aguardando sua aprovação para usar {pendente['ferramenta']}", "mcp")
        print(f"\n🔐 Ferramenta aguardando aprovação: {pendente['ferramenta']} "
              f"← {pendente['argumento'][:120]}")
    else:
        print(f"\n🔗 Pergunta (modo {body.mode}): {body.question} [coleções: {colecoes}]"
              f"\n🔌 MCPs: {body.mcps or []} — {len(usos)} chamada(s) de ferramenta"
              f"\n📚 {len(found)} documento(s)\n🤖 Resposta: {answer}\n")
    if not pendente:
        # 🧭 F3: registra (pergunta→resposta) na bússola para a PRÓXIMA
        # pergunta igual sair de graça (cache semântico removido 27/08)
        if answer and not getattr(config, "MOCK_LLM", False):
            bussola.registrar(body.question, answer, body.sessao, owner,
                              body.mode, colecoes, log=log)
    return {"question": body.question, "mode": body.mode, "collections": colecoes, "docs": found,
            "answer": answer, "erros": erros, "ferramentas": usos, "mcp_erros": mcp_erros,
            "pendente": pendente, "aprovacoes_sessao": aprovacoes,
            "pergunta_busca": pergunta_busca if not body.estado_agente else "",
            "bussola": bussola_sugestao,
            "model": modelo_usado, "provider": provider,
            "busca": busca_stats,
            "tokens": contadores.balanco_ler()}  # ÚNICO método (o antigo


# id de sessão válido: hex/uuid simples — bloqueia path traversal
# (ex.: id="../users" leria/apagaria .json FORA de sessions/)
_RE_SID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _sid_valido(sid: str | None) -> bool:
    return bool(sid) and bool(_RE_SID.match(sid))


SESSOES_QDRANT = "sessoes_chat"


def _embed_sessao(sid: str, dono: str):
    """Indexa a sessão no Qdrant (embedding bge-m3) — falha silenciosa: a
    conversa já está salva em JSON; o vetor é um extra para busca."""
    try:
        dados = sessions.get_session(sid)
        if not dados:
            return
        client = QdrantClient(url=config.QDRANT_URL, timeout=30,
                              check_compatibility=False)
        if not client.collection_exists(SESSOES_QDRANT):
            from qdrant_client.models import Distance, VectorParams
            dim = len(rag.embeddings().embed_query("dim"))
            client.create_collection(
                collection_name=SESSOES_QDRANT,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
        msgs = dados.get("messages", [])
        ultima = next((m["content"] for m in reversed(msgs)
                       if m.get("role") == "assistant" and m.get("content")), "")
        texto = (f"[sessão de chat]\n{dados.get('titulo', '')}\n\n"
                 + "\n".join(f"{m['role']}: {m['content']}" for m in msgs[-8:]))
        ponto = str(uuid.uuid5(uuid.NAMESPACE_URL, f"sessao:{sid}"))
        client.upsert(collection_name=SESSOES_QDRANT, points=[PointStruct(
            id=ponto,
            vector=rag.embeddings().embed_query(texto[:4000]),
            payload={"page_content": texto[:8000],
                     "metadata": {"tipo": "sessao", "sessao_id": sid, "owner": dono,
                                  "titulo": dados.get("titulo", ""),
                                  "resumo": ultima[:400],
                                  "atualizada": dados.get("atualizada", "")}})])
    except Exception as e:
        print(f"⚠️  Sessão '{sid}' não indexada no Qdrant: {e}")


class McpTestarIn(BaseModel):
    entrada: str  # URL http · comando (npx/uvx…) · github.com/owner/repo


# instalação de MCP como JOB (logs ao vivo no popup — igual ingestão/seed)
_mcp = JobRegistry("mcp", "instalação de MCP")


class McpInstalarEntradaIn(BaseModel):
    entrada: str = ""            # campo único (URL/comando/github) — se vazio, usa nome do catálogo
    nome: str = ""               # nome do catálogo (instalação por clique)
    params: dict = {}            # {{param}} do catálogo (pasta permitida, etc.)
    env: dict = {}               # chaves opcionais (API keys) → .env


class McpInstalarIn(BaseModel):
    nome: str  # nome no catálogo (mcp_conhecidos.json)
    params: dict = {}  # {"pasta_permitida": "...", ...} conforme o servidor


