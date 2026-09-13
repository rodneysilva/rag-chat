import threading
"""
Componentes LangChain do RAG: embedding, Qdrant, LLM e geração da resposta.

As instruções de comportamento (chat, categorização, análise) vêm dos
arquivos de spec em core/specs/ — nada de prompt hardcoded aqui.
"""
import json
import re
import time

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

from . import config
from . import telemetria
from .specs import spec

# llama.cpp não valida chave por padrão, mas com --api-key no llama-server
# ela É obrigatória (401 sem). Local não usa; VPS via túnel usa LLM_API_KEY.
# Lida de config a CADA construção de cliente: a constante de import congelava
# o valor do boot (trocar a chave no Sistema só valia após restart).
def _api_key() -> str:
    return str(getattr(config, "LLM_API_KEY", "") or "").strip() or "sk-no-key"

# Lembrete curto repetido no FIM do prompt (depois do histórico): o modelo dá
# mais peso ao que está perto da geração — sem isso, um histórico com respostas
# repetidas vira "exemplo" e o modelo copia a resposta anterior por inércia.
# Texto vive na SPEC lembrete_final.md (regra de ouro: comportamento em spec,
# não no código) — fallback embutido só se a spec sumir.
def _lembrete() -> str:
    try:
        from .specs import spec as _spec
        return _spec("lembrete_final").strip()
    except Exception:
        return ("Lembrete final: esta pergunta é NOVA — nunca repite uma "
                "resposta anterior; cite o fragmento ([n]) quando usar o "
                "contexto.")


def embeddings():
    """Embedding BGE-M3 via API (/v1/embeddings) — SOBE SOZINHO se estiver
    fora do ar (ciclo on-demand: busca/ingestão o acionam com prioridade).

    Subclass com TELEMETRIA: cada lote embedado vira evento tipo "embed"
    (documentos + duração + tokens de entrada estimados pela usage quando
    o servidor devolve) — o Dashboard mostra o consumo do embedding, que
    antes ficava invisível (só a LLM de chat era contada)."""
    from . import modelos as _m
    from . import telemetria as _tel
    _m.garantir_embedding()

    class _EmbeddingsContados(OpenAIEmbeddings):
        def embed_documents(self, texts, **kw):
            import time as _t
            t0 = _t.time()
            saida = super().embed_documents(texts, **kw)
            try:
                _tel.evento("embed", f"🧬 bge-m3: {len(texts)} texto(s)",
                            docs=len(texts), modelo="bge-m3",
                            duracao_s=round(_t.time() - t0, 2))
            except Exception:
                pass
            return saida

        def embed_query(self, text, **kw):
            import time as _t
            t0 = _t.time()
            saida = super().embed_query(text, **kw)
            try:
                _tel.evento("embed", "🧬 bge-m3: consulta",
                            docs=1, modelo="bge-m3",
                            duracao_s=round(_t.time() - t0, 3))
            except Exception:
                pass
            return saida

    return _EmbeddingsContados(
        api_key=_api_key(),
        base_url=config.EMBED_BASE_URL,
        model=config.EMBED_MODEL,
        check_embedding_ctx_length=False,  # envia texto puro, sem tiktoken
        # SEM timeout o cliente OpenAI espera 600 s: com o túnel/agente
        # fora do ar, TUDO que toca embedding (título da sessão, busca,
        # ingestão) ficava pendurado por minutos — 60 s cobre o lote
        # maior do bge-m3 e falha rápido quando o servidor não existe
        timeout=60,
    )


def vectorstore(client, collection=None):
    """Acesso a uma coleção do Qdrant (a padrão do .env, ou outra informada)."""
    return QdrantVectorStore(
        client=client,
        collection_name=collection or config.COLLECTION,
        embedding=embeddings(),  # langchain >= 1.0 usa "embedding" (singular)
    )


# override de PROVEDOR EXTERNO por execução (thread-local, como os
# contadores): {base_url, api_key, model, provedor} — o chat seta quando a
# conversa escolhe glm/deepseek/openai/anthropic; vazio = llama-server local
_TL = threading.local()


def set_override(prov: dict | None) -> None:
    """Define o provedor da ESTA execução (None volta para o local)."""
    _TL.prov = prov or None


def _override() -> dict | None:
    return getattr(_TL, "prov", None)


def usa_llm_local() -> bool:
    """Esta execução usa o llama-server LOCAL? (False = provedor externo no
    override — glm/deepseek/openai… não toca a GPU da estação, e o ciclo
    frio do chat não deve religar nada por causa dela.)"""
    return not _override()


