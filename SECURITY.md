# Política de segurança

## Visão geral / modelo de ameaça

O RagChat é um assistente **self-hosted** que roda LLM (local ou em endpoint
próprio) e guarda a base de conhecimento pessoal (biblioteca + Qdrant). A
superfície exposta é a **API web** (`:8001`) e, opcionalmente, **túneis** para
os endpoints de LLM do dono (estação/servidor próprio). Não há broker nem
serviço de terceiros obrigatório — jobs rodam no executor in-process.

## Autenticação e sessões

- Contas com hash **scrypt** (`users.json`, fora do git) — senha nunca fica
  em texto no disco.
- Tokens de sessão **HMAC-SHA256** assinados com `AUTH_SECRET` do `.env`
  (auto-gerado no primeiro boot), válidos por 30 dias, entregues no cookie
  `ragchat_token` (httpOnly, SameSite=Lax).
- Login com rate limit: **8 tentativas erradas por 5 min** (por IP+usuário).
- Registro de conta **só para nomes da allowlist** (`usuarios_permitidos.txt`)
  — quem não conhece um nome permitido não cadastra.
- Perfis isolam sessões/conversas por dono; operações de admin —
  configurações, modelos, instalação/registro de MCP — são exclusivas do
  perfil admin (`AUTH_ADMIN_USER`).

## Isolamento da sandbox

- Container próprio **sem portas publicadas** (só rede interna do compose),
  usuário **não-root**.
- Arquivos de teste **efêmeros** (`/tmp/work` — cada teste é autossuficiente).
- O preview público de arquivos do teste exige **token HMAC curto (15 min)**;
  apps web temporários sobem com **link temporário (~30 min)** — ambos
  expiram sozinhos, sem estado na borda.

## Ferramentas MCP (agente)

- Registro e instalação de servidores MCP são **admin-only**.
- **Toda execução de ferramenta no chat exige aprovação explícita do
  usuário**: permitir uma vez, permitir na sessão ou negar (ferramentas só
  de leitura/raciocínio passam sem portão).
- O env configurado por um servidor MCP **não pode gravar as chaves
  proibidas** (lista `_ENV_PROIBIDAS` em `api/base.py`: `AUTH_SECRET`,
  `AUTH_ADMIN_*`, `LLM_*`, `EMBED_*`, `QDRANT_URL`, `RAGAROY_CONTAINER`,
  `MODELS_DIR`, `LLAMA_BIN`, `SERPER_API_KEY`) — um instalador malicioso
  não sequestra a auth nem a infra.

## LLM e dados

- Modelos rodam no **hardware do dono** (estação/servidor próprio) — **nada
  sai por padrão**; a API alcança o llama-server por rede local ou túnel.
- Provedores cloud são **opcionais** e configurados por `.env`
  (`PROV_<id>_BASE_URL` + `_API_KEY`); chaves aparecem **mascaradas** na UI
  e nunca são regravadas pelo painel.
- O embedding é **sempre local (bge-m3)** — a base mantém a dimensão (1024)
  das coleções no Qdrant.

## Segredos e o que NUNCA commitar

`.env`, `users.json`, `sessions/`, `saidas/`, `logs/`, `datasets/`,
`qdrant_data/`, `hf_cache/`, `deploy/`, `docs/`, `scripts/`, `tests_manual/`,
`Temp/`, `AGENTS-historico.md` — estado local, dados pessoais e segredos,
todos no `.gitignore`. O CI usa apenas secrets do GitHub. **Regra: novo
arquivo de estado entra no `.gitignore` na mesma PR.**

## Superfície de API

OpenAPI interativo em **`/docs`** (atrás do login, como qualquer página).
Jobs longos (ingestão, pesquisa, sandbox…) retornam um **id** e são
consultados por `/status/{job}` — **sem callback externo**.

## Divulgação responsável

Achou uma vulnerabilidade? **Não abra issue pública** com detalhes
exploráveis. Use **GitHub → Security → "Report a vulnerability"** ou
contate o mantenedor diretamente, informando versão/commit e passos de
reprodução. O relato é confirmado o quanto antes e a correção priorizada
pela severidade; coordinated disclosure quando houver fix em andamento.

**No escopo**: falhas de autenticação/sessão, escape da sandbox, bypass da
aprovação de ferramentas MCP, exposição de segredos, XSS/CSRF na webui.

**Fora do escopo**: DoS, dependência desatualizada sem POC de exploração,
engenharia social, problemas da infra própria do dono (túneis/DNS mal
configurados) e versões antigas já corrigidas.
