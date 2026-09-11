# AGENTS.md — rag-chat (RagChat)

RAG local (LangChain + Qdrant + llama.cpp) com chat agêntico MCP — **fork
100% texto do rag-llama (RagAroy)**: sem geração/edição de mídia, sem
análise de imagem (i2t), sem voz (STT/TTS). Mantém: chat + RAG/Qdrant +
biblioteca + MCP/pesquisa web + sandbox de código. Projeto **completo e
funcional**; este arquivo captura o contexto de como operá-lo e
modificá-lo sem quebrar nada.

---

## ⚠️ 0. REGRA INEGOCIÁVEL — COMMIT AO TERMINAR

**Este fork NASCEU sem remote** (clone local do rag-llama com
`git remote remove origin`): o trabalho versiona por COMMIT LOCAL —
nada de push enquanto o dono não criar um repo próprio.

**Todo trabalho que altera arquivos DEVE terminar com:**

```powershell
git status --short          # verificar o que mudou
git add -A
git commit -m "feat|fix|docs|refactor: <o que foi feito e por quê>"
```

Regras:
- Arquivos de estado/dados (logs/, sessions/, saidas/, users.json,
  qdrant_data/, hf_cache/, .env) são gitignored — NÃO commitar.
- **`.env` contém segredos reais** (SERPER_API_KEY, AUTH_ADMIN_PASS,
  LLM_API_KEY, AGENTE_TOKEN, SANDBOX_TOKEN) — NUNCA commitar/pushar.
- Branch de trabalho: **develop**.

---

## 1. Stack e ambiente

### 🏭 ONDE RODA O QUÊ — política fixa do dono

**A GPU é SEMPRE a ESTAÇÃO do dono** (a máquina local). O servidor NÃO
hospeda llama: nenhum llama-server, nenhum GGUF — os modelos de
conversa/embedding rodam na estação e a produção os alcança pelos túneis
(`llm.disroy.org` :8090 · `embed.disroy.org` :8081 ·
`agente.disroy.org` :8010). No servidor vivem SÓ os serviços de
aplicação: `api` (FastAPI+webui), `sandbox` (teste de código),
`traefik`/`cloudflared`.

### ⚠️ QDRANT COMPARTILHADO (decisão do fork)

O fork **usa a MESMA instância Qdrant do rag-llama**
(`http://localhost:6333`, dados em `rag-llama/qdrant_data`) — nenhum
qdrant no compose do fork. As coleções EXISTENTES aparecem sozinhas no
seletor (`_scan_collections` é 100% dinâmico). Consequências:

- `EMBED_MODEL` **tem que continuar bge-m3** (1024 dims — a dimensão
  das coleções existentes; trocar exige reingestão total).
- `COLECOES_SISTEMA` (api/base.py) mantém `midia_gerada`/`prompts_midia`
  escondidas — as coleções existem fisicamente no Qdrant compartilhado
  (são do RagAroy) e NÃO devem aparecer no seletor do fork.
- `core/preview.py` NÃO mexer: esconde as mesmas coleções do Qdrant
  compartilhado.

### Serviços externos

| Serviço | Onde | Porta | Notas |
|---|---|---|---|
| Qdrant | instância do rag-llama | :6333 API / :6334 dashboard | compartilhado — fork não sobe o seu |
| llama-server chat | `<pasta-do-usuario>\llama.cpp\bin` | :8090 | 2 slots: `-c 32768 -np 2 -fa on -ctk/-ctv q8_0` |
| llama-server embedding (bge-m3) | idem | :8081 | **SEMPRE ligado** — nada pode derrubá-lo |
| agente do host | `python -X utf8 -m api.agente_host` | :8010 | ergue chat+embed no BOOT; operações de GPU |
| sandbox | container `ragchat-sandbox` | rede interna | teste de código do chat |