def llm(temperature=None):
    """LLM de conversa via API (/v1/chat/completions) do llama-server — OU
    de um PROVEDOR EXTERNO quando a execução tem override (glm, deepseek,
    openai, anthropic… todos falam OpenAI-compatible; a chave vem do .env).

    `temperature` sobrepõe a do .env — o agente de ferramentas usa 0:
    loop ReAct precisa de comportamento estável (mesma pergunta, mesmo
    passo a passo), não de criatividade.

    A classe conta os tokens de CADA chamada (usage devolvido pelo
    servidor) no acumulador global por serviço — tudo que passa pela LLM
    é medido, onde quer que seja chamada (chat, ingestão, estúdio…).
    """
    # CICLO FRIO (pedido do dono 10/09): a estação derruba o chat ocioso
    # (5 min) e quem RELIGA é quem precisa — a fábrica é o gargalo COMUM
    # de todo consumidor de LLM local (reformulação, categorização do
    # ingest, pesquisa, manutenção); a espera é narrada no log da THREAD
    # (contadores.log_atual dentro do garantir_llm). Erro engolido: frio
    # + agente fora → o erro REAL (conexão) nasce no invoke, no lugar de
    # um motivo distante aqui na construção do cliente.
    if not _override():
        from . import modelos as _m
        try:
            _m.garantir_llm()
        except Exception:
            pass
    from . import contadores

    class LLMContada(ChatOpenAI):
        """ChatOpenAI que registra prompt/completion tokens de cada chamada —
        no acumulador, no 'pensando…' (tempo real via thread-local) e na
        telemetria persistente (logs/telemetria.jsonl)."""

        def _registrar(self, entrada, saida, dur):
            try:
                contadores.registrar(entrada, saida, duracao_s=dur)
                # MODELO REAL: config.LLM_MODEL fica VELHO após trocas feitas
                # na estação (o .env da VPS não acompanha) — a telemetria e o
                # dashboard "por modelo" liam sempre o mesmo nome. Quem sabe
                # é o SERVIDOR (cache 10 s): lê /v1/models do llama-server.
                # Com override externo, o nome é o modelo ESCOLHIDO.
                try:
                    ov = _override()
                    if ov:
                        modelo_agora = f"[{ov['provedor']}] {ov['model']}"
                    else:
                        from .modelos import servido, CHAT_PORTA
                        modelo_agora = servido(CHAT_PORTA) or config.LLM_MODEL
                except Exception:
                    modelo_agora = config.LLM_MODEL
                # TEMPO REAL: o job desta thread (se registrou o log) mostra
                # os tokens de CADA chamada enquanto ainda está pensando —
                # com a ETAPA entre colchetes (reformulação/resposta/agente
                # passo N/verificação): o par chamada→retorno fica legível
                log = contadores.log_atual()
                if log:
                    et = contadores.etapa_atual()
                    log(f"🪙 LLM {contadores.servico_atual()}"
                        + (f" [{et}]" if et else "")
                        + f": 🔻{entrada} entrada · 🔺{saida} saída · {dur:.1f}s",
                        "tokens")
                telemetria.evento("llm", f"🧠 {modelo_agora}: "
                                         f"🔻{entrada} · 🔺{saida} · {dur:.1f}s "
                                         f"[{contadores.servico_atual()}]",
                                  entrada=entrada, saida=saida,
                                  duracao_s=round(dur, 2),
                                  modelo=modelo_agora,
                                  servico=contadores.servico_atual())
            except Exception:
                pass  # telemetria nunca derruba a resposta

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            t0 = time.time()
            resultado = super()._generate(messages, stop=stop,
                                          run_manager=run_manager, **kwargs)
            try:
                uso = (resultado.llm_output or {}).get("token_usage") or {}
                self._registrar(int(uso.get("prompt_tokens", 0)),
                                int(uso.get("completion_tokens", 0)),
                                time.time() - t0)
            except Exception:
                pass
            return resultado

        def _stream(self, messages, stop=None, run_manager=None, **kwargs):
            """STREAM também conta (bug pré-existente: respostas em
            streaming — rag com on_token — passavam POR AQUI e saíam com
            0 chamadas/0 tokens no rodapé e na telemetria). O usage viaja
            no ÚLTIMO chunk (usage_metadata) quando stream_usage=True.
            Também mede a velocidade REAL de geração: do 1º chunk em
            diante é geração pura (o tempo até ele é o pré-processamento
            do prompt) — o rodapé antigo dividia saída pelo total e o
            'tok/s' mentia com prompt grande."""
            t0 = time.time()
            t_primeiro = None
            entrada = saida = 0
            for pedaco in super()._stream(messages, stop=stop,
                                          run_manager=run_manager, **kwargs):
                # o _stream devolve ChatGenerationChunk: o usage mora na
                # MENSAGEM (.message.usage_metadata) — no chunk cru é None
                msg = getattr(pedaco, "message", pedaco)
                uso = getattr(msg, "usage_metadata", None)
                if uso:
                    entrada = int(uso.get("input_tokens") or entrada)
                    saida = int(uso.get("output_tokens") or saida)
                if t_primeiro is None:
                    t_primeiro = time.time()   # 1º token = fim do pré-processamento
                yield pedaco
            dur_total = time.time() - t0
            try:
                if saida and t_primeiro:
                    contadores.set_vel_geracao(
                        round(saida / max(dur_total - (t_primeiro - t0), 1e-3), 1))
            except Exception:
                pass
            self._registrar(entrada, saida, dur_total)

    # TEMPERATURA: uma regra só (pedido do dono) — valor do Sistema/.env
    # vale para TODAS as LLMs (local e provedores externos); default 0.5,
    # alterável na tela Sistema sem restart. O antigo 0.15 para "coder"
    # criava exceção invisível que contradizia o valor configurado.
    if temperature is None:
        temperatura = config.TEMPERATURE
    else:
        temperatura = temperature
    ov = _override()
    return LLMContada(
        api_key=(ov or {}).get("api_key") or _api_key(),
        base_url=(ov or {}).get("base_url") or config.LLM_BASE_URL,
        model=(ov or {}).get("model") or config.LLM_MODEL,
        temperature=temperatura,
        # usage no ÚLTIMO chunk do stream (alimenta o _stream do LLMContada;
        # sem isto o rodapé de respostas em streaming ficava 0/0)
        stream_usage=True,
        # sem timeout o job do chat podia ficar "running" para sempre com os
        # slots do llama-server ocupados (fila em vez de erro) — 15 min cobre
        # as respostas mais longas com contexto grande
        timeout=900,
        # UA próprio: o WAF da borda bloqueia UA de Python (OpenAI/Python,
        # python-httpx) com 403 — provadores externos via domínio próprio
        # (ex.: túnel da estação) morriam na mão do Cloudflare
        default_headers={"User-Agent": "ragaroy/1.0"},
    )


def _history_messages(history) -> list:
    """Últimas 12 mensagens (era 6 — pedido do dono 28/08: em conversas de
    continuidade "E mais 2? E mais 3? E a raiz quadrada?" a 1ª pergunta caía
    FORA da janela e o modelo perdia a conta acumulada; 12 cobre a cadeia)."""
    msgs = []
    for m in (history or [])[-12:]:
        classe = AIMessage if m.get("role") == "assistant" else HumanMessage
        msgs.append(classe(content=str(m.get("content", ""))))
    return msgs


def _system_text(nome_spec: str) -> str:
    """Texto da spec + extras do operador (entra no prompt como valor, não template)."""
    # 📅 DATA/HORA DO SERVIDOR em TODA chamada (pedido do dono 28/08:
    # "que dia é hoje?" saía 29/10/2023 — data do corte de treinamento).
    # O modelo SABE a data corrente antes de abrir a boca.
    from datetime import datetime as _dt
    _d = _dt.now()
    _DS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
           "sexta-feira", "sábado", "domingo")
    _MS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho",
           "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")
    texto = (f"📅 Hoje é {_DS[_d.weekday()]}, {_d.day} de "
             f"{_MS[_d.month - 1]} de {_d.year}, {_d.strftime('%H:%M')} "
             "(relógio do servidor)." + "\n"
             "Toda referência a 'hoje', 'agora', "
             "'ontem', 'este ano' ou datas correntes usa ESTA data — nunca "
             "uma data do treinamento." + "\n\n" + spec(nome_spec))
    # ⏱ MODELO EXTERNO: provedores cloud desaceleram gerações longas
    # (medido na prática: zai flash 370→46 tok/s em ~3,5 k tokens, com
    # corte de stream) — densidade máxima, teto curto, salvo pedido
    # explícito de texto longo.
    try:
        if _override():
            texto += ("\n\n⏱ LIMITE DE SAÍDA: você roda num provedor "
                      "externo que DESACELERA respostas longas. Seja "
                      "maximamente DENSO: tabela/bullets, sem introdução "
                      "nem conclusão repetida, no máximo ~400 palavras — "
                      "exceto se o usuário pedir explicitamente um texto "
                      "longo.")
    except Exception:
        pass
    if config.PROMPT_SYSTEM.strip():  # instruções extras opcionais do operador
        texto += "\n\nInstruções adicionais do operador:\n" + config.PROMPT_SYSTEM
    return texto


def build_prompt():
    """Prompt do chat (modo RAG): spec fixa (specs/chat.md) + contexto.

    A spec e o histórico entram como VALORES, então texto com { } não quebra
    o template.
    """
    return ChatPromptTemplate.from_messages([
        ("system", "{system_text}\n\nContexto:\n{context}"),
        MessagesPlaceholder("history"),
        ("system", _lembrete()),
        ("human", "{question}"),
    ])


