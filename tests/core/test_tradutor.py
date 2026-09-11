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


def test_palavras_vivem_na_spec_nao_no_codigo():
    """Regra do projeto (pedido do dono): texto exibido ao usuário vem da
    spec core/specs/traducao.md — o marcador do digest e as mensagens de
    log são LIDOS de lá, com fallback embutido se a spec sumir."""
    # marcador real: lido da spec que existe no repo
    marcador = tradutor.palavra("MARCADOR_TRADUZIDO", "*(fallback)*")
    assert marcador.startswith("*(") and marcador.endswith(")*")
    assert marcador != "*(fallback)*"          # a spec foi a fonte
    # substituição de {campo} na mensagem da spec
    msg = tradutor.palavra("MSG_FALHA", "erro {erro}",
                           erro="boom")
    assert "boom" in msg and "{" not in msg
    # chave inexistente na spec: fallback embutido SEM estourar
    assert tradutor.palavra("CHAVE_INEXISTENTE", "seguro") == "seguro"
