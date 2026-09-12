"""🧭 Roteamento de domínio no escopo da consulta (regra 6 da spec
rag_puro.md — sem LLM).

Caso real do dono 12/09: "Como desenvolvo uma api em dotnet?" com escopo
"todas as visíveis" devolvia tucupi junto com arquivos .NET. A pergunta
declara o assunto e o escopo acompanha — a regra só RESTRINGE (escopo que
ficaria vazio segue como está).
"""
import pytest
from langchain_core.documents import Document

from api.base import QueryIn, _processar_query


def _doc(txt: str, colecao: str) -> Document:
    return Document(page_content=txt,
                    metadata={"colecao": colecao, "area": ""})


class _ClientFake:
    """Qdrant de mentira: dotnet/python/culinaria/psicanalista existem
    (a base unificada NÃO — para não entrar no escopo dos testes)."""

    def collection_exists(self, nome: str) -> bool:
        return nome in {"dotnet", "python", "culinaria", "psicanalista"}


@pytest.fixture
def cenario(monkeypatch):
    """Modo rag puro (LLM off), escopo com DOMÍNIOS MISTOS e o rag.search
    capturando o escopo EFETIVO que chegou à busca."""
    from api import base
    from core import rag, modelos

    monkeypatch.setattr(base.config, "RAG_ATIVO", True)
    monkeypatch.setattr(base.config, "LLM_ATIVO", False)
    monkeypatch.setattr(base.config, "RAG_COLECOES",
                        "dotnet,python,culinaria,psicanalista")
    monkeypatch.setattr(base.config, "MCP_ATIVOS", "")
    capturado: dict = {}

    def _search(client, escopo, pergunta, log=None, **kw):
        capturado["escopo"] = list(escopo)
        capturado["pergunta"] = pergunta
        return ([(_doc("Um controller em ASP.NET faz o roteamento da api.",
                       "dotnet"), 0.58, "dotnet")], {})
    monkeypatch.setattr(rag, "search", _search)
    monkeypatch.setattr(rag, "versoes_ausentes", lambda q, d: [])
    monkeypatch.setattr(base, "QdrantClient", lambda **kw: _ClientFake())
    monkeypatch.setattr(modelos, "servido",
                        lambda porta=None, forcar=False: "alias-x")
    monkeypatch.setattr(base.config, "SCORE_DIRETO", 0.99)
    monkeypatch.setattr(base.config, "SCORE_FRACO", 0.0)
    monkeypatch.setattr(base.rerank, "rerank", lambda *a, **kw: None)
    monkeypatch.setattr(base.rerank, "notas_de", lambda *a, **kw: None)
    monkeypatch.setattr(base.bussola, "consultar", lambda *a, **kw: None)
    monkeypatch.setattr(base.bussola, "registrar", lambda *a, **kw: None)
    return base, rag, capturado


def _query(base, rag, capturado, pergunta, **kw):
    r = _processar_query(QueryIn(question=pergunta, mode="rag", **kw))
    assert r["mode"] == "rag"
    return r


def test_pergunta_de_codigo_busca_so_colecoes_dev(cenario):
    """O caso do dono: pergunta dev não disputa com culinária/psicanálise."""
    base, rag, capturado = cenario
    _query(base, rag, capturado, "Como desenvolvo uma api em dotnet?")
    assert capturado["escopo"] == ["dotnet", "python"]  # só dev
    assert "culinaria" not in capturado["escopo"]


def test_pergunta_fora_de_codigo_exclui_as_colecoes_dev(cenario):
    """Simetria: 'receita de tucupi' não vasculha os chunks de código."""
    base, rag, capturado = cenario
    _query(base, rag, capturado, "como fazer tucupi?")
    assert capturado["escopo"] == ["culinaria", "psicanalista"]
    assert "dotnet" not in capturado["escopo"]


def test_pergunta_dev_sem_colecao_dev_mantem_o_escopo(cenario, monkeypatch):
    """Escopo que ficaria VAZIO segue como está (produção hoje: só
    culinária) — a honestidade do sem-sinal cobre; nunca 503."""
    base, rag, capturado = cenario
    monkeypatch.setattr(base.config, "RAG_COLECOES", "culinaria")
    _query(base, rag, capturado, "Como desenvolvo uma api em dotnet?")
    assert capturado["escopo"] == ["culinaria"]


def test_pergunta_nao_dev_com_escopo_so_dev_mantem_o_escopo(
        cenario, monkeypatch):
    base, rag, capturado = cenario
    monkeypatch.setattr(base.config, "RAG_COLECOES", "dotnet,python")
    _query(base, rag, capturado, "como fazer tucupi?")
    assert capturado["escopo"] == ["dotnet", "python"]


def test_escopo_unico_nao_e_restringido(cenario, monkeypatch):
    """Coleção única marcada pelo admin é intenção explícita — sem ruído."""
    base, rag, capturado = cenario
    monkeypatch.setattr(base.config, "RAG_COLECOES", "culinaria")
    _query(base, rag, capturado, "como fazer tucupi?")
    assert capturado["escopo"] == ["culinaria"]