def format_docs(docs):
    """Junta os documentos recuperados em um texto numerado para o prompt.

    Cada fragmento traz sua origem (coleção · área) para a LLM saber de que
    domínio aquele texto é (tecnologia, medicina, psicologia…).
    """
    partes = []
    for i, d in enumerate(docs, 1):
        colecao = d.metadata.get("colecao", "")
        area = d.metadata.get("area", "")
        origem = " · ".join(x for x in (colecao, area) if x)
        tag = f" ({origem})" if origem else ""
        partes.append(f"[{i}]{tag} {d.page_content}")
    return "\n\n".join(partes)


def _contexto_com_bases(bases: str | None, docs_formatados: str) -> str:
    """Prepends ao contexto o mapa das bases selecionadas (se o chamador enviar).

    `bases` já vem formatado pelo chamador (API), com nome + área/categoria +
    descrição de cada coleção consultada — é o que faz a LLM "compreender" de
    que domínio é o material antes de ler os fragmentos.
    """
    return f"{bases}\n\n{docs_formatados}" if bases else docs_formatados


# ─── CONVERSA NATURAL (guardrail de código — o modelo pequeno ecoa o
# envelope do sistema: "Contexto recuperado da base: … (nada foi
# recuperado…) Resposta: …". A conversa do chat tem que ser uma MENSAGEM
# natural; as fontes vivem no painel da interface, não no texto) ───
_RE_ECO_INICIO = re.compile(
    r"^\s*(?:[#>*\-•\s]*)*(?:\*{0,2})(?:contexto recuperado(?: da base)?"
    r"|fragmentos?(?: recuperados?)?|base consultada|resposta|answer)"
    r"(?:\*{0,2})\s*:?\s*(?:\*{0,2})\s*$", re.I)
_RE_ECO_NADA = re.compile(r"^\s*[\(\*]{0,2}nada foi recuperado", re.I)
_RE_RESPOSTA_LABEL = re.compile(r"^\s*\*{0,2}resposta\*{0,2}\s*:\s*", re.I)
_RE_SECAO_FONTES = re.compile(
    r"\n+\s*(?:[#>*\-•\s]*)*\*{0,2}\s*(?:📚\s*)?fontes?\s*(?:da\s+base)?"
    r"[\s*:#>-]*\n", re.I)


def naturalizar(texto: str) -> str:
    """Remove do INÍCIO/FIM da resposta os artefatos de eco do prompt e a
    seção "Fontes:" final (as fontes seguem no painel — pedido do dono:
    "a conversa no chat deve ser natural").

    Casos cobertos (vistos em produção com modelos 7–8B):
    1. eco completo "Contexto recuperado da base: … Resposta: X" → fica X;
    2. linhas-cabeçalho soltas ("Contexto recuperado da base:", "(nada foi
       recuperado…)", "Resposta:") no início → removidas;
    3. seção "Fontes:"/ "Fontes" no final (≤8 linhas curtas) → removida.
    """
    if not texto:
        return texto
    t = texto.strip()
    # 1) eco completo: o modelo reproduziu o envelope E marcou "Resposta:"
    m = re.search(r"^\s*\**\s*contexto recuperado.*?\n\**\s*resposta\**\s*:", t,
                  re.I | re.S)
    if m:
        t = t[m.end():].lstrip(" \n*#>-")
    # 2) cabeçalhos soltos no início (repete enquanto casar)
    for _ in range(6):
        linhas = t.split("\n")
        while linhas and not linhas[0].strip():
            linhas.pop(0)
        if not linhas:
            return ""
        if (_RE_ECO_INICIO.match(linhas[0]) or _RE_ECO_NADA.match(linhas[0])):
            linhas.pop(0)
            t = "\n".join(linhas)
            continue
        linha = _RE_RESPOSTA_LABEL.sub("", linhas[0], count=1)
        if linha != linhas[0]:
            linhas[0] = linha
            t = "\n".join(linhas)
            continue
        break
    # 3) seção "Fontes:" FINAL — só quando o restante é lista curta de
    #    citações/origens (não arranca conteúdo real do meio da resposta)
    m = _RE_SECAO_FONTES.search(t)
    if m:
        calda = t[m.end():].strip("\n")
        linhas_c = [l for l in calda.split("\n") if l.strip()]
        if (linhas_c and len(linhas_c) <= 8
                and all(len(l.strip()) <= 220 for l in linhas_c)
                and "```" not in calda):
            t = t[:m.start()].rstrip(" \n*#>-")
    return t.strip()


def _gerar(chain, payload: dict, on_token=None) -> str:
    if on_token is None:
        return naturalizar(chain.invoke(payload))
    buf = []
    for pedaco in chain.stream(payload):
        if pedaco:
            buf.append(pedaco)
            try:
                on_token(''.join(buf))
            except Exception:
                pass
    # o AO VIVO mostra o bruto (natural de um stream); o FINAL gravado é
    # naturalizado — eco de envelope/sessão de fontes não fica na conversa
    return naturalizar(''.join(buf))


# ─── GUARDA DE VERSÃO (código, dinâmico — "a spec monta com base no
# qdrant", pedido do dono): a pergunta cita versão/ano de tecnologia
# (C# 14, .NET 10, python 3.12…) e NENHUM fragmento recuperado traz? o
# contexto ganha um REGISTRO DA BUSCA avisando o modelo para não inventar
# recursos daquela versão — o modelo 8B "conhece" o mundo antigo do
# treinamento e apresentava sintaxe inventada como se fosse da versão
# pedida. Zero fato hardcoded: a checagem é a MESMA regex contra a
# pergunta e contra os fragmentos que vieram do Qdrant. ───
_RE_TECH_VERSAO = re.compile(
    r"(?:\.\s?net\s*(?:core\s*|framework\s*)?v?(\d{1,2})(?:\.\d+)?"
    r"|\bdotnet\s*v?(\d{1,2})\b"
    r"|\b(?:c\s*#|csharp)\s*v?(\d{1,2})\b"
    r"|\b(python|java|node(?:js)?|deno|bun|typescript|javascript|react|vue|"
    r"angular|django|flask|fastapi|rails|ruby|rust|golang|php|laravel|"
    r"kotlin|swift|spring|svelte)\s+v?(\d{1,2})(?:\.\d+)?)", re.I)


def _pares_versao(texto: str) -> set[str]:
    """{"C# 14", ".NET 10", "python 3"} citados no texto (canônico)."""
    pares = set()
    for m in _RE_TECH_VERSAO.finditer(texto or ""):
        g = m.groups()
        if g[0]:
            pares.add(f".NET {g[0]}")
        elif g[1]:
            pares.add(f".NET {g[1]}")
        elif g[2]:
            pares.add(f"C# {g[2]}")
        elif g[3] and g[4]:
            pares.add(f"{g[3].lower()} {g[4]}")
    return pares


