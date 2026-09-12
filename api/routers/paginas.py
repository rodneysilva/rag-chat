"""Rotas de paginas — extraídas mecanicamente de api/app.py (split Fase 1).
Ordem interna preservada; decorator @app -> @router.
"""
from api.base import *  # noqa: F401,F403 — contrato do split
from api.routers.biblioteca import collections  # noqa: F401 — chamada cross-router (era namespace global do monólito)
from api.routers.sistema import status  # noqa: F401 — chamada cross-router (era namespace global do monólito)

from fastapi import APIRouter

router = APIRouter()
@router.get("/")
def pagina_chat(request: Request, _sid: str | None = None):
    """Home = conversa (mensagens da sessão do cookie + composer). O
    `_sid` é o override da rota /c/{sid} (conversa por slug na URI)."""
    # REGRA DO DONO (28/08): SEM slug na URI = conversa NOVA — a sessão do
    # cookie NÃO aparece (o cookie é limpo aqui; o 1º envio cria sid novo e
    # a URI é promovida para /c/{sid}). /c/{sid} = a conversa DA URI (F5
    # dentro dela volta na mesma conversa).
    sid_uso = _sid
    ctx = _paginas_ctx(request, "chat")
    ctx["mensagens"] = _msgs_da_sessao(sid_uso, ctx["usuario"])
    # job EM CURSO da sessão: o polling volta renderizado (refresh não perde)
    ctx.update(_job_ativo_ctx(sid_uso))
    # 🎯 CONSULTA CONSOLIDADA (spec core/specs/consulta_consolidada.md):
    # o composer NÃO recebe mais coleções/modelos/MCPs — modo/escopo/
    # ferramentas vêm da config da administração. Só o health escapa:
    # llm_ativo decide se o botão ✨prompt existe (sem LLM não há o que
    # reescrever); o badge 🧠 do topo segue lendo /api/modelo/ativo
    ctx["llm_ativo"] = consulta.llm_ativo()
    resposta = TEMPLATES.TemplateResponse(request, "chat.html", ctx)
    if not _sid:
        resposta.delete_cookie(SESSAO_COOKIE)  # nova conversa DE VERDADE
    return resposta


@router.get("/c/{sid}")
def pagina_chat_sid(sid: str, request: Request):
    """CONVERSA POR SLUG (pedido do dono: "incluir como slug o id da
    sessão na uri tanto do chat…"): /c/{sid} abre a conversa NA URL —
    valida o dono, assume a sessão (cookie) e renderiza a home do chat."""
    import re as _re
    if not _re.match(r"^[\w\-]{6,64}$", sid or ""):
        raise HTTPException(404, "conversa não encontrada")
    usuario = _usuario(request)
    d = sessions.get_session(sid) or {}
    if not d or (d.get("owner") or "") != usuario:
        raise HTTPException(404, "conversa não encontrada")
    resp = pagina_chat(request, _sid=sid)
    resp.set_cookie(SESSAO_COOKIE, sid, max_age=30 * 86400,
                    httponly=True, samesite="lax")
    return resp


@router.get("/biblioteca")
def pagina_biblioteca(request: Request):
    ctx = _paginas_ctx(request, "biblioteca")
    try:
        # forcar=True: a grade é a FONTE DA VERDADE na carga da página —
        # sem isso, o cache de 30 s podia trazer de volta coleção recém-
        # apagada ("exclusão fantasma")
        cols = collections(forcar=True) or []
    except Exception:
        cols = []
    ctx["colecoes"] = cols
    # ── KPIs do topo (reestruturação: a biblioteca começa pelas coleções) ──
    ctx["bib_kpis"] = {
        "colecoes": len(cols),
        "pontos": sum(c.get("points") or 0 for c in cols),
        "pontos_fmt": f"{sum(c.get('points') or 0 for c in cols):,}".replace(",", "."),
    }
    # transparência: o que existe e NÃO aparece (sistema/legado do ORIG)
    try:
        client = QdrantClient(url=config.QDRANT_URL, timeout=10,
                              check_compatibility=False)
        tudo = _scan_collections(client, incluir_sistema=True) or {}
        ctx["bib_ocultas"] = sorted(n for n in tudo
                                    if n in COLECOES_SISTEMA)
    except Exception:
        ctx["bib_ocultas"] = []
    # ═══ JOBS ATIVOS voltam com a página (a pesquisa não "some" ao navegar):
    # qualquer pesquisa/preview em andamento é re-injetada no topo com o
    # partial de polling — o estado vive no registry, não no DOM. ═══
    ativos = []
    for reg, kind, rotulo in ((_pesquisa, "pesquisa", "pesquisa na web"),
                              (_preview, "preview", "revisão de aquisição"),
                              (_ingest, "ingest", "ingestão"),
                              (_seed, "seed", "coleção por assunto")):
        try:
            with reg.lock:
                for jid, st in (reg.jobs or {}).items():
                    if isinstance(st, dict) and st.get("running"):
                        ativos.append({"kind": kind, "job": jid,
                                       "rotulo": f"{rotulo} · em andamento"})
        except Exception:
            pass
    ctx["jobs_ativos"] = ativos
    return TEMPLATES.TemplateResponse(request, "biblioteca.html", ctx)


