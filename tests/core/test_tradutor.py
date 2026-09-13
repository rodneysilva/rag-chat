"""⇄ Guardas de DEGENERAÇÃO do tradutor (caso real 13/09: o greedy do
opus-mt entrava em loop de repetição — "você vai" ×N até o teto — no
trecho do dev.java, texto fora do domínio; o digest cuspiu o spam
traduzido como se fosse a resposta).
"""
from types import SimpleNamespace

from core import tradutor


class _TokFake:
    """Tokenizer de mentira: devolve a PRÓXIMA saída da fila a cada decode."""

    def __init__(self, saidas: list[str]):
        self._fila = list(saidas)

    def __call__(self, t):
        return SimpleNamespace(input_ids=[1, 2, 3])

    def convert_ids_to_tokens(self, ids):
        return ["<s>", "tok", "</s>"]

    def convert_tokens_to_ids(self, toks):
        return [1]

    def decode(self, ids, skip_special_tokens=True):
        return self._fila.pop(0)


class _MotorFake:
    def __init__(self):
        self.kwargs = None

    def translate_batch(self, lotes, **kw):
        self.kwargs = kw
        return [SimpleNamespace(hypotheses=[["tok"]]) for _ in lotes]


def _montar(monkeypatch, saidas):
    from core import config
    motor = _MotorFake()
    tok = _TokFake(saidas)
    monkeypatch.setattr(config, "TRADUTOR", True)
    monkeypatch.setattr(config, "TRADUTOR_MODEL", "m")
    monkeypatch.setattr(tradutor, "disponivel", lambda: True)
    monkeypatch.setattr(tradutor, "_modelos", {"m": (tok, motor)})
    return motor


def test_degenerada_detecta_o_loop():
    loop = "você vai, " * 60
    assert tradutor._degenerada(loop) is True
    # no meio de texto normal, o loop continua detectado (janela deslizante)
    misto = ("O vatapá é um prato paraense à base de dendê e camarão seco. "
             + "você vai, " * 40)
    assert tradutor._degenerada(misto) is True


def test_degenerada_nao_acusa_prosa_normal():
    bom = ("O vatapá é um prato paraense à base de dendê, pão e camarão "
           "seco, servido com arroz branco. O caruru acompanha o vatapá na "
           "tradição baiana. Cada família guarda sua receita e o tempero "
           "muda de cidade para cidade, mas o vatapá segue sendo o prato "
           "central das festas. ") * 2
    assert tradutor._degenerada(bom) is False
    assert tradutor._degenerada("curto demais") is False


def test_traducao_degenerada_vira_none_e_a_limpa_passa(monkeypatch):
    """Loop de repetição = DESCARTA (trecho fica no idioma original); a
    tradução limpa passa — o guard não joga fora tradução boa."""
    loop = "você vai, " * 60
    limpa = ("O vatapá é um prato tradicional do estado do Pará, feito com "
             "azeite de dendê, pão e camarão seco, servido com arroz "
             "branco, apreciado nas festas religiosas do Norte do Brasil "
             "desde o tempo da colônia, com variações de família para "
             "família em cada cidade da região amazônica do Pará.")
    _montar(monkeypatch, [limpa, loop])
    out = tradutor.traduzir_lote(["texto 1", "texto 2"], log=lambda *a: None)
    assert out[0] == limpa          # limpa: tradução entregue
    assert out[1] is None           # loop: original mostrado


def test_decodificacao_bloqueia_4grama_repetido(monkeypatch):
    """A fonte do problema é o greedy sem trava: o motor agora decodifica
    com no_repeat_ngram_size=4 (4-grama repetido é loop, não prosa)."""
    motor = _montar(monkeypatch, ["tradução limpa e comum, sem loop algum "
                                  "de repetição, seguindo o texto da fonte."])
    tradutor.traduzir_lote(["x"], log=lambda *a: None)
    assert motor.kwargs["no_repeat_ngram_size"] == 4
    assert motor.kwargs["beam_size"] == 1
