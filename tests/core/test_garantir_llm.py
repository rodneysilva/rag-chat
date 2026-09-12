"""🎯 Guard do garantir_llm (spec consulta_consolidada.md, regra 10).

LLM_ATIVO=0 é o switch LÓGICO da consulta — diferente dos markers
`*_off.marker` (ciclo FÍSICO de GPU), o ciclo frio NÃO religa o que a
administração desligou. O guard levanta RuntimeError ANTES de qualquer
IO (sem tocar agente/container); consumidores que degradam (rag.llm
engole com try/except) seguem como "LLM indisponível"."""
import pytest

from core import modelos


def test_llm_desligada_na_config_levanta(monkeypatch):
    monkeypatch.setattr(modelos.config, "LLM_ATIVO", False)
    with pytest.raises(RuntimeError, match="desligada na configuração"):
        modelos.garantir_llm()


def test_guard_antes_de_qualquer_io(monkeypatch):
    """O guard dispara SEM consultar o servidor/agente — nem o `servido`
    (cache 10 s, primeira linha do ciclo) pode rodar antes da decisão da
    configuração."""
    monkeypatch.setattr(modelos.config, "LLM_ATIVO", False)

    def _boom(*a, **kw):
        raise AssertionError("IO antes do guard da configuração")
    monkeypatch.setattr(modelos, "servido", _boom)
    monkeypatch.setattr(modelos, "_chamar_agente", _boom)
    with pytest.raises(RuntimeError, match="desligada na configuração"):
        modelos.garantir_llm()