@router.get("/dashboard")
def pagina_dashboard(request: Request):
    ctx = _paginas_ctx(request, "dashboard")
    try:
        client = QdrantClient(url=config.QDRANT_URL, timeout=10,
                              check_compatibility=False)
        scan = _scan_collections(client) or {}
    except Exception:
        scan = {}
    uso = contadores.totais() or {}
    total = uso.get("total") or {}
    por = uso.get("por_servico") or {}
    ctx["kpis"] = {
        "colecoes": len(scan), "grupos": 0,
        "pontos": sum((v or {}).get("points") or 0 for v in scan.values()),
        "tokens_in": total.get("entrada", 0), "tokens_out": total.get("saida", 0),
        "tokens_total": total.get("entrada", 0) + total.get("saida", 0),
        "chamadas": total.get("chamadas", 0), "por_servico": por,
    }
    # ── INFRA detalhada: coleções do Qdrant com pontos/dimensão ──
    ctx["colecoes_detalhe"] = sorted(
        ((nome, v) for nome, v in (scan or {}).items()),
        key=lambda kv: -(kv[1].get("points") or 0))
    # ── modelos de linguagem: uso REAL por modelo (telemetria) + GB do
    # GGUF + quem está servindo agora + VRAM corrente ──
    from core import estatisticas
    try:
        uso_modelo = estatisticas.por_modelo() or {}
    except Exception:
        uso_modelo = {}
    gb_por_alias = {}
    try:
        for m in modelos.listar():
            gb_por_alias[modelos.normalizar(m["nome"])] = m.get("gb")
    except Exception:
        pass
    servindo = modelos.servido(modelos.CHAT_PORTA)
    vram = None
    if config.EM_CONTAINER:
        try:
            vram = modelos._chamar_agente("/saude", timeout=4).get("vram_mi")
        except Exception:
            pass
    else:
        vram = modelos._vram_uso_mi()
    modelos_llm = []
    for nome, u in sorted(uso_modelo.items(),
                          key=lambda kv: -kv[1]["chamadas"]):
        # SÓ O QUE RODOU (pedido do dono: "incluir só o que foi utilizado,
        # os que não tiverem tokens ou uso, não exibir")
        if not u.get("chamadas"):
            continue
        media_s = round(u["segundos"] / u["chamadas"], 1)
        modelos_llm.append({
            "nome": nome, **u, "media_s": media_s,
            "gb": gb_por_alias.get(modelos.normalizar(nome)),
            "ativo": modelos.normalizar(nome) == modelos.normalizar(servindo),
        })
    ctx["modelos_llm"] = modelos_llm
    ctx["vram_mi"] = vram
    ctx["servindo"] = servindo
    try:
        ctx["embed_resumo"] = estatisticas.embedding_resumo()
    except Exception:
        ctx["embed_resumo"] = {"chamadas": 0, "documentos": 0, "segundos": 0}
    return TEMPLATES.TemplateResponse(request, "dashboard.html", ctx)


