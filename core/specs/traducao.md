# Especificação da tradução dos trechos do digest (modo rag puro)

Pedido do dono 12/09 ("o retorno tem partes em português e outras em inglês"):
no modo rag puro não há LLM de conversa para reescrever a resposta — os
trechos em inglês passam por um tradutor LOCAL dedicado (MarianMT/opus-mt,
seq2seq de ~110M parâmetros) antes de entrar no digest. O motor de execução
é o ctranslate2 INT8 na CPU (transformers+torch fp32 media >10 min por lote
na VPS de 2 vCPU — CT2 int8 devolve em segundos; a conversão roda 1x e fica
em cache). Tradução é APRESENTAÇÃO: nunca é ponto de falha e nunca acorda a
GPU da estação.

## Regras

1. Só traduz quando a PERGUNTA está em português e o TRECHO não está —
   pergunta em inglês recebe trecho em inglês (o leitor perguntou no idioma
   que lê).
2. TÍTULO entra na fila apenas com evidência REAL de inglês (palavra
   funcional EN presente no texto): título curto sem evidência fica no
   original — traduzir "Tucupi — síntese" (já em português) seria pior do
   que deixar como está.
3. Trechos e títulos vão em UM LOTE — uma única passada do modelo cobre
   tudo (o custo é o do texto mais longo, não a soma deles).
4. O trecho traduzido sai MARCADO no cabeçalho do digest: o leitor sabe
   que aquele texto é tradução do sistema, não a redação original da fonte.
5. Indisponível (flag desligada / torch ausente / erro de inferência) =
   trecho no idioma original, aviso único em silêncio — a resposta nunca
   derruba por causa da tradução.
6. Geração GREEDY (beam 1) com teto de ~350 tokens por item, no motor
   ctranslate2 INT8: apresentação não pode travar a resposta. O greedy
   pode DEGENERAR em loop de repetição ("você vai" ×N até o teto — visto
   ao vivo 13/09 no trecho do dev.java, texto fora do domínio do modelo):
   a decodificação bloqueia 4-gramas repetidos e a saída degenerada é
   DESCARTADA — o trecho fica no idioma original (regra 5).

## Palavras usadas pelo código

(O código lê estas linhas; editar aqui muda o texto exibido sem rebuild.)

MARCADOR_TRADUZIDO: *(traduzido)*
MSG_CARREGANDO: ⇄ carregando tradutor ({modelo}, CPU; 1ª vez baixa/converte para o cache)…
MSG_CONVERTENDO: ⇄ 1ª vez: convertendo o modelo para ctranslate2 int8 (usa torch, ~1 min; as próximas cargas abrem direto)…
MSG_INDISPONIVEL: ⇄ tradutor indisponível (ctranslate2 não instalado) — os fragmentos ficam no idioma original
MSG_FALHA: ⚠️ tradução falhou ({erro}) — trechos no idioma original
MSG_DEGENERADA: ⚠️ tradução saiu em loop de repetição ({n}×) — trecho no idioma original
MSG_PREAQUECIDO: ⇄ tradutor pré-aquecido no boot — trechos EN saem traduzidos sem pagar a 1ª carga
