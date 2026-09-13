# Especificação do modo rag PURO (resposta em linguagem natural sem LLM)

Pedido do dono 11/09 ("quando seleciono só a base, não precisa consultar a
LLM") e 12/09 ("usar o Qdrant e o embedding e conseguir fazer buscas
semânticas e ter respostas em linguagem natural sem precisar de LLM —
culinária hoje, hello world em qualquer linguagem amanhã"): a resposta É o
DIGEST dos fragmentos recuperados — embedding + Qdrant + reranker (+ o
tradutor da spec traducao.md) montam tudo. Nenhuma chamada à LLM de
conversa; o container do chat nem acorda na estação.

## Regras

1. HEADER PADRÃO de cada fragmento: número, título, o que é (quando a
   metadata traz e difere do título), origem (ÁREA do domínio, ou 🌐 web —
   nome de coleção NÃO aparece: regra 6 da spec consulta_consolidada.md) —
   e o marcador *(traduzido)* quando o tradutor agiu. A RESPOSTA DIRETA
   (score alto) segue o MESMO idioma da pergunta: fragmento em inglês para
   pergunta em português sai traduzido (spec traducao.md) com o marcador.
2. Do fragmento entra o TRECHO mais parecido com a pergunta (parágrafo
   ± vizinhos, até ~1600 caracteres — `DIGEST_MAX` no .env: seção completa
   da base autoral quando cabe), corte só em borda de parágrafo/palavra;
   CERCA DE CÓDIGO NUNCA É CORTADA nem no trecho nem na exibição (regra
   8); detritos de citação da Wikipédia (<sup>, <ref>, [12]) fora;
   cabeçalho de indexação do chunk removido; linhas de METADADO de
   datasets (repo_name, sha256, "campo: valor | campo: valor") fora — só
   o conteúdo da linha entra.
3. PEDIDO DE CÓDIGO ("hello world", "exemplo", "como fazer em X", "criar
   um script"): quando o fragmento contém bloco de código cercado
   (```), o bloco entra INTEIRO e VERBATIM como resposta do item —
   EXTRAÇÃO da base, nunca geração. Sem bloco na base, o trecho de prosa
   responde como sempre.
4. HONESTIDADE: o reranker bilíngue leu pergunta × cada fragmento; se
   NADA tem relação real com o pedido, a resposta AVISA e o material só
   entra "por referência" (no máximo 3 fragmentos) — nunca entrega outro
   assunto como se fosse a resposta.
5. ORDEM = relevância do reranker: fragmentos da base e páginas baixadas
   da web disputam em igualdade (rerank base+web). Com fragmentos de
   ASSUNTOS diferentes, o digest AGRUPA por assunto (área do domínio) —
   seções na ordem do melhor fragmento de cada grupo, ordem do reranker
   mantida DENTRO do grupo; um assunto só segue sem seções.
6. ROTEAMENTO DE DOMÍNIO (regex, sem LLM — pedido do dono 12/09: "eu
   perguntei de código e me falou de ingredientes"): a pergunta declara o
   assunto e o escopo acompanha — termos de código (linguagem/framework,
   "api", "função", "docker"…) restringem a busca às coleções de
   desenvolvimento; pergunta SEM esses termos tira as coleções dev quando
   há coleções de outro domínio no escopo. A regra só RESTRIGE: escopo
   que ficaria vazio segue como está (a honestidade da regra 4 cobre o
   resto — classificação errada vira aviso de sem-sinal, nunca resposta
   de outro assunto).
7. BASE DEV AUTORAL (pedido do dono 13/09: "pode usar a llm para montar os
   documentos… quero deixar o rag perfeito, sem cortes ou informações
   incompletas, para usar depois sem o uso de llms"): as coleções dev
   (dotnet, python, rust, go, nodejs, javascript, typescript, java, ruby)
   são documentos AUTORAIS completos em PORTUGUÊS, redigidos COM IA
   apenas na MONTAGEM dos .md (datasets/seed/{colecao}/, formato
   `# título` + `> fonte:` + `> redação:` + `> descrição:`) — a CONSULTA
   segue 100% sem LLM. Pergunta PT acha documento PT: sem tradutor, sem
   marcador *(traduzido)*. Rebuild: `scripts/seed_autoral.py` (apaga a
   coleção inteira e reingere só os autorais — wipe total, sem fantasma).
8. GARANTIA VERBATIM EM CADEIA (o código é extraído, nunca reescrito):
   (i) a LIMPEZA de ingestão é fence-aware — cerca ``` fechada sai byte a
   byte (indentação, linhas de símbolo, fechamento); (ii) o SPLIT nunca
   pica cerca entre chunks (bloco atômico, mesmo acima de CHUNK_SIZE) e
   os cabeçalhos markdown só cortam na prosa; (iii) os GATES de
   qualidade pontuam a prosa — pipes/indentação de código não são tabela
   nem ruído; (iv) o DIGEST nunca corta dentro de cerca. Autoria: código
   em cercas ``` com tag de linguagem; exemplos que citam ``` interno
   usam cerca `~~~`.

## Palavras usadas pelo código

(O código lê estas linhas; editar aqui muda o texto exibido sem rebuild.
"\n" na linha vira quebra de texto.)

MSG_SEM_SINAL: ⚠️ **Nada na base responde a esta pergunta** — o reranker analisou os fragmentos recuperados e nenhum tem relação real com o pedido (a base não parece conter este assunto).\n\nO material abaixo é apenas o mais próximo que a busca encontrou, por referência:\n\n
MSG_RECUSA_CRIAR: Não possuo dados confiáveis o suficiente nos documentos para responder.\n\n💡 Seu pedido parece ser de **criação** (página, código, API…): isto é trabalho do modo **híbrido** — a base orienta o estilo e o modelo escreve. A LLM está desligada na configuração: peça ao administrador para ligá-la em **Sistema → 🎯 Consulta** (spec consulta_consolidada.md).
