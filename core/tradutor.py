"""Tradutor local (MarianMT/opus-mt) — EN→PT do digest do rag puro.

Pedido do dono 12/09 ("o retorno tem partes em português e outras em
inglês"): sem LLM não há tradução criativa — mas o trecho pode passar por
um modelinho seq2seq DEDICADO a traduzir (Marian ~110M params, ~450 MB em
safetensors), na MESMA stack do reranker (torch+transformers, CPU, cache
do HF em volume).

Contrato espelha o core/rerank.py: carregamento LAZY, residente em CPU,
degradação em silêncio (None/item → o chamador mostra o original —
tradução é APRESENTAÇÃO, nunca ponto de falha).
"""
_modelos: dict[str, tuple] = {}   # id do modelo -> (tokenizer, model)
_aviso_indisponivel = False       # loga a degradação 1x só


def disponivel() -> bool:
    """torch+transformers importáveis (sem baixar nada)."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


def _carregar(modelo: str, log):
    """Carrega (1x por processo e por modelo) o seq2seq do cache do HF."""
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    log(f"⇄ carregando tradutor ({modelo}, CPU; 1ª vez baixa para o cache "
        "do HF)…")
    tok = AutoTokenizer.from_pretrained(modelo)
    mod = AutoModelForSeq2SeqLM.from_pretrained(modelo)
    mod.eval()
    _modelos[modelo] = (tok, mod)


def traduzir_lote(textos: list[str], log=print,
                  modelo: str | None = None) -> list[str | None] | None:
    """Traduz VÁRIOS textos em UM lote (uma passada do modelo — 4 trechos
    custam ~o mesmo que 1; o batch padroniza para o mais longo).

    None quando indisponível (flag off / torch ausente / erro); por item,
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
            log("⇄ tradutor indisponível (torch não instalado) — os "
                "fragmentos ficam no idioma original", "busca")
        return None
    modelo = modelo or getattr(config, "TRADUTOR_MODEL",
                               "Helsinki-NLP/opus-mt-tc-big-en-pt")
    try:
        if modelo not in _modelos:
            _carregar(modelo, log)
        import torch
        tok, mod = _modelos[modelo]
        with torch.no_grad():
            entradas = tok(limpos, return_tensors="pt", padding=True,
                           truncation=True, max_length=512)
            saidas = mod.generate(**entradas, num_beams=2,
                                  max_new_tokens=600)
        return [tok.decode(s, skip_special_tokens=True).strip() or None
                for s in saidas]
    except Exception as e:
        log(f"⚠️ tradução falhou ({str(e)[:120]}) — trechos no idioma "
            "original", "busca")
        return None


def traduzir(texto: str, log=print, modelo: str | None = None) -> str | None:
    """Casca de 1 texto sobre o lote (títulos etc.)."""
    lote = traduzir_lote([texto], log=log, modelo=modelo)
    return lote[0] if lote else None


def descarregar() -> None:
    """Solta o(s) modelo(s) da memória (política do ⏹ Parar tudo)."""
    global _modelos
    _modelos = {}