GGUFs dos modelos ficam em `D:\models` (presets em `core/config.py`:
`MODELOS`/`EMBEDDINGS`). O fork serve SÓ chat (:8090) e embedding
(:8081) — GGUFs de difusão/visão que existam em `D:\models` são
classificados pelos `PADROES` de `core/modelos.py` apenas para NÃO
aparecer como opção de conversa.

### VRAM (8 GB)

Um modelo de conversa por vez + o embedding. `servicos_llm.py` já
reinicia tudo ao trocar de modelo; a troca pela webui (`modelos.ativar`)
espera `VRAM_ASSENTAMENTO_S` (constante em `core/config.py`) pela VRAM
liberar antes de subir o novo.

### Cookies e portas (isolamento do ORIG)

O fork roda na **porta 8001** (o rag-llama na 8000). Cookies RENOMEADOS
porque cookie ignora porta: `ragchat_token` (login) e `rc_sessao`
(sessão do chat). Os dois apps rodam SIMULTÂNEOS sem se pisar.

- **OS:** Windows, shell **PowerShell 5.1** (sem `&&` — usar `;`) ou bash.
- **Python:** venv em `.venv/`; requisitos com pins em
  `requirements.txt` (LangChain 1.x — o código já usa a API nova).
- **Codificação:** sempre `python -X utf8` ao rodar scripts que imprimem
  acentos/emoji no console.

## 2. Comandos

```powershell
# subir a API em modo host (desenvolvimento na estação)
python -X utf8 -m uvicorn api.app:app --host 0.0.0.0 --port 8001

# operar por container (compose sobe api :8001 + sandbox)
docker compose up -d --build

# subir/gerenciar os modelos (menu; atualiza LLM_MODEL no .env)
python servicos_llm.py

# testes
python -m pytest tests -q

# CLI: ingestão e consulta
python -X utf8 -m core.ingest caminho\da\pasta
python -X utf8 -m core.main

# CLI: coleção nova por assunto (seed profundo)
python -X utf8 -m core.seed "assunto" --fontes 12

# varredura LLM das coleções (apaga lixo claro apontado pelo modelo)
python -X utf8 -m core.varredura <colecao> [outra...]

# REPARO: vetores zerados após crash do Docker (buscas score 0.0)
python -X utf8 -m core.reembed [colecao ...]   # sem args: todas

# AGENTE DO HOST (obrigatório junto com o container): ergue o chat+embed
# no BOOT e atende as operações de GPU da API-container (:8010)
python -X utf8 -m api.agente_host
```

## 3. Arquitetura — 2 subsistemas

### Núcleo RAG

| Módulo | Papel |
|---|---|
| `core/config` | `.env` + `reload()` em runtime (a webui edita e aplica sem restart); binário local (LLAMA_BIN) ajustável no .env; `VRAM_ASSENTAMENTO_S` constante |
| `core/contadores` | 📊 uso de tokens do llama-server (:8090): wrapper em `rag.llm()` conta CADA chamada por serviço via thread-local; acumula em `logs/uso_llm.jsonl` (append atômico); `totais()` agrega com cache 3 s; `/api/contagem` e `tokens` nas respostas |
| `core/auth` | login scrypt+salt em `users.json` (FORA do git), tokens HMAC stateless; bootstrap do admin via AUTH_ADMIN_* do .env; owner isola sessões por conta |
| `core/rag` | embedding/Qdrant/LLM/chain; modos rag/livre/híbrido; `search` multi-coleção com `SCORE_MIN`, máx 2 chunks/arquivo e teto 4×TOP_K; `reformula` a pergunta usando o histórico |
| `core/ingest` | wizard de 7 etapas; `rapido=True` pula LLM; texto LIMPO (`core/limpeza`), split por seções markdown, chunks com cabeçalho contextual e metadata; descarta ruído e duplicados |
| `core/limpeza` | limpeza de texto + `e_lixo()` (heurística de chunk sem semântica) |
| `core/higieniza` | limpa coleções JÁ GRAVADAS in-place: re-embeda o texto limpo no mesmo id, apaga ruído e duplicados |
| `core/catalog` | metadados das coleções na coleção `meta_colecoes` + `agrupar()` |
| `core/analyze` | LLM analisa todas as coleções → catálogo |
| `core/enrich` | destrincha coleção em várias por tema (reaproveita vetores) |
| `core/sessions` | sessões do CHAT (JSON em `sessions/`) |
| `core/executor` | ⚙️ executor de JOBS async in-process: fila `asyncio.Queue` serial, fábricas em `to_thread`, retry+backoff SÓ p/ transientes; restart = jobs somem com erro claro no polling |
| `core/seed` | seed PROFUNDO seguindo a spec `pesquisa_web.md` |
| `core/varredura` | varredura LLM: julga cada chunk contra o ASSUNTO da coleção |
| `core/unificar_arquiteturas` | consolida chunks por CONCEITO na `arquitetura_unificada` (oculta, entra automática em buscas `arquitetura_*`) |
| `core/specs` | carrega `core/specs/*.md` com `lru_cache` |
| `core/provedores` | provedores externos OpenAI-compatible (PROV_* no .env, auto-descobertos) |
| `core/modelos` | troca a quente de GGUF; grava `LLM_MODEL` no .env + `config.reload()` |

