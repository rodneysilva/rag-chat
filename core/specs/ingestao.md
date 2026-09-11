# Especificação da ingestão — o contrato narrativo da base

A ingestão transforma material bruto em **unidades narrativas recuperáveis**.
Um chunk que entra na base não é "um pedaço de texto": é uma **história curta
e autocontida** — quem lê (pessoa ou LLM) entende o que ela diz, de onde veio
e onde se encaixa no documento, sem precisar de mais nada.

## O contrato de cada chunk (inviolável)

1. **Sentença completa.** O corte respeita fronteiras naturais na ordem
   parágrafo → linha → fim de frase (`. ! ? … ;`) → palavra. Um chunk NUNCA
   começa ou termina no meio de uma frase — frase cortada é informação
   quebrada, e informação quebrada não vira base.
2. **Cabeçalho contextual embutido.** Todo chunk abre com
   `[título · seção · parte i/n]`. O cabeçalho entra no **embedding** (o
   vetor representa o contexto, não o trecho solto), na **exibição** (a
   webui mostra de onde veio) e no **metadata** (`titulo`/`secao`/`i`/`n`).
   `parte i/n` preserva a ordem da história: a reconstrução do documento e
   a leitura sequencial são sempre possíveis.
3. **Semântica mínima.** Prosa de verdade: frases com pontuação, sem
   dominância de links, tabela, JSON cru ou lista de nomes. O gate
   `score_chunk` (nota 0–1, determinístico) rejeita abaixo de
   `SCORE_CHUNK_MIN` com o motivo no relatório da Revisão.
4. **Sem duplicados.** Conteúdo idêntico entra uma vez.

## O documento como história

O documento inteiro conta uma história: **o que é → os detalhes → a fonte**.
A limpeza (`core/limpeza`) reconstrói frases quebradas pela web (cada
`<a>`/`<b>` do HTML vira linha própria — as frases voltam a ser parágrafos),
remove chrome de página (menus, referências, marcas de edição de wiki,
infoboxes) e preserva tabelas de dado real. O que sobra tem começo, meio e
fonte — nada de "informação jogada sem sentido".

## Pipeline (implementação)

1. Ler `.txt`, `.md`, `.mdx`, `.rst`, `.pdf` e código-fonte da pasta
   (subpastas inclusas).
2. **Limpar e preparar** cada documento (`core/limpeza`): frases
   reconstituídas, ruído fora, título derivado. Código-fonte ganha camada
   própria (sem limpeza de prosa — indentação é semântica) e análise LLM
   por arquivo quando não está em modo lote (`analise_codigo.md`).
3. **Categorizar** com a LLM (`categorizacao.md`) — categoria/descrição
   herdam todos os chunks; no modo lote (`rapido=True`) a categoria é a
   própria coleção.
4. **Dividir** por seções (cabeçalhos markdown) e por tamanho com o corte
   narrativo do contrato; aplicar cabeçalho contextual e gate de qualidade.
5. **Testar o embedding** (BGE-M3) e descobrir a dimensão do vetor.
6. **Criar a coleção** (COSINE) se não existir; gravar os chunks com
   metadata rica (`arquivo`, `titulo`, `secao`, `url`, `i`, `n`, `score`,
   `categoria`).
7. **Registrar no catálogo** (`meta_colecoes`) com categoria e descrição.

## Comportamento esperado

- LLM fora do ar: a ingestão CONTINUA com `categoria="sem_categoria"` —
  nunca falha por isso.
- Qdrant ou embedding fora do ar: aborta com mensagem clara ANTES de começar.
- **Nenhum chunk aprovado: a ingestão FALHA** com o relatório de rejeições
  (motivos e quantidades) — material fragmentado demais não vira base;
  nada é gravado "por gravar".
- Reingerir a mesma pasta adiciona os pedaços de novo (duplica) — use a
  higienização e os snapshots para corrigir bases existentes.