def versoes_ausentes(question: str, docs) -> list[str]:
    """Versões citadas na pergunta que NÃO aparecem em nenhum fragmento
    recuperado — a distância entre o que foi pedido e o que a base traz."""
    citadas = _pares_versao(question or "")
    if not citadas or not docs:
        return []
    na_base = _pares_versao("\n".join(str(d.page_content) for d in docs))
    return sorted(c for c in citadas if c not in na_base)


def _ctx_com_guarda(contexto: str, question: str, docs, hibrido: bool = False) -> str:
    """Anexa ao contexto o REGISTRO DA BUSCA quando a versão pedida não
    está nos fragmentos (rag: proíbe inventar; híbrido: exige declarar
    que não vem da base)."""
    ausentes = versoes_ausentes(question, docs)
    if not ausentes:
        return contexto
    rigido = ("NÃO invente recursos, sintaxe, APIs ou exemplos desta(s) "
              "versão(ões): responda com o que os fragmentos realmente "
              "trazem, informe qual versão os documentos cobrem e diga que "
              "a versão pedida não está na base.")
    flexivel = ("Se complementar com conhecimento próprio sobre ela(s), "
                "DIGA explicitamente que não vem da base e pode estar "
                "desatualizado — nunca apresente como conteúdo dos documentos.")
    return (contexto
            + "\n\n[REGISTRO DA BUSCA] A pergunta cita "
            + ", ".join(ausentes)
            + ", mas NENHUM fragmento recuperado menciona esta(s) versão(ões). "
            + (flexivel if hibrido else rigido))


def answer(question, docs, history=None, bases=None, on_token=None):
    """Resposta completa em uma string (usada pela API/webui)."""
    chain = build_prompt() | llm() | StrOutputParser()
    return _gerar(chain, {"system_text": _system_text("chat"),
                          "context": _ctx_com_guarda(
                              _contexto_com_bases(bases, format_docs(docs)),
                              question, docs),
                          "question": question, "history": _history_messages(history)},
                  on_token)


# ─── digest do modo rag PURO: limpeza de detritos + recorte do trecho ───
# (pedido do dono 12/09: "<sup> aparecendo", fragmento-monstro inteiro e
# "fiz uma pergunta e ele me deu outra resposta")
_RE_SUP = re.compile(r"<sup\b[^>]*>.*?</sup>|<sup\b[^>]*/?>|</sup>",
                     re.I | re.S)
_RE_REF = re.compile(r"<ref\b[^>]*(?:/>|>.*?</ref>)|</ref>", re.I | re.S)
_RE_NOTA = re.compile(
    r"\s*\[(?:\d{1,3}|[a-z]|nota [^\]\n]{1,24}"
    r"|cita[çc][ãa]o necess[áa]ria|citation needed)\]", re.I)
# ⛳ PEDIDO DE CÓDIGO no rag puro (spec core/specs/rag_puro.md, pedido do
# dono 12/09: "hello world em qualquer linguagem com base no que tenho no
# qdrant, sem recorrer a llm"): pergunta pede código e o fragmento TEM
# bloco cercado (```) → o bloco entra INTEIRO e VERBATIM — EXTRAÇÃO da
# base, nunca geração. Sem bloco no fragmento, o trecho de prosa segue.
_RE_PEDIDO_CODIGO = re.compile(
    r"hello\s*world|ol[áa]\s+mundo|\bc[óo]digo\b|\bcode\b|\bscript\b|"
    r"\bsnippet\b|exemplo\s+de\s+c[óo]digo|mostre?\s+o\s+c[óo]digo|"
    r"como\s+(?:escrever|implementar|programar)\b|"
    r"\bfun[çc][ãa]o\s+(?:que\s+)?(?:fa[çc]a|retorne)", re.I)
_RE_BLOCO_CERCADO = re.compile(r"```[\w+\-#.]*(?:[ \t]*\r?\n).*?```", re.S)


def bloco_de_codigo(pergunta: str, texto: str, max_blocos: int = 2) -> str | None:
    """Pedido de código + bloco cercado no texto → o(s) bloco(s) INTEIROS e
    VERBATIM (regra 3 da spec rag_puro.md) — compartilhado entre o digest
    rag e a resposta direta. None quando não é pedido de código ou o texto
    não tem bloco (a prosa responde como sempre)."""
    if not _RE_PEDIDO_CODIGO.search(pergunta or ""):
        return None
    blocos = _RE_BLOCO_CERCADO.findall(texto or "")
    return "\n\n".join(blocos[:max_blocos]) if blocos else None


def traduzir_resposta_direta(pergunta: str, texto: str) -> str:
    """Resposta DIRETA (score ≥ SCORE_DIRETO) num idioma que não o da
    pergunta → sai traduzida, com o marcador da spec — a MESMA regra do
    digest (caso real do dono 13/09: "Como desenvolvo uma api em dotnet?"
    devolvia os passos do tutorial MS Learn EM INGLÊS: "Create a web
    project — From the File menu…").

    Bloco de código verbatim (regra 3) e texto já no idioma da pergunta
    entram como estão. Trecho longo é RECORTADO (~900 chars, parágrafo
    mais parecido) antes de traduzir — o motor opus-mt tem teto de ~350
    tokens por item e truncar no meio seria pior que recortar na borda.
    Tradutor é CPU (spec traducao.md): a LLM de conversa segue desligada.
    """
    if not texto or not _eh_portugues(pergunta or ""):
        return texto
    if texto.lstrip().startswith("```"):          # código verbatim: como está
        return texto
    if _eh_portugues(texto):
        return texto
    trecho = texto if len(texto) <= 1100 else _digest_trecho(
        texto, _digest_termos(pergunta), pergunta_pt=True)
    from .tradutor import palavra, traduzir_lote
    try:
        lote = traduzir_lote([trecho])
    except Exception:
        lote = None
    if not lote or not lote[0]:
        return texto                             # indisponível: original
    return (lote[0] + " "
            + palavra("MARCADOR_TRADUZIDO", "*(traduzido)*")).strip()
_STOP_DIGEST = frozenset(
    "a o as os um uma uns umas de do da das dos e em no na nos nas por para "
    "com que qual quais quanto quando onde como quem cuja ao aos à às é foi "
    "ser está esta são the of and or an in on for to with is are was were "
    "be been this that it its as at by from which also known made".split())


def _digest_termos(texto: str) -> set[str]:
    """Termos normalizados (minúsculos, sem acento) fora das stopwords."""
    import unicodedata
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    return {w for w in re.findall(r"[a-z0-9]{3,}", t)
            if w not in _STOP_DIGEST}