### Chat agêntico

| Módulo | Papel |
|---|---|
| `core/agent` | ReAct artesanal; portão de aprovação (`pendente` + `uma_vez`\|`sessao`\|`negar`); verificação anti-invenção |
| `core/mcp_registry` | registro de servidores MCP (`mcp_servers.json`) + catálogo de conhecidos (`mcp_conhecidos.json`) com instalação automática |
| `core/auto` | modo Auto: roteador decide base/web/livre; web-first com aprofundamento de até 5 níveis |
| `core/bussola` | 🧭 coleção `sessoes_chat` indexa (pergunta→resposta) por owner — resposta direta ≥0.95, sugestão 0.85–0.95 |
| `core/pesquisa` | 🔬 pesquisa profunda com evidências (planner → busca → páginas inteiras → claims → síntese com citações → modo revisão) |
| `core/rerank` | 🎛️ CrossEncoder bge-reranker-base em CPU, LAZY; rerank do chat e gate de tema da Revisão |
| `core/sandbox` | ▶ testar código em container isolado (multi-linguagem, deps auto, entry automático, site com link temporário) |

## 4. Regras de comportamento = specs (regra de ouro)

**Toda comunicação com a LLM é via RAG**: comportamento e formato vivem em
`core/specs/*.md` ou no conteúdo do Qdrant; o código só monta o envelope
(dados + `ETAPA: x`) — nada de instrução hardcoded. Coleções são sempre
genéricas: nenhum texto do sistema cita coleção específica. Para mudar
comportamento → editar a spec. `core/specs.py` usa `lru_cache`: **editar
spec exige restart da API**.

## 5. Armadilhas

- PowerShell 5.1: sem `&&` (usar `;`); `curl` pede senha → usar
  `Invoke-RestMethod`.
- **MODO CONTAINER** (`RAGAROY_CONTAINER=1` no compose): endpoints de
  infra (Qdrant/LLM/Embed) vêm do ENVIRONMENT e o `.env` montado NÃO os
  sobrescreve (`load_dotenv(override=False)`). `embedding_no_ar()` usa
  `EMBED_BASE_URL` — NUNCA hardcode 127.0.0.1 (o container testaria a
  si mesmo). Rebuild: `docker compose up -d --build`.
- **Coleções de sistema** (`COLECOES_SISTEMA` em `api/base.py`):
  `meta_colecoes`, `midia_gerada`, `prompts_midia` e
  `arquitetura_unificada` são FUNCIONAIS mas OCULTAS da webui — as duas
  de mídia pertencem ao Qdrant COMPARTILHADO (RagAroy): manter escondidas.
