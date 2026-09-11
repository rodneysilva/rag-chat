"""Tradutor local (MarianMT/opus-mt via ctranslate2 int8) — EN→PT do digest
do rag puro.

Pedido do dono 12/09 ("o retorno tem partes em português e outras em
inglês"): sem LLM não há tradução criativa — mas o trecho pode passar por
um modelinho seq2seq DEDICADO a traduzir (Marian ~110M params). Motor de
execução: ctranslate2 INT8 — medido na VPS (2 vCPU): transformers+torch
fp32 gastava >10 min num lote de 4 trechos; CT2 int8 devolve em segundos.
O tokenizer continua o da HF (sentencepiece + sacremoses); a conversão
int8 roda 1x e fica cacheada ao lado do cache do HF (mesmo volume).

Contrato espelha o core/rerank.py: carregamento LAZY, residente em CPU,
degradação em silêncio (None/item → o chamador mostra o original —
tradução é APRESENTAÇÃO, nunca ponto de falha). As PALAVRAS exibidas
vivem na spec core/specs/traducao.md.
"""
import os
from pathlib import Path

_modelos: dict[str, tuple] = {}   # id do modelo -> (tokenizer, Translator CT2)
_aviso_indisponivel = False       # loga a degradação 1x só


def palavra(chave: str, padrao: str, **subs) -> str:
    """Texto de EXIBIÇÃO do tradutor, lido da spec core/specs/traducao.md
    (regra do projeto: palavras ao usuário vivem na spec, não no código —
    editar a spec muda o texto sem rebuild). `{campo}` no texto é trocado
    pelos `subs`; spec ausente/linha sumida = fallback embutido."""
    try:
        from .specs import valor as _valor
        texto = _valor("traducao", chave, padrao)
    except Exception:
        texto = padrao
    for k, v in subs.items():
        texto = texto.replace("{" + k + "}", str(v))
    return texto


def disponivel() -> bool:
    """ctranslate2 + tokenizer importáveis (sem baixar nada)."""
    try:
        import ctranslate2  # noqa: F401
        import sentencepiece  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


def _dir_ct2(modelo: str) -> Path:
    """Pasta do modelo convertido int8 (ao lado do cache do HF — mesmo
    volume, sobrevive a redeploys)."""
    raiz = Path(os.getenv("HF_HOME") or Path.home() / ".cache" / "huggingface")
    return raiz / "ct2" / modelo.replace("/", "__")


def _carregar(modelo: str, log):
    """Carrega (1x por processo e por modelo): tokenizer HF + motor CT2
    int8. A 1ª carga CONVERTE o modelo do cache do HF (usa torch, ~1 min) e
    guarda — as seguintes abrem o binário int8 direto."""
    import ctranslate2
    from transformers import AutoTokenizer
    log(palavra("MSG_CARREGANDO",
                "⇄ carregando tradutor ({modelo}, CPU; 1ª vez baixa para o "
                "cache do HF)…", modelo=modelo))
    tok = AutoTokenizer.from_pretrained(modelo)
    alvo = _dir_ct2(modelo)
    if not (alvo / "model.bin").exists():
        log(palavra("MSG_CONVERTENDO",
                    "⇄ 1ª vez: convertendo o modelo para ctranslate2 int8 "
                    "(usa torch, ~1 min; as próximas cargas abrem direto)…"))
        from ctranslate2.converters import TransformersConverter
        TransformersConverter(modelo).convert(str(alvo), quantization="int8",
                                              force=False)
    motor = ctranslate2.Translator(str(alvo), device="cpu", inter_threads=1)
    _modelos[modelo] = (tok, motor)


def traduzir_lote(textos: list[str], log=print,
                  modelo: str | None = None) -> list[str | None] | None:
    """Traduz VÁRIOS textos em UM lote (uma passada do modelo — 4 trechos
    custam ~o mesmo que 1; o batch padroniza para o mais longo).

    None quando indisponível (flag off / ct2 ausente / erro); por item,
    a string traduzida ou None (vazio/erro individual não existe aqui:
    lote é atômico — o chamador mostra o original de quem vier None)."""
    global _aviso_indisponivel
    from . import config
    if not getattr(config, "TRADUTOR", True):
        return None
    limpos = [(t or "").strip() for t in textos]
    if not any(limpos):
        return [None] * len(textos)
    if not disponivel():
        if not _aviso_indisponivel:
            _aviso_indisponivel = True
            log(palavra("MSG_INDISPONIVEL",
                        "⇄ tradutor indisponível (ctranslate2 não instalado) "
                        "— os fragmentos ficam no idioma original"), "busca")
        return None
    modelo = modelo or getattr(config, "TRADUTOR_MODEL",
                               "Helsinki-NLP/opus-mt-tc-big-en-pt")
    try:
        if modelo not in _modelos:
            _carregar(modelo, log)
        tok, motor = _modelos[modelo]
        # CT2 fala em TOKENS (strings): codifica cada texto (o tokenizer
        # apenda </s>, como o Marian espera) e decodifica a hipótese de volta
        lotes = [tok.convert_ids_to_tokens(tok(t).input_ids) for t in limpos]
        # GREEDY (beam 1) + teto realista: trecho do digest tem ≤900 chars ≈
        # ~250 tokens de saída — apresentação não pode travar a resposta
        resultados = motor.translate_batch(lotes, beam_size=1,
                                           max_decoding_length=350)
        return [
            tok.decode(tok.convert_tokens_to_ids(r.hypotheses[0]),
                       skip_special_tokens=True).strip() or None
            for r in resultados
        ]
    except Exception as e:
        log(palavra("MSG_FALHA",
                    "⚠️ tradução falhou ({erro}) — trechos no idioma original",
                    erro=str(e)[:120]), "busca")
        return None


def traduzir(texto: str, log=print, modelo: str | None = None) -> str | None:
    """Casca de 1 texto sobre o lote (títulos etc.)."""
    lote = traduzir_lote([texto], log=log, modelo=modelo)
    return lote[0] if lote else None


def descarregar() -> None:
    """Solta o(s) modelo(s) da memória (política do ⏹ Parar tudo)."""
    global _modelos
    _modelos = {}
