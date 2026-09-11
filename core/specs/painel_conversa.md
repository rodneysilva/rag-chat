# Painel da Conversa (spec de produto — UI HTMX)

> Contrato do painel direito do chat. Não é prompt de LLM: documenta o
> comportamento implementado que o time (e o dono) espera ver funcionando.
> Regra do projeto: código > AGENTS > README > docs.

## Princípio

O painel é a **bancada de saídas** da conversa: tudo que a conversa produz
entra nele SOZINHO, sem o usuário caçar na página. Nada substitui nada —
itens ACUMULAM por conversa.

## Abas

| Aba | O que entra | Quando |
|---|---|---|
| 📄 arquivos | cada bloco de código/comando da resposta, como `arquivoN.linguagem`, com botão copiar | resposta CONCLUÍDA (streaming ao vivo não conta — o parcial re-renderiza) |
| 📚 fontes | docs citados (📚 do rodapé) e a resposta completa (▦) | ao clicar no rodapé/botão da mensagem |

- contadores `(N)` por aba; o
  clique em fontes/resposta TROCA para a aba 📚 (a filtragem é uma ÚNICA
  função `_irParaAba` — nunca fica inconsistente).
- trocar de conversa LIMPA e RECONSTRÓI as abas a partir das mensagens.
- **⚠️ serialização**: `data-fontes` usa aspas SIMPLES no HTML — o `tojson`
  do Jinja escapa `'` mas NÃO escapa `"`; com aspas duplas o JSON quebrava
  no primeiro `"` e o painel de fontes falhava em silêncio.

## Fontes: dados do embedding

Cada fonte exibe o que a recuperação realmente mediu:

- **score** de similaridade do embedding (bge-m3) — badge ⚡;
- **coleção** de origem e **categoria** do catálogo;
- **arquivo** de origem (`source`, basename) e **descrição/seção** quando
  existem nos metadados;
- o **conteúdo** do chunk (o texto que alimentou a resposta).

## Nome dos arquivos

O item da aba 📄 usa o NOME REAL quando o bloco dá pistas (comentário com
caminho `# src/app.py`, "arquivo: x", declaração `class/def/function` +
extensão da linguagem); sem pistas cai em `bloco.N.ext` — nunca genérico.

## Expansão

- botão ⤢ alterna largo (`min(46rem, 62vw)`) ↔ padrão (21rem).
- a borda esquerda ARRASTA para redimensionar (280px … 80vw).

## Progresso dos jobs

Jobs de fila (ingestão, seed, manutenção, pesquisa) mostram **barra de
progresso REAL** (parseada no core) + etapa + ETA (~Ns restantes) quando
o job reporta; sem %, o log linha a linha continua sendo o progresso.

## Raciocínio transparente

O raciocínio do chat narra TUDO o que o core faz, limpo e claro:

- consultas ao Qdrant (`🗄️ qdrant → coleção: densa + full-text…`) e o que
  voltou (`N denso(s) + M textual(is) → K escolhido(s)` + top resultados
  com score/arquivo);
- modelo: `🧠 modelo X já está no ar — sem recarga` (NUNCA recarregar o
  modelo que já está servindo; troca só quando é OUTRO modelo).

## Combobox inteligente de modelos

- **texto** → modelos de conversa CATEGORIZADOS em optgroups
  (👨‍💻 programação · 💬 conversa).

## Download .zip da aba atual

Botão ⬇ no cabeçalho do painel baixa a ABA ATUAL:

- 📄 arquivos → `POST /api/zip` com `{nome, conteudo}` de cada bloco
  (o caminho do rótulo vira pasta no zip);
- 📚 fontes → `POST /api/zip` com cada fonte como arquivo de texto.