def _eh_portugues(texto: str) -> bool:
    """Heurística leve (sem LLM): palavras funcionais PT × EN na amostra.
    Lista ampla de propósito — frase curta PT sem NENHUM marcador empatava
    0×0 e o trecho seguia para o tradutor ('O tucupi é um caldo amarelo…'
    não tinha 'um'/'é'/'da' na lista antiga)."""
    t = (texto or "").lower()[:2000]
    pt = len(re.findall(r"\b(?:que|não|nao|um|uma|uns|umas|é|com|para|de|do|"
                        r"da|dos|das|no|na|em|por|mais|como|está|são|sao|"
                        r"foi|era|tem|há|sem|entre|sobre|muito|quando|porque|"
                        r"onde|estar|também|tambem|já|ja|ainda|assim|aqui|"
                        r"pelo|pela|seu|sua|então|entao)\b", t))
    en = len(re.findall(r"\b(?:the|and|with|from|this|that|which|also|"
                        r"known|made|after|being|there|into|than|then|"
                        r"these|those|its|their|has|have|was|were)\b", t))
    return pt > en


def _digest_trecho(txt: str, termos: set[str], pergunta_pt: bool,
                   max_chars: int = 900) -> str:
    """Recorta o PARÁGRAFO mais parecido com a pergunta (± vizinhos enquanto
    cabe). Sem LLM, "mais certeiro" = sobreposição de termos + preferência
    pelo idioma da pergunta; trecho já curto sai inteiro."""
    if len(txt) <= max_chars:
        return txt
    parags = [p.strip() for p in re.split(r"\n\s*\n", txt) if p.strip()]
    if not parags:
        return txt[:max_chars].rsplit(" ", 1)[0] + "…"
    melhor, melhor_pontos = 0, -1.0
    for n, p in enumerate(parags):
        pontos = float(len(_digest_termos(p) & termos))
        if pergunta_pt and len(p) >= 80:
            if _eh_portugues(p):
                pontos += 1.0        # mesmo idioma da pergunta: sobe
            else:
                pontos -= 0.5        # idioma diverso: leve desconto
        if len(p) < 80:
            pontos *= 0.5            # linha solta pesa menos que parágrafo
        if pontos > melhor_pontos:
            melhor, melhor_pontos = n, pontos
    if melhor_pontos <= 0:
        melhor = 0                    # nada casou: começa do topo do trecho
    ini, fim = melhor, melhor + 1
    while ini > 0 and len("\n\n".join(parags[ini - 1:fim])) <= max_chars * 0.6:
        ini -= 1                      # um pouco de contexto ANTERIOR cabe
    out = "\n\n".join(parags[ini:fim]).strip()
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + "…"
    return ("…" if ini > 0 else "") + out + ("…" if fim < len(parags) else "")


def _eh_ingles(texto: str) -> bool:
    """Evidência REAL de inglês — usado em TÍTULOS curtos, onde a contagem
    PT×EN empata (0×0) e traduzir 'Tucupi — síntese' (já em PT) seria pior
    que deixar como está."""
    t = (texto or "").lower()[:300]
    en = len(re.findall(r"\b(?:the|of|and|with|from|this|that|also|known|"
                        r"made|being|cuisine|dish)\b", t))
    return en > 0 and not _eh_portugues(texto)


def _unquote_titulo(t) -> str:
    """Título de exibição: decodifica slug de URL e troca underscores por
    espaços ("Cuisine_of_Par%C3%A1" → "Cuisine of Pará")."""
    from urllib.parse import unquote as _unquote
    return _unquote(str(t or "").strip()).replace("_", " ")