- **Auth**: `users.json` e `.env` (AUTH_ADMIN_PASS/AUTH_SECRET) NUNCA no
  git. Tokens são HMAC — AUTH_SECRET novo derruba todos os logins. Cookie
  do login = `ragchat_token`; sessão do chat = `rc_sessao` (renomeados
  no fork para não colidir com o rag-llama no mesmo localhost).
- Ingerir a mesma pasta **duplica** chunks — para coleções antigas, rode
  a **higienização**. Recomeçar do zero: apague a coleção no dashboard
  do Qdrant (:6333).
- Embedding de dimensão diferente de bge-m3 (1024) exige **reingestão total**.
- **Chat é JOB**: a webui chama `/api/query` com `job=true` (imune ao
  524 do Cloudflare) e faz polling em `/api/query/status/{job}`; cada
  etapa vira linha em tempo real no "pensando…". CLI/tests usam a rota
  síncrona (sem job).
- **Jobs no EXECUTOR ASYNC**: fila SERIAL (1 job por vez), fábrica em
  `asyncio.to_thread`, RETRY com backoff SÓ para transientes. A entrada
  de status é criada ANTES do return. `_podar_concluidos(dic)` exige
  lock segurado (Lock não é reentrante). Restart da API: jobs somem com
  ERRO CLARO "dispare novamente". `to_thread` reusa threads:
  thread-local (rag.set_override, contadores) exige `finally`.
- **MCP é admin-only**: registrar/testar/instalar/remover executa
  processos no host → `_exigir_admin` em todas as rotas de escrita.
- **Settings valida tipos ANTES de gravar** (422) e **mascara segredos**.
- **Sessões**: id validado por regex (`_RE_SID`, anti path-traversal) e
  DELETE/PATCH conferem owner.
- **`set_env_inplace`** (config.py): gravar no .env SEM rename — bind
  mount de ARQUIVO único no Docker rejeita `os.replace`. Também atualiza
  `os.environ` (reload usa override=False).
- **Qdrant × crash do Docker Desktop**: o crash pode ZERAR os vetores em
  disco (buscas voltam score 0.0 para tudo). Remédio:
  `python -X utf8 -m core.reembed [coleções]` — idempotente.
- **Operação pela API = CONTAINER** JUNTO ao **AGENTE DO HOST**
  (`python -X utf8 -m api.agente_host`, :8010): ergue chat+embedding no
  BOOT e recebe da API-container as operações de GPU
  (`modelos.ativar`/`garantir_embedding` proxyam via AGENTE_HOST_URL).
  ⚠️ Agente da estação roda o CÓDIGO LOCAL: mudou agente_host.py →
  restart do processo (o deploy não o atualiza).
- **Desligar embedding/llama (manual)**: badges 🧬/🧠 → `POST
  /api/embed/{ligar,desligar}` e `/api/llm/{ligar,desligar}` (admin; em
  container, proxy ao agente). Estado = MARKER (`saidas/{embed,llm}_off.
  marker`) que `garantir_embedding()`/boot respeitam — desligado fica
  desligado até o ▶.
- **Busca HÍBRIDA**: `rag.search` funde densa + full-text do Qdrant por
  **RRF**; índice full-text criado LAZY. A ordem final é do RRF.
- **Reranker**: CrossEncoder em CPU, LAZY (~1,1 GB no cache HF). Flag
  `RERANKER` no .env; DEGRADA em silêncio se torch ausente.
- **👁️ MODO REVISÃO**: dry-run da ingestão — NADA grava sem aprovação
  (`core/preview.py` + revisão na Biblioteca).
- **🧭 BUSSOLA PRÉ-TOKEN**: coleção `sessoes_chat` (escopo por owner);
  ≥0.95 → resposta direta reaproveitada (zero token). O modo livre tem
  early-return próprio — o `bussola.registrar` precisa existir LÁ TAMBÉM.
