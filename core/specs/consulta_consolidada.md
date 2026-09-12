# Especificação da CONSULTA CONSOLIDADA (admin define, chat/API consomem)

Pedido do dono 11/09 ("quero que remova do chat qualquer informação sobre
coleções ou mcps… será global, definido na administração… todas as
configurações devem ficar apenas no .env… no chat ou na API openai, ela irá
somente receber informações já consolidadas"): o chat (webui) e a API
compatível OpenAI (/v1) não escolhem nem exibem escopo — a consulta inteira
nasce da configuração da administração (Sistema → 🎯 Consulta), persistida
SOMENTE no .env.

## Regras

1. FONTE ÚNICA: `RAG_ATIVO`, `LLM_ATIVO`, `RAG_COLECOES`, `MCP_ATIVOS` no
   .env (grupo "Consulta"), gravados pelo cartão 🎯 Consulta do /sistema.
   Nunca entram no `environment:` do compose (o .env precisa vencer).
   Gravação aplica na hora (`set_env_inplace` + `reload()`, sem restart).
2. MODO EFETIVO deriva dos toggles: ambos ligados → **híbrido**; só RAG →
   **rag** (digest da spec rag_puro.md, zero LLM); só LLM → **livre**
   (sem busca na base); nenhum → erro claro (MSG_INDISPONIVEL abaixo).
   O modo `auto` deixa de ser alcançável por seleção.
3. ESCOPO EFETIVO: `RAG_COLECOES` (CSV); vazio = TODAS as visíveis
   (`_scan_collections`); coleção morta sai do escopo em silêncio (regra
   vigente).
4. MCPs EFETIVOS: `MCP_ATIVOS` ∩ servidores registrados (ausente é
   logada e sai); o pseudo-MCP **pesquisa-web** só participa se LISTADO —
   o auto-detector de intenção ("pesquise na web…") deixa de surpreender:
   só dispara quando pesquisa-web ∈ MCP_ATIVOS. MCPs REAIS exigem LLM
   (ReAct usa o modelo): com LLM_ATIVO=0 são pulados com aviso no
   raciocínio.
5. PAYLOAD NÃO MANDA: `/api/query` e `/hx/chat` aceitam
   `mode/model/collection(s)/mcps` por compatibilidade e os IGNORAM — a
   primeira linha do raciocínio registra a config que vale.
6. CHAT LIMPO: sem nomes de coleções e sem menção a MCPs na webui e nas
   respostas; fontes/arquivos/trechos CONTINUAM visíveis (decisão do dono).
   Internamente os docs seguem carregando `colecao` (ensinar a base,
   título semântico) — a remoção é só de EXIBIÇÃO.
7. MOCK_LLM precede os toggles (função dele é validar a UI com a máquina
   toda desligada).
8. API COMPATÍVEL OPENAI (`POST /v1/chat/completions`, `GET /v1/models`):
   última mensagem `user` vira a pergunta, as anteriores o histórico;
   resposta no shape OpenAI (`choices[].message`, `usage`) com `citations`
   (fontes SEM coleção) como campo extra; `model`/`temperature` aceitos e
   ignorados; `stream:true` devolve SSE fatiando a resposta final
   (`chat.completion.chunk` + `[DONE]`); erros no shape
   `{"error":{message,type,code}}`; autenticação = mesmo Bearer do login
   (401 JSON, nunca redirect).
9. BÚSSOLA segue rodando em modo livre (memória de conversa, não consulta
   à base — coleção de sistema, não exposta).
10. Papéis distintos de "desligar": markers `*_off.marker` = ciclo FÍSICO
    de GPU (cartão 🧠 Motor); `LLM_ATIVO`/`RAG_ATIVO` = switch LÓGICO da
    consulta (cartão 🎯). `garantir_llm` não religa o que a config desligou.

## Palavras usadas pelo código

(O código lê estas linhas; editar aqui muda o texto exibido sem rebuild.
"\n" na linha vira quebra de texto.)

MSG_INDISPONIVEL: ⚠️ **Consulta indisponível** — RAG e LLM estão desligados na configuração.\n\nA administração decide isto em **Sistema → 🎯 Consulta**: ligue o RAG (respostas pela base), a LLM (conversa) ou ambos (híbrido).
MSG_MCP_SEM_LLM: 🔌 ferramentas MCP exigem a LLM (loop de raciocínio) — LLM desligada na configuração, MCPs pulados nesta resposta.