def digest_rag(question, docs, limite: int = 4) -> str:
    """Modo rag PURO (pedido do dono 11/09: "quando seleciono só a base, não
    precisa consultar a llm, somente o embedding"): a resposta É o digest dos
    fragmentos recuperados — generaliza a resposta-direta (SCORE_DIRETO) para
    qualquer score, sem NENHUMA chamada à LLM de conversa.

    Os fragmentos já vêm ordenados (rerank rodou antes). Cada um entra com:
    cabeçalho numerado + TÍTULO + coleção; detritos de citação da Wikipédia
    (<sup>, <ref>, [12]) removidos; e apenas o TRECHO mais parecido com a
    pergunta (parágrafo ± vizinhos) — não a seção inteira.

    ⇄ TRADUÇÃO (pedido do dono 12/09: "o retorno tem partes em português e
    outras em inglês"): pergunta PT + trecho EN → o trecho (e o título com
    evidência de inglês) sai em PT via opus-mt local, marcado *(traduzido)*.
    Em LOTE — uma passada do modelo cobre tudo; indisponível = original."""
    from . import limpeza as _limpeza
    termos = _digest_termos(question)
    pergunta_pt = _eh_portugues(question)
    # 1ª passada: limpa/recorta/título (a tradução vem depois, em lote)
    itens = []
    for d in docs[:limite]:
        txt = (d.page_content or "").strip()
        if not txt:
            continue
        try:
            if _limpeza.parece_pagina_html(txt):
                txt = _limpeza.html_para_texto(txt) or txt
        except Exception:
            pass  # sanitização falhou = entrega o texto cru (blinda o fluxo)
        # 🧹 DUMP HF (linhas "[linha N] campo: v | …"): a higienização tira
        # da base, mas o digest não pode exibir o lixo que AINDA não passou
        # por ela — belt-and-suspenders (regra 2 da spec)
        txt = _limpeza.limpar_dump_hf(txt)
        # header "[título contextual]" do chunk é METADADO de indexação — fora
        # (cap 260: o padrão novo "O que é · Para que serve · parte i/n" é longo)
        txt = re.sub(r"^\s*\[[^\]\n]{1,260}\][ \t]*\r?\n", "", txt, count=1)
        # detritos de citação (o _md_basico ESCAPA html — <sup> virava texto
        # visível na resposta, bug real visto em produção 12/09)
        txt = _RE_SUP.sub(" ", txt)
        txt = _RE_REF.sub(" ", txt)
        txt = _RE_NOTA.sub("", txt)
        txt = re.sub(r"[ \t]{2,}", " ", txt)
        # ênfase colada ("select**New**" renderiza "selectNew"): espaço nas
        # bordas do negrito FORA de cercas — o lixo já está na base, o reparo
        # é na EXIBIÇÃO (limpeza.reparar_enfase é fence-aware)
        txt = _limpeza.reparar_enfase(txt)
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        # ⛳ PEDIDO DE CÓDIGO (regra 3 da spec rag_puro.md): o bloco cercado
        # do fragmento entra INTEIRO e VERBATIM — a base RESPONDE com o que
        # tem (extração), sem gerar nada; arquivo de código PURO (sem cerca
        # no texto) vira bloco cercado da linguagem do arquivo
        trecho = bloco_de_codigo(question, txt)
        if trecho is None and _RE_PEDIDO_CODIGO.search(question or ""):
            if d.metadata.get("camada") == "codigo":
                _nome = str(d.metadata.get("arquivo")
                            or d.metadata.get("source") or "")
                _ext = _nome.rpartition(".")[2].lower()
                _lingua = str(d.metadata.get("linguagem") or
                              {"py": "python", "cs": "csharp", "js": "javascript",
                               "ts": "typescript", "rs": "rust", "go": "go",
                               "sh": "bash", "ps1": "powershell"}.get(_ext, _ext))
                trecho = (f"```{_lingua}\n"
                          f"{_digest_trecho(txt, termos, False)}\n```")
        itens.append({
            "n": len(itens) + 1,
            "trecho": trecho or _digest_trecho(txt, termos, pergunta_pt),
            # slug de URL vira título legível ("Cuisine_of_Par%C3%A1" →
            # "Cuisine of Pará")
            "titulo": _unquote_titulo(d.metadata.get("titulo")),
            "o_que_e": str(d.metadata.get("o_que_e") or "").strip(),
            "colecao": d.metadata.get("colecao", ""),
            "area": d.metadata.get("area", ""),
        })
    for it in itens:
        # bloco de código extraído NÃO é prosa: jamais vai ao tradutor
        it["traduzivel"] = (pergunta_pt
                            and not it["trecho"].lstrip().startswith("```")
                            and not _eh_portugues(it["trecho"]))
    # fila de tradução: trecho + título (só título com evidência REAL de
    # inglês) de cada item não-PT — UMA passada do modelo cobre tudo
    pendentes = []
    for it in itens:
        if it["traduzivel"]:
            pendentes.append((it, "trecho"))
            if it["titulo"] and _eh_ingles(it["titulo"]):
                pendentes.append((it, "titulo"))
    if pendentes:
        from .tradutor import traduzir_lote
        try:
            lote = traduzir_lote([it[c] for it, c in pendentes]) or []
        except Exception:
            lote = []
        for (it, campo), novo in zip(pendentes, lote):
            if novo:
                it[campo] = novo
                it["traduzido"] = True
    # 2ª passada: cabeçalhos numerados + separadores (o marcador de tradução
    # vive na spec core/specs/traducao.md — palavras ao usuário fora do código)
    from .tradutor import palavra as _palavra_trad
    # 🗂️ AGRUPAMENTO POR ASSUNTO (regra 5 da spec — pedido do dono 12/09:
    # "não tem como organizar melhor as informações?"): fragmentos de
    # assuntos DIFERENTES ficam em seções próprias (código junto com código,
    # cozinha com cozinha) — a seção entra na ordem do MELHOR fragmento do
    # grupo e, dentro do grupo, a ordem do reranker manda. Um assunto só
    # (ou área desconhecida em tudo) = sem seções: saída idêntica à de antes
    grupos: list[tuple[str, list]] = []
    indice: dict[str, list] = {}
    for it in itens:
        chave = (it["colecao"] if it["colecao"] == "🌐 web"
                 else str(it["area"] or "").strip())
        if chave not in indice:
            indice[chave] = []
            grupos.append((chave, indice[chave]))
        indice[chave].append(it)
    partes, n = [], 0
    for chave, grupo in grupos:
        blocos = []
        for it in grupo:
            n += 1
            it["n"] = n            # renumera na ordem VISUAL (agrupada)
            # 🎯 CONSULTA CONSOLIDADA (regra 6 da spec consulta_consolidada.md):
            # o NOME da coleção NÃO aparece na resposta — escopo é assunto da
            # administração. A origem visível é a ÁREA (domínio do texto) ou o
            # marcador 🌐 web para páginas baixadas
            if it["colecao"] == "🌐 web":
                origem = it["colecao"]   # "🌐 web · web" seria redundância
            else:
                origem = str(it["area"] or "").strip()
            cab = (f"**{it['n']} · {it['titulo']}**" if it["titulo"]
                   else f"**{it['n']}**")
            if origem:
                cab += f" — {origem}"
            # O QUE É (regra 1 da spec rag_puro.md): a metadata do padrão de
            # ingestão traz "o que é" — subtítulo quando difere do título
            oq = it.get("o_que_e") or ""
            if oq and oq != str(it["titulo"] or ""):
                cab += f"\n\n*{oq[:140]}*"
            if it.get("traduzido"):
                cab += " " + _palavra_trad("MARCADOR_TRADUZIDO", "*(traduzido)*")
            blocos.append(cab + "\n\n" + it["trecho"])
        secao = "\n\n---\n\n".join(blocos)
        if chave and len(grupos) > 1:
            secao = f"### {chave}\n\n{secao}"
        partes.append(secao)
    return "\n\n---\n\n".join(partes)


def answer_free(question, history=None, on_token=None):
    """Modo livre: gera a resposta com o conhecimento do modelo, sem busca no Qdrant."""
    chain = (ChatPromptTemplate.from_messages([
        ("system", "{system_text}"),
        MessagesPlaceholder("history"),
        ("system", _lembrete()),
        ("human", "{question}"),
    ]) | llm() | StrOutputParser())
    return _gerar(chain, {"system_text": _system_text("geracao"), "question": question,
                          "history": _history_messages(history)}, on_token)


def _ultimo_codigo(history) -> str:
    """Último bloco de código das respostas da conversa (para o envelope —
    pergunta CURTA tipo 'quero que seja web' quase sempre se refere a ELE;
    sem isto o 7B respondia um Hello World genérico fora do assunto)."""
    for m in reversed(history or []):
        if m.get("role") != "assistant":
            continue
        txt = str(m.get("content", ""))
        if "```" not in txt:
            continue
        partes = txt.split("```")
        blocos = [b for b in partes[1::2] if b.strip()]
        if not blocos:
            continue
        cod = blocos[-1].strip()
        # primeira linha pode ser a linguagem (```python) — descarta
        linhas = cod.splitlines()
        if linhas and linhas[0].strip() and not any(c in linhas[0] for c in "(=.;:"):
            cod = "\n".join(linhas[1:])
        return cod[:2400]
    return ""


def answer_hybrid(question, docs, history=None, bases=None, on_token=None):
    """Modo híbrido: busca na base como referência e a LLM contextualiza/completa."""
    chain = (ChatPromptTemplate.from_messages([
        ("system", "{system_text}\n\nContexto recuperado da base (pode estar vazio ou pouco relevante):\n{context}"),
        MessagesPlaceholder("history"),
        ("system", _lembrete()),
        ("human", "{question}"),
    ]) | llm() | StrOutputParser())
    contexto = format_docs(docs) if docs else "(nada foi recuperado da base para esta pergunta)"
    contexto = _contexto_com_bases(bases, contexto)
    # guarda de versão também no híbrido (aviso flexível: pode completar,
    # mas tem que DECLARAR que não veio da base)
    contexto = _ctx_com_guarda(contexto, question, docs, hibrido=True)
    # ENVELOPE (dados, não comportamento): pergunta CURTA de continuação
    # ganha o ÚLTIMO CÓDIGO da conversa colado — o 7B não reconecta sozinho
    # e respondia fora do assunto (Hello World para um pedido de culinária).
    if len(question.split()) <= 8:
        cod = _ultimo_codigo(history)
        if cod:
            contexto += ("\n\n[ÚLTIMO CÓDIGO desta conversa — a pergunta atual é "
                         "curta e provavelmente se REFERE a ele; transforme/ajuste "
                         "ESTE código conforme o pedido, mantendo o assunto]:\n```\n"
                         + cod + "\n```")
    return _gerar(chain, {"system_text": _system_text("hibrido"), "context": contexto,
                         "question": question, "history": _history_messages(history)}, on_token)


