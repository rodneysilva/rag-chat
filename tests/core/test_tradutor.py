"""Tradutor local (opus-mt) — contrato de degradação.

Tradução é APRESENTAÇÃO, nunca ponto de falha: flag desligada devolve None
e o chamador mostra o original. (O caminho feliz exige torch+transformers
e o modelo do HF — coberto ao vivo na validação, não aqui.)"""
from core import config, tradutor


def test_flag_desligada_devolve_none(monkeypatch):
    monkeypatch.setattr(config, "TRADUTOR", False)
    assert tradutor.traduzir_lote(["kitchen"]) is None


def test_texto_vazio_nao_acorda_o_modelo(monkeypatch):
    monkeypatch.setattr(config, "TRADUTOR", True)
    monkeypatch.setattr(tradutor, "disponivel",
                        lambda: (_ for _ in ()).throw(AssertionError(
                            "modelo consultado com lote vazio")))
    assert tradutor.traduzir_lote(["", "  "]) == [None, None]


def test_descarregar_solta_o_modelo():
    tradutor._modelos["teste/falso"] = ("tok", "mod")
    tradutor.descarregar()
    assert tradutor._modelos == {}
