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
   metadata traz e difere do título), origem (coleção · área, ou 🌐 web) —
   e o marcador *(traduzido)* quando o tradutor agiu.
2. Do fragmento entra só o TRECHO mais parecido com a pergunta (parágrafo
   ± vizinhos, até ~900 caracteres), nunca a seção inteira; detritos de
   citação da Wikipédia (<sup>, <ref>, [12]) fora; cabeçalho de indexação
   do chunk removido.
3. PEDIDO DE CÓDIGO ("hello world", "exemplo", "como fazer em X", "criar
   um script"): quando o fragmento contém bloco de código cercado
   (```), o bloco entra INTEIRO e VERBATIM como resposta do item —
   EXTRAÇÃO da base, nunca geração. Sem bloco na base, o trecho de prosa
   responde como sempre.
4. HONESTIDADE: o reranker bilíngue leu pergunta × cada fragmento; se
   NADA tem relação real com o pedido, a resposta AVISA e o material só
   entra "por referência" — nunca entrega outro assunto como se fosse a
   resposta.
5. ORDEM = relevância do reranker: fragmentos da base e páginas baixadas
   da web disputam em igualdade (rerank base+web).

## Palavras usadas pelo código

(O código lê estas linhas; editar aqui muda o texto exibido sem rebuild.
"\n" na linha vira quebra de texto.)

MSG_SEM_SINAL: ⚠️ **Nada na base responde a esta pergunta** — o reranker analisou os fragmentos recuperados e nenhum tem relação real com o pedido (a base não parece conter este assunto).\n\nO material abaixo é apenas o mais próximo que a busca encontrou, por referência:\n\n
MSG_RECUSA_CRIAR: Não possuo dados confiáveis o suficiente nos documentos para responder.\n\n💡 Seu pedido parece ser de **criação** (página, código, API…): isto é trabalho do modo **híbrido** — a base orienta o estilo e o modelo escreve. A LLM está desligada na configuração: peça ao administrador para ligá-la em **Sistema → 🎯 Consulta** (spec consulta_consolidada.md).
