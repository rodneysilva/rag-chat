<div align="center">

<img src="static/logo.svg" width="72" alt="RagChat"/>

# RagChat

**Assistente local com RAG: base de conhecimento própria, chat com fontes citadas e execução de código — LLM na sua GPU, custo zero por pergunta.**

[![Licença: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI multi-OS](https://img.shields.io/badge/CI-ubuntu%20%7C%20windows%20%7C%20macos-green.svg)](.github/workflows/ci-cd.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](requirements.txt)

[O que faz](#o-que-faz) · [Começo rápido](#começo-rápido) · [Specs](#specs--comportamento-em-markdown) · [API](#api) · [Arquitetura](#arquitetura) · [Documentação](#documentação)

</div>

---

## Visão geral

O RagChat converte sua base de conhecimento na memória de um modelo de
linguagem local: perguntas do seu domínio respondem por busca vetorial
com **citação das fontes**, sem custo por token. Provedores externos
(GLM, DeepSeek, OpenAI, Claude) operam como complemento pontual quando o
assunto está fora das coleções e das ferramentas MCP.

O projeto é **100% texto**: chat + RAG (Qdrant) + biblioteca +
MCP/pesquisa web + sandbox de código.

| | local (RagChat) | provedor externo |
|---|---|---|
| custo por pergunta | zero (GPU/CPU própria) | por token |
| latência | milissegundos | segundos |
| conhecimento | suas coleções (RAG) | treino do modelo + web |
| uso recomendado | domínio próprio, consultas repetidas, com fontes | o que não está nas bases nem nos MCPs |

## O que faz

**💬 Conversar com os documentos** — Ingestão por PDFs, pastas, datasets
HuggingFace e pesquisa web profunda, sempre em **modo Revisão** (nada
grava sem aprovação: chunks, duplicados, clusters e gate de tema). A
resposta cita trechos `[n]`; fragmento forte responde direto da base,
sem gastar LLM. Modos: `híbrido` (base + modelo), `rag` (só a base,
recusa honesta), `livre` e `auto` (roteador decide entre base e web).

**🧹 Base limpa por construção** — Cada chunk recebe um score de
qualidade 0–1 na ingestão (densidade de links, repetição, JSON cru,
tabelas sem prosa); abaixo de `SCORE_CHUNK_MIN` (.env) é rejeitado com
motivo no relatório. Coleções existentes têm higienização determinística
com backup reversível.

**🔌 Provedores externos** — Qualquer endpoint OpenAI-compatible entra
pelo `.env` (`PROV_<id>_BASE_URL` + `_API_KEY`) e aparece no seletor
com os modelos **reais** do provedor. Chaves mascaradas na UI.

**⚙️ Executar código** — Respostas com código viram projeto no painel;
▶ testar roda em container isolado (Python, Node, Java, .NET 8/10, Rust,
Ruby, PHP, Go, Dart), instala as dependências que o próprio código
importa e detecta o entry point. Sites Flask/FastAPI/ASP.NET sobem com
link temporário para navegar.

**📊 Observabilidade** — Dashboard por modelo (tokens, tok/s, chamadas),
infra Qdrant, histórico com log completo de cada job, telemetria
persistente.

## Começo rápido

Pré-requisitos: **Docker** + **Python 3.11+**. GPU opcional (~8 GB VRAM
recomendada). **Qdrant**: uma instância qualquer alcançável
(`QDRANT_URL` no `.env`) — o app não sobe a sua.

```bash
# 1) dependências
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2) configurar
cp .env.example .env        # preencha AUTH_ADMIN_* (login inicial) e QDRANT_URL

# 3) subir a API (compose sobe api :8001 + sandbox)
docker compose up -d --build
#    ou em modo host: python -X utf8 -m uvicorn api.app:app --port 8001

# 4) LLM + embedding — um dos dois caminhos:
#    a) llama-server na sua GPU:  python servicos_llm.py
#    b) qualquer endpoint OpenAI-compatible: LLM_BASE_URL/EMBED_BASE_URL no .env

# 5) abrir http://localhost:8001 e logar com o AUTH_ADMIN_* do .env
```

No Windows, `setup.ps1` faz os passos 1–3 em um comando.

<details>
<summary><b>Modelos recomendados</b> (um por tipo, em <code>~/models</code> ou <code>D:\models</code>)</summary>

| Tipo | Modelo | Tamanho |
|---|---|---|
| Conversa | [Qwen2.5-Coder-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF) Q4_K_M | 4,7 GB |
| Embedding | [bge-m3](https://huggingface.co/gpustack/bge-m3-GGUF) Q8 | 0,7 GB |

⚠️ Fixe o embedding em **bge-m3** (1024 dims) ao criar coleções: trocar
de embedding exige reingestão total da base.

</details>

<details>
<summary><b>Sem GPU local?</b></summary>

Aponte `LLM_BASE_URL`/`EMBED_BASE_URL` para qualquer endpoint
OpenAI-compatible (local via túnel ou provedor). Sem Docker no host, a
API roda com `uvicorn` — jobs no executor async embutido, contagem de
tokens em arquivo, nenhuma dependência extra.

</details>

<details>
<summary><b>Provedores externos (GLM, DeepSeek, OpenAI, Claude)</b></summary>

```env
# .env — o provedor aparece sozinho no seletor do chat (grupo 🌐)
PROV_GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
PROV_GLM_API_KEY=sk-...
PROV_DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
PROV_DEEPSEEK_API_KEY=sk-...
# lista manual de reserva (se o provedor não listar /models):
# PROV_ANTHROPIC_MODELOS=claude-sonnet-4-5,claude-haiku-4-5
```

Modelos vêm do `GET /models` (cache 5 min). A telemetria registra o
modelo real (`[glm] glm-4.6`). Chaves nunca aparecem na UI; o embedding
segue local (bge-m3) para a base não perder dimensão.

</details>

## Specs — comportamento em markdown

**Todo comportamento da LLM do RagChat vive em
[`core/specs/*.md`](core/specs), não no código.** O que o assistente
faz em cada etapa — como responde no modo RAG, como decide entre base e
web, como corta e classifica um documento na ingestão, como monta uma
coleção nova por assunto — é uma especificação em markdown que o código
apenas entrega ao modelo como instrução de sistema (o código monta só o
envelope: dados + `ETAPA: x`).

Como funciona o mecanismo:

- Cada etapa do pipeline carrega a sua spec por nome —
  `core/specs.py` lê o arquivo `.md` (com cache `lru_cache`) na hora de
  montar o prompt. `spec("chat")` governa o modo RAG,
  `spec("seed")` governa a criação de coleções, e assim por diante.
- **Editar a spec muda o comportamento sem tocar em código.** Depois da
  edição, `POST /api/specs/reload` derruba o cache e a nova spec vale na
  hora (ou restart da API).
- As specs também são **registradas no catálogo** (`meta_colecoes`, uma
  coleção própria do Qdrant, com embedding) — dá para perguntar no
  próprio chat *“como você decide entre base e web?”* e a resposta vem
  das specs, via RAG. O sistema documenta a si mesmo.

### Specs e a criação de coleções

As specs são o **ponto focal dos fluxos que criam e evoluem coleções**:
todo o caminho — do planejamento de fontes à classificação, passando
pela curadoria em modo Revisão — é governado por elas:

| Spec | Governa |
|---|---|
| `seed.md` | criar coleção nova por assunto: planeja as buscas, seleciona fontes, propõe a base |
| `base_conhecimento.md` | construir base curada em 5 passos |
| `ingestao.md` | pipeline de ingestão (extração → limpeza → chunks → gate) |
| `categorizacao.md` | classificar arquivos/coleções (área, categoria — registradas no catálogo) |
| `edicao_documentos.md` · `modelo_dados.md` | editar chunks / schema dos payloads no Qdrant |
| `analise_colecoes.md` · `agrupamento.md` · `rotulo_cluster.md` | manutenção: analisar, agrupar duplicados, rotular clusters |
| `destrinchar.md` | quebrar coleção grande em menores |

### Índice completo das specs

| Grupo | Specs |
|---|---|
| Conversa | `chat` (modo RAG estrito) · `hibrido` (base + tom executivo) · `geracao` · `geracao_codigo` (modo livre) · `roteador` (modo auto: base/web/livre) · `reformulacao` (reescreve a pergunta p/ busca) · `exibicao` · `lembrete_final` |
| Pesquisa | `pesquisa_planner` (plano) · `evidencia` (claims) · `sintese` (síntese citada) · `pesquisa_web` · `busca_neutra` |
| Agência | `ferramentas` — agente ReAct com MCP, portão de aprovação |
| Código na conversa | `analise_codigo` · `arquivo_codigo` · `painel_conversa` (painel 📄) |
| UX | `prompt_melhoria` — ✨ melhorar o prompt antes de enviar |

## API

A API REST do RagChat é **documentada no padrão OpenAPI**: espec
interativa completa em **`/docs`** (Swagger UI) — todos os endpoints,
modelos de entrada/saída e autenticação, prontos para testar no
navegador.

- **Autenticação**: `POST /api/auth/login` devolve o cookie de sessão
  `ragchat_token` (HMAC); todas as rotas `/api/*` o exigem. Contas vêm
  de uma allowlist (`usuarios_permitidos.txt`).
- **Tarefa longa é job**: a rota devolve `{job: id}` imediatamente e o
  andamento (logs ao vivo, resultado final) sai de
  `GET /api/<area>/status/{job}` — imune a timeout de proxy.
- **Modelos no protocolo OpenAI**: toda chamada de LLM/embedding usa o
  wire padrão (`/v1/chat/completions`, `/v1/models`, `/v1/embeddings`).
  Trocar o motor = apontar `LLM_BASE_URL`/`EMBED_BASE_URL` para
  qualquer endpoint OpenAI-compatible (llama.cpp, vLLM, provedor cloud)
  — zero mudança de código.

Superfície por domínio: `auth` (login/conta) · `chat` (consulta com
jobs, sessões) · `biblioteca` (ingestão, coleções, pesquisa, revisão,
curadoria, snapshots) · `sandbox` (execução de código) · `sistema`
(configurações, modelos, provedores) · `telemetria` (contadores,
histórico) · `agentico` (sessões MCP) · `jobs` (status das famílias de
job).

```bash
# exemplo: login + pergunta em modo job
curl -c jar -X POST http://localhost:8001/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"user": "voce", "senha": "..."}'
curl -b jar -X POST http://localhost:8001/api/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "o que diz a base sobre X?", "mode": "rag", "job": true}'
curl -b jar http://localhost:8001/api/query/status/<job>   # logs + resposta
```

## Arquitetura

```
┌─ estação com GPU (opcional) ─────────────┐   ┌─ host / servidor (docker compose) ───┐
│ llama-server  chat :8090 · embed :8081   │⇄⇄│ api :8000 (int)  FastAPI + webui HTMX │
│ (binário local em dev · containers GPU   │tú│ · composição + routers por domínio    │
│  na produção, via endpoint OpenAI-compat)│nel│ · executor async de jobs (in-proc)    │
└───────────────────────────────────────────┘   │ qdrant     instância externa :6333   │
                                                │ sandbox    execução isolada + sites   │
                                                └───────────────────────────────────────┘
```

- **Monólito modular em camadas** (SOLID/DDD/Clean): `api/app.py` é
  composição (~90 linhas); rotas em `api/routers/*` por domínio; domínio
  em `core/*`; contrato normativo em `docs/arquitetura.md` (interno).
- **Toda tarefa longa é job** no executor async in-process (fila serial,
  retry com backoff para transientes) — UI nunca bloqueia, **sem broker
  externo** (sem RabbitMQ/Redis).
- **A GPU é a máquina de quem opera** — o servidor não hospeda modelos
  de linguagem; sem GPU local, provedores cloud cobrem o chat e a base
  segue no Qdrant.
- **Comportamento vive em specs** ([`core/specs/*.md`](core/specs)):
  mudar como o assistente responde é editar markdown, não código.
- Produção recomendada: containers (api + sandbox) sem portas publicadas
  atrás de proxy reverso; LLM alcançado por HTTPS com API key.

## Documentação

| Documento | Conteúdo |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Memória operacional: stack, comandos, armadilhas, decisões |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Como contribuir (issues e PRs; mudança de comportamento = editar spec) |
| [`SECURITY.md`](SECURITY.md) | Política de segurança do projeto (auth, sandbox, MCP, segredos) |
| `docs/` | Análises internas (não versionadas — vivem na máquina de quem opera) |

## Projetos open source que o sustentam

[llama.cpp](https://github.com/ggml-org/llama.cpp) · [LangChain](https://github.com/langchain-ai/langchain) · [Qdrant](https://qdrant.tech) · [FastAPI](https://fastapi.tiangolo.com) · [HTMX](https://htmx.org) + [Tailwind](https://tailwindcss.com) · [Qwen2.5](https://github.com/QwenLM/Qwen2.5) · [bge-m3](https://huggingface.co/BAAI) · [Trafilatura](https://github.com/adbar/trafilatura) — licenças e lista completa em [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Segurança

Auth scrypt + tokens HMAC e rate limit de login; sandbox em container
isolado (não-root, sem portas); ferramenta MCP só executa com aprovação
explícita; segredos apenas no `.env` (gitignored). Detalhes em
[`SECURITY.md`](SECURITY.md).

---

## Licença

MIT — veja [LICENSE](LICENSE).