@router.get("/sistema")
def pagina_sistema(request: Request):
    ctx = _paginas_ctx(request, "sistema")
    if not ctx["admin"]:
        return RedirectResponse("/", status_code=303)
    st = status()
    ctx["servicos"] = st["services"]
    ctx["modelos"] = {"llm": st.get("modelo"), "embed": st.get("embedding")}
    ctx["nomes"] = {"qdrant": "Qdrant", "llm": "LLM (chat)", "embed": "Embedding"}
    # 🧠 ATIVOS pela FONTE ÚNICA (`modelos_ativos`): o cabeçalho mostra o
    # que está SERVINDO agora (chat/visão/difusores) — nunca o .env velho.
    ctx["ativos"] = modelos_ativos()
    # 🌐 provedores CADASTRADOS (retrato no cartão ☁️ do Sistema — feedback
    # de que a chave gravou: nome + nº de modelos)
    try:
        from core import provedores as _prov
        ctx["provedores_externos"] = [
            {"id": p["id"], "nome": p["nome"],
             "n_modelos": len(p["modelos"])}
            for p in _prov.listar() if p["externo"]]
        ctx["prov_conhecidos"] = [{"id": k, **v} for k, v in
                                  _prov.CONHECIDOS.items()]
    except Exception:
        ctx["provedores_externos"] = []
        ctx["prov_conhecidos"] = []
    # ── painel do MOTOR (modelos ativos + VRAM) ──────────────────────
    # em container: a verdade está no agente do host (quem tem a GPU).
    # AGENTE FORA? O status NÃO mente "desligado": a LLM continua
    # servindo PELO TÚNEL — lê pelo túnel e avisa.
    motor = {"chat": None, "embed": None, "vram_mi": None,
             "agente": None, "rodando": []}
    try:
        if config.EM_CONTAINER:
            try:
                saude = modelos._chamar_agente("/saude", timeout=5)
                motor = {"chat": saude.get("chat"),
                         "embed": bool(saude.get("embed")),
                         "vram_mi": saude.get("vram_mi"),
                         "agente": True,
                         "rodando": saude.get("rodando") or []}
            except Exception as e:
                # agente offline: a LLM pode estar no ar mesmo assim (túnel)
                motor = {"chat": modelos.servido(modelos.CHAT_PORTA),
                         "embed": modelos.embedding_no_ar(),
                         "vram_mi": None,
                         "agente": f"offline ({str(e)[:60]}) — status lido "
                                   "pelos túneis",
                         "rodando": []}
        else:
            motor = {"chat": modelos.servido(modelos.CHAT_PORTA),
                     "embed": modelos.embedding_no_ar(),
                     "vram_mi": modelos._vram_uso_mi(), "agente": None,
                     "rodando": []}
    except Exception as e:
        motor["agente"] = f"fora do ar ({str(e)[:80]})"
    ctx["motor"] = motor
    # ⚙️ CONFIGURAÇÕES: TODAS as chaves editáveis do registro FIELDS, com o
    # VALOR ATUAL do .env — agrupadas por categoria, segredos MASCARADOS.
    # (bug antigo: a lógica da máscara era invertida — chave DEFINIDA sumia
    # do form em vez de aparecer como ••••; parecia "perdida".)
    cfg_atual = config.as_dict()
    ctx["config_atual"] = cfg_atual   # usados avulsos no cabeçalho (KPIs)
    grupos_cfg: dict = {}
    for chave, (grupo, rotulo, tipo) in _campos_config().items():
        if grupo == "Consulta":
            continue  # 🎯 vive no cartão Consulta — UMA fonte de edição na UI
        bruto = cfg_atual.get(chave, os.getenv(chave, ""))
        grupos_cfg.setdefault(grupo, []).append({
            "chave": chave, "rotulo": rotulo, "tipo": tipo,
            "dica": _DICAS_CAMPO.get(chave, rotulo),
            "valor": "" if tipo == "secret" else str(bruto or ""),
            "definido": bool(bruto),   # secret definido mostra placeholder ••••
        })
    ctx["grupos_cfg"] = grupos_cfg
    # 🎯 CONSULTA CONSOLIDADA (spec core/specs/consulta_consolidada.md):
    # estado resolvido + listas para o cartão 🎯 Consulta do /sistema
    ctx["consulta"] = consulta.resumo()
    try:
        ctx["consulta_colecoes"] = collections(forcar=True) or []
    except Exception:
        ctx["consulta_colecoes"] = []
    try:
        ctx["consulta_mcps"] = [s.get("nome") or s for s
                                in mcp_registry.list_servers()]
    except Exception:
        ctx["consulta_mcps"] = []
    return TEMPLATES.TemplateResponse(request, "sistema.html", ctx)


@router.get("/entrar")
def pagina_entrar(request: Request):
    return TEMPLATES.TemplateResponse(request, "entrar.html",
                                      {"request": request, "erro": None})


@router.post("/entrar")
def entrar(request: Request, user: str = Form(...), senha: str = Form(...)):
    if not auth.verificar(user, senha):
        return TEMPLATES.TemplateResponse(request, "entrar.html",
                                          {"request": request,
                                           "erro": "usuário ou senha incorretos"},
                                          status_code=401)
    token = auth.emitir_token(user.strip())
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE_TOKEN, token, max_age=auth.TOKEN_DIAS * 86400,
                    httponly=True, samesite="lax")
    return resp


@router.get("/sair")
def sair():
    resp = RedirectResponse("/entrar", status_code=303)
    resp.delete_cookie(COOKIE_TOKEN)
    resp.delete_cookie(SESSAO_COOKIE)
    return resp


@router.get("/revisao/{pid}")
def pagina_revisao(pid: str, request: Request):
    from core import preview as _pv
    resp = _pv.ver(pid)
    if not resp:
        return TEMPLATES.TemplateResponse(request, "revisao.html",
                                          {"request": request,
                                           "resp": {"documentos": [], "descartados": [],
                                                    "clusters": [], "resumo": {},
                                                    "colecao_alvo": None, "tema_min": 0},
                                           "pid": pid, "expirou": True})
    return TEMPLATES.TemplateResponse(request, "revisao.html",
                                      {"request": request, "resp": resp, "pid": pid,
                                       "expirou": False})