# GUARDRAIL de reformulação (código, não só spec — o 7B ignora spec): a
# saída é uma CONSULTA, não uma resposta. Padrões de início de resposta
# ("Claro!", "Vou criar…") ou consulta longa demais = LLM copiou a
# resposta anterior → usa a pergunta original (a busca segue com termos
# reais do usuário, nunca com texto gerado).
_RE_RESPOSTA = re.compile(
    r"^(claro|certo|sure|of course|entendo|pe[çc]o desculpas|desculpe|"
    r"vou |vou criar|para criar|para responder|abaixo|aqui est[áa]|"
    r"i'?ll |i will|let'?s )\b", re.I)


def _sanear_consulta(consulta: str, question: str, log=None) -> str:
    """Consulta válida ou a pergunta original. Regras: 1 linha, ≤ 25
    palavras, sem padrão de resposta, sem código/markdown."""
    c = " ".join((consulta or "").split()).strip().strip('"`')
    if not c:
        return question
    if "\n" in consulta or "```" in consulta:
        c = c.splitlines()[0]
    palavras = len(c.split())
    if palavras > 25 or _RE_RESPOSTA.search(c):
        if log:
            log(f"⚠️ reformulação inválida ({palavras} palavras"
                f"{' , padrão de resposta' if _RE_RESPOSTA.search(c) else ''})"
                " — usando a pergunta original na busca", "busca")
        return question
    return c


def reformula(question: str, history) -> str:
    """Reescreve a pergunta como consulta de busca autossuficiente.

    A busca vetorial não vê o histórico: "por que me falou de crianças?" vira
    embedding de pronomes soltos. Aqui a pragmática é resolvida ANTES — a
    LLM condensa histórico + pergunta numa consulta com os termos concretos
    (spec em specs/reformulacao.md). Sem histórico, devolve a pergunta como
    está (nada a resolver). O embedding do BGE-M3 pondera fortemente os
    termos raros do texto: a consulta boa é a que carrega o termo de domínio
    certo, não a palavra final da frase do usuário.

    GUARDRAILS: histórico entra SÓ com mensagens do USUÁRIO (respostas do
    assistente viravam modelo de saída — o 7B devolvia "Claro! Vou criar…"
    como "consulta"); e a saída passa por _sanear_consulta.
    """
    if not history:
        return question
    hist_user = [m for m in history[-12:] if m.get("role") == "user"]
    if not hist_user:
        return question
    prompt = ChatPromptTemplate.from_messages([
        ("system", spec("reformulacao")),
        MessagesPlaceholder("history"),
        ("human", "{question}"),
    ])
    texto = (prompt | llm(temperature=0) | StrOutputParser()).invoke(
        {"question": question, "history": _history_messages(hist_user)})
    return _sanear_consulta(texto, question)


def _termos_busca(pergunta: str) -> str:
    """Termos da pergunta p/ o filtro full-text (MatchText casa TODOS os
    termos — o alvo são IDs/códigos/técnicos exatos).

    v2: inclui termos de 3 chars ("api", "net", "web" — caíam no filtro
    >3 e o full-text ficava cego ao ÚNICO termo compartilhado PT×EN) e
    descarta stopwords latinas ("cria"? não — mas "uma", "dos", "para"
    entopem a conjunção AND sem agregar)."""
    from .idioma import _STOPWORDS_LATIN
    limpos = [p.strip(".,;:!?\"'()[]{}").lower() for p in pergunta.split()]
    uteis = [t for t in limpos
             if len(t) >= 3 and len(t) < 40
             and not _STOPWORDS_LATIN.fullmatch(t)]
    return " ".join(uteis)


# índices full-text já criados (1x por coleção por processo)
_indices_texto: set[str] = set()


def _busca_lexical(client, colecao: str, termos: str, limite: int = 40) -> list:
    """Busca full-text do Qdrant no `page_content` (payload que já existe —
    SEM reingestão). O índice é criado LAZY (tentativa única por coleção;
    MatchText funciona SEM índice por full-scan, o índice é velocidade).
    O scroll NÃO é ranqueado: a ordem entra só como rank da fusão RRF."""
    from langchain_core.documents import Document as _Doc
    from qdrant_client.models import FieldCondition, Filter, MatchText
    if colecao not in _indices_texto:
        try:
            client.create_payload_index(collection_name=colecao,
                                        field_name="page_content",
                                        field_schema="text")
        except Exception:
            pass  # já existe ou versão sem suporte — o full-scan segue valendo
        _indices_texto.add(colecao)
    pontos, _ = client.scroll(
        collection_name=colecao,
        scroll_filter=Filter(must=[FieldCondition(
            key="page_content", match=MatchText(text=termos))]),
        limit=limite, with_payload=True)
    docs = []
    for p in pontos:
        payload = p.payload or {}
        texto = str(payload.get("page_content") or "")
        if not texto:
            continue
        docs.append(_Doc(page_content=texto,
                         metadata=dict(payload.get("metadata") or {})))
    return docs


def _chave_dedupe(texto: str) -> str:
    """md5 do conteúdo normalizado — chave do dedupe global E da fusão RRF
    (o mesmo chunk achado pelas duas buscas soma os dois sinais)."""
    import hashlib
    return hashlib.md5(re.sub(r"\s+", " ", texto).strip()
                       .encode("utf-8")).hexdigest()


