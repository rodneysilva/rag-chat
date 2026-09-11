# Especificação da consolidação na ingestão (verificar antes de incluir)

Pedido do dono 12/09: "antes de incluir qualquer item no Qdrant, verificar se
já tem a informação, e se tiver, consolidar — sempre que fizer uma inclusão
na mesma coleção, pesquisar o que tem e complementar; se não tiver,
acrescentar".

## Regras

1. NENHUM pedaço entra na coleção sem antes CONSULTAR o que já está lá:
   cada pedaço novo é embedado e comparado (busca vetorial na MESMA
   coleção, top-3) com o que a coleção já tem.
2. Score ≥ 0.92 (mesma informação dita com outras palavras) → CONSOLIDAR
   no ponto existente (mesmo id): o texto base permanece e as SENTENÇAS
   NOVAS do pedaço que chegou são anexadas; a metadata é fundida (campos
   vazios preenchidos, origens distintas lembradas em origens_extras); o
   ponto ganha atualizado_em e é re-embedado.
3. Pedaço que não acrescenta NENHUMA sentença nova → INALTERADO (nada é
   gravado — a informação já estava completa). Código (camada "codigo")
   NUNCA é fundido no meio: acima do limiar é porque já está lá
   (inalterado); versão diferente de código é assunto novo (entra).
4. Score < 0.92 (informação nova) → ACRESCENTAR como ponto novo com id
   DETERMINÍSTICO (hash do conteúdo na coleção): reingerir o mesmo
   material SOBREPÕE em vez de empilhar.
5. PADRÃO de todo ponto gravado: metadata o_que_e, pra_que_serve,
   criado_em/atualizado_em; e a primeira linha do texto é o cabeçalho
   "[O que é: … · Para que serve: … · parte i/n]" — o cabeçalho
   contextualiza o EMBEDDING; a exibição (digest/resposta direta) o
   remove.
6. SAÍDA PADRÃO de toda inclusão/alteração — sempre o mesmo formato,
   no log do job e no resultado da operação.

## Palavras usadas pelo código

(O código lê estas linhas; editar aqui muda o texto exibido sem rebuild.
"\n" na linha vira quebra de texto.)

MSG_INICIO: 🔎 consultando a coleção antes de incluir ({total} pedaço(s)) — semelhante ≥ {limiar} funde, novo acrescenta…
MSG_CONSOLIDANDO: 🔁 consolidando com o ponto existente (score {score}): {titulo} +{novas} frase(s) nova(s)
MSG_NOVO: ⬆️ {novos} pedaço(s) novo(s) — id determinístico (reingestão sobrepõe, não empilha)
MSG_SAIDA: 📥 saída: {novos} novo(s) · {consolidados} consolidado(s) · {inalterados} inalterado(s) — {colecao} ficou com {total} ponto(s)