- **Cache semântico REMOVIDO** (decisão do dono): a bússola cobre
  perguntas repetidas cross-sessão.
- **`/api/ingest/upload`**: `colecao`/`rapido` são `Form()` — sem a
  anotação o FastAPI lia da QUERY. Escrita em `asyncio.to_thread`.
- **Pensamentos do chat**: linhas do "pensando…" ANEXADAS à mensagem
  (`pensamentos`); ao vivo grupos concluídos retraem sozinhos. A sessão
  é salva JÁ NO ENVIO; o job ativo fica no localStorage (`ragchat.chatJob`)
  — sair/recarregar no meio RETOMA o polling ao voltar.
- **Painel de código**: arquivos acumulados de TODAS as respostas
  (última versão vence); `/api/zip` preserva a estrutura de pastas.
- **Telemetria persistente** (`core/telemetria.py` →
  `logs/telemetria.jsonl`): cada chamada LLM e cada job.
- **Tokens em tempo real**: `contadores.set_log` (thread-local) loga
  `🪙 🔻in · 🔺out` a CADA chamada com a ETIQUETA da etapa.
- **Histórico de jobs** (`core/historico.py` → `logs/historico.jsonl`):
  TODO job de fila registra tipo/duração/ok/resumo ao terminar — o
  embrulho é na FÁBRICA.
- **Interrupção**: novo envio com job "pensando" → `POST
  /api/query/cancel/{job}` cancela no servidor (resultado tardio é
  descartado) e o card sai da tela; a pergunta interrompida JÁ está na
  sessão (entra no history do novo POST).
- **htmx**: NUNCA mutar inputs do form no listener de `submit` (o htmx
  captura os parâmetros ENTRE submit e configRequest) — mutar só em
  `beforeRequest`. Flag de in-flight só sobe DENTRO do `beforeRequest`,
  DEPOIS do check (senão cancela o próprio pedido). Guard de vazio com
  `preventDefault()` no submit (NUNCA `required` + limpeza no ato).
- **jinja NUNCA no JS cru**: `{{ x | tojson }}` quebra teste de sintaxe
  — usar data-attribute + `JSON.parse`.
- **NUNCA editar template pelo PowerShell** (PS 5.1 regrava cp1252 e
  corrompia UTF-8) — edits de arquivo em Python ou ferramenta própria.
- **Sandbox**: ▶ do card testa SÓ os arquivos daquele retorno (painel =
  conversa inteira); deps que o código importa são instaladas; entry
  point escolhido automaticamente (`escolher_principal`); app web ganha
  link temporário (~30 min, HMAC). Nome do arquivo usa a DICA da prosa
  (`_nomesCitados`) — nunca diverge do sugerido no chat.
- **Deploy VPS é SEMPRE pelo CI** (quando o fork ganhar repo próprio):
  `docker compose up` MANUAL sem o override da infra derruba o Traefik
  → 502. O 502 do Cloudflare por ~20 s durante deploy = janela normal.

## 6. Estado e decisões históricas

- **Fork (10/09/2026)**: nasceu do rag-llama (RagAroy) em
  `C:\Users\rodne\projetosia\rag-chat` — commit único de strip removeu
  i2t/t2i/t2v/estúdio/voz; o histórico git COMPLETO do RagAroy segue no
  clone (até o commit de strip). Qdrant compartilhado com o ORIG
  (mesma instância :6333), cookies/porta renomeados para coexistir.
- Análises vivas do código (herdadas, ainda válidas para o núcleo RAG):
  `docs/core-analise.md` · `docs/guia-conceitos-rag.md` ·
  `docs/plano-qualidade-rag.md`. Atualizar esses docs ao mudar o que
  eles descrevem.
- Datasets: clones esparsos de fontes oficiais em `datasets/` (fora do
  git) + `datasets/seed/` (versionado).
- Git: `.env` NUNCA; `sessions/`, `saidas/`, `logs/` fora.