def search(client, collections, question: str, k: int | None = None,
           log=None):
    """Busca HÍBRIDA ampla em várias coleções (F2-6): densa (embedding, k*3
    candidatos) + full-text (MatchText, limit 40) fundidas por RRF.

    `log(msg, etapa)` (opcional) narra CADA consulta ao Qdrant e o que
    voltou (densos/lexicais/escolhidos + top resultados) — o raciocínio do
    chat mostra a conversa inteira com a base, linha por linha.

    A fusão RRF (Reciprocal Rank Fusion) soma 1/(60+rank) de cada lista por
    chave de conteúdo: quem aparece bem nas DUAS fica no topo; achados
    SÓ-TEXTO entram mesmo sem score denso — match exato de ID/código é
    sinal forte que o embedding dilui. Cada coleção segue contribuindo com
    até k pedaços DIVERSIFICADOS (máximo 2 por arquivo de origem).

    Retorna ([ (documento, score, colecao_de_origem) ], {colecao: erro}).
    Coleções com problema (inexistentes, dimensão errada) não derrubam a
    busca. O total é limitado a k x 4 (no máximo 4x TOP_K) para caber no
    contexto da LLM. Documentos densos com score abaixo de SCORE_MIN (.env)
    são descartados; só-texto entram com score = SCORE_MIN (não há similaridade
    semântica medida — o sinal deles é lexical).
    """
    k = k or config.TOP_K
    achados, erros = [], {}
    vistos: set[str] = set()  # dedupe GLOBAL: mesmo conteúdo em coleções
    _log = log or (lambda *a, **kwa: None)  # sem log → no-op (CLI/scripts)
    for nome in collections:
        _log(f"🗄️ qdrant → {nome}: consulta densa (top {k * 3}) + "
             "full-text…", "busca")
        try:
            densos = vectorstore(client, nome).similarity_search_with_score(
                question, k=k * 3)
        except Exception as e:
            erros[nome] = str(e)[:120]
            _log(f"🗄️ qdrant ✕ {nome}: {erros[nome]}", "busca")
            continue
        # lexical: mesma pergunta, filtro full-text (termos >3 chars); se a
        # frase completa não acha nada, cai para o termo mais longo
        termos = _termos_busca(question)
        lexicos = []
        if termos:
            try:
                lexicos = _busca_lexical(client, nome, termos)
                if not lexicos and " " in termos:
                    lexicos = _busca_lexical(
                        client, nome, max(termos.split(), key=len))
            except Exception:
                lexicos = []
        # fusão RRF por chave de conteúdo: rank denso (já vem ordenado) +
        # rank textual (ordem do scroll); a soma ordena os candidatos
        rrf: dict[str, float] = {}
        for r, (d, _s) in enumerate(densos):
            c = _chave_dedupe(d.page_content)
            rrf[c] = rrf.get(c, 0.0) + 1.0 / (60 + r + 1)
        for r, d in enumerate(lexicos):
            c = _chave_dedupe(d.page_content)
            rrf[c] = rrf.get(c, 0.0) + 1.0 / (60 + r + 1)
        unificados: dict[str, tuple] = {}
        for d, score in densos:
            unificados.setdefault(_chave_dedupe(d.page_content), (d, float(score)))
        for d in lexicos:  # só-texto: entram mesmo sem score denso
            unificados.setdefault(_chave_dedupe(d.page_content), (d, None))
        ordenados = sorted(unificados.items(),
                           key=lambda kv: rrf.get(kv[0], 0.0), reverse=True)
        escolhidos, por_arquivo = [], {}
        for chave, (d, score) in ordenados:
            if score is not None and score < config.SCORE_MIN:
                continue
            # por NOME do arquivo (não pelo caminho completo): o mesmo
            # arquivo ingerido duas vezes com grafias diferentes de
            # caminho (relativo/absoluto) é o MESMO arquivo
            origem = (str(d.metadata.get("source", "?"))
                      .replace("\\", "/").rsplit("/", 1)[-1])
            if por_arquivo.get(origem, 0) >= 2:  # já pegou 2 deste arquivo
                continue                          # → amplia para outros
            if chave in vistos:
                continue  # duplicado exato (outra coleção): 1ª ocorrência fica
            vistos.add(chave)
            por_arquivo[origem] = por_arquivo.get(origem, 0) + 1
            d.metadata["colecao"] = nome  # origem visível no prompt
            escolhidos.append((d, score if score is not None
                               else round(config.SCORE_MIN, 4), nome,
                              rrf.get(chave, 0.0)))
            if len(escolhidos) >= k:
                break
        # RETORNO do qdrant narrado: quantos vieram de cada lado da busca
        # híbrida, quantos sobreviveram ao filtro de score/dedup e os
        # melhores (score + arquivo) — limpo e legível no raciocínio
        _log(f"🗄️ qdrant ← {nome}: {len(densos)} denso(s) + "
             f"{len(lexicos)} textual(is) → {len(escolhidos)} escolhido(s)"
             + (f" (descartados: {len(ordenados) - len(escolhidos)})"
                if len(ordenados) > len(escolhidos) else ""), "busca")
        for d, s, _c, _r in escolhidos[:3]:
            _arq = (str(d.metadata.get("source")
                         or d.metadata.get("arquivo")
                         or d.metadata.get("titulo") or "?")
                    .replace("\\", "/").rsplit("/", 1)[-1])
            _log(f"   ↳ {s:.3f} · {_arq}"
                 + (f" · {str(d.page_content)[:160]}…" if d.page_content else ""),
                 "busca")
        if not escolhidos:
            _log(f"   ↳ nada acima do corte (score ≥ {config.SCORE_MIN})",
                 "busca")
        achados += escolhidos
    # ordem final = RRF (a fusão manda, não o score bruto de similaridade)
    achados.sort(key=lambda t: t[3], reverse=True)
    achados = achados[: k * min(len(collections), 4)]
    return [(d, s, c) for d, s, c, _ in achados], erros


def answer_stream(question, docs, history=None, bases=None):
    """Resposta em streaming (usada pelo CLI)."""
    chain = build_prompt() | llm() | StrOutputParser()
    return chain.stream({"system_text": _system_text("chat"),
                         "context": _ctx_com_guarda(
                             _contexto_com_bases(bases, format_docs(docs)),
                             question, docs),
                         "question": question, "history": _history_messages(history)})


# ---------- Tarefas auxiliares da LLM (categorizar / analisar) ----------

def _extract_json(texto: str) -> dict:
    """Extrai o primeiro objeto JSON da resposta da LLM (tolerante a cercas)."""
    try:
        return json.loads(texto[texto.index("{"): texto.rindex("}") + 1])
    except Exception:
        return {}


def _ask_json(nome_spec: str, conteudo: str) -> dict:
    """Pergunta algo à LLM seguindo uma spec e espera JSON de volta.

    Toda a instrução de formato/comportamento vive na spec — o código só
    entrega o conteúdo (definição do projeto: nada de prompt hardcoded).
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", "{spec}"),
        ("human", "{conteudo}"),
    ])
    texto = (prompt | llm() | StrOutputParser()).invoke(
        {"spec": spec(nome_spec), "conteudo": conteudo})
    return _extract_json(texto)


def categorize(amostra: str, origem: str = "") -> dict:
    """Categoriza um documento: {area, categoria, descricao} em português (via LLM).

    `area` é o domínio controlado (tecnologia, medicina, psicologia…) definido
    em specs/categorizacao.md; `categoria` é o tema específico.
    """
    conteudo = f"Arquivo: {origem}\n\nAmostra:\n{amostra[:1200]}"
    r = _ask_json("categorizacao", conteudo)
    return {
        "area": str(r.get("area") or "indeterminado"),
        "categoria": str(r.get("categoria") or "sem_categoria"),
        "descricao": str(r.get("descricao") or ""),
    }


def analyze_collection(nome: str, amostras: list[str]) -> dict:
    """Analisa uma coleção: {area, categoria, descricao, resumo} em PT (via LLM)."""
    if amostras:
        conteudo = f"Coleção: {nome}\n\nAmostras:\n" + "\n---\n".join(amostras)
    else:
        conteudo = f"Coleção: {nome}\n\n(sem amostras — coleção vazia)"
    r = _ask_json("analise_colecoes", conteudo)
    return {
        "area": str(r.get("area") or "indeterminado"),
        "categoria": str(r.get("categoria") or "indeterminado"),
        "descricao": str(r.get("descricao") or ""),
        "resumo": str(r.get("resumo") or ""),
    }
