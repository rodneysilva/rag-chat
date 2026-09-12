"""🎯 CONSULTA CONSOLIDADA — resolução pura (core/consulta.py) e a injeção
no _processar_query (spec core/specs/consulta_consolidada.md).

Regras cobertas: modo efetivo das 4 combinações de toggles (2), escopo
RAG_COLECOES vazio = todas (3), MCP_ATIVOS cru (4), payload ACEITO E
IGNORADO (5), 503 com ambos desligados (MSG_INDISPONIVEL), MCPs reais
pulados sem LLM, pedido de web na mensagem NÃO liga busca sozinho (4)."""
import pytest
from fastapi import HTTPException
from langchain_core.documents import Document

from api.base import QueryIn, _processar_query
from core import consulta


# ── módulo puro: as 4 combinações + CSVs ──────────────────────────────
class TestResolucaoPura:
    @pytest.mark.parametrize("rag,llm,esperado", [
        (True, True, "hibrido"),
        (True, False, "rag"),
        (False, True, "livre"),
    ])
    def test_modo_efetivo(self, monkeypatch, rag, llm, esperado):
        monkeypatch.setattr(consulta.config, "RAG_ATIVO", rag)
        monkeypatch.setattr(consulta.config, "LLM_ATIVO", llm)
        assert consulta.modo_efetivo() == esperado

    def test_ambos_off_levanta(self, monkeypatch):
        monkeypatch.setattr(consulta.config, "RAG_ATIVO", False)
        monkeypatch.setattr(consulta.config, "LLM_ATIVO", False)
        with pytest.raises(consulta.ConsultaIndisponivel):
            consulta.modo_efetivo()
        # resumo NÃO levanta: modo None = o chamador devolve o 503
        assert consulta.resumo()["modo"] is None

    def test_escopo_vazio_eh_none_todas(self, monkeypatch):
        monkeypatch.setattr(consulta.config, "RAG_COLECOES", "")
        assert consulta.escopo_config() is None      # todas as visíveis

    def test_escopo_csv_limpo(self, monkeypatch):
        monkeypatch.setattr(consulta.config, "RAG_COLECOES",
                            " a ,, b ,a,")
        assert consulta.escopo_config() == ["a", "b"]

    def test_mcps_csv(self, monkeypatch):
        monkeypatch.setattr(consulta.config, "MCP_ATIVOS",
                            "pesquisa-web, servidor-x,pesquisa-web")
        assert consulta.mcps_config() == ["pesquisa-web", "servidor-x"]


# ── mundo falso mínimo p/ _processar_query (padrão do test_rag_puro) ──
class _ClientFake:
    def collection_exists(self, nome):
        return nome == "c"


@pytest.fixture
def mundo(monkeypatch):
    from api import base
    from core import rag, modelos
    monkeypatch.setattr(base.config, "MOCK_LLM", False)
    monkeypatch.setattr(base.config, "RAG_ATIVO", True)
    monkeypatch.setattr(base.config, "LLM_ATIVO", True)
    monkeypatch.setattr(base.config, "RAG_COLECOES", "c")
    monkeypatch.setattr(base.config, "MCP_ATIVOS", "")
    monkeypatch.setattr(base.config, "SCORE_DIRETO", 0.99)
    monkeypatch.setattr(base.config, "SCORE_FRACO", 0.0)
    achados = [(Document(page_content="O vatapá é um prato paraense.",
                         metadata={"colecao": "c"}), 0.60, "c")]
    monkeypatch.setattr(rag, "search", lambda *a, **kw: (achados, {}))
    monkeypatch.setattr(rag, "versoes_ausentes", lambda q, d: [])
    monkeypatch.setattr(base, "QdrantClient", lambda **kw: _ClientFake())
    monkeypatch.setattr(modelos, "servido",
                        lambda *a, **kw: "alias-x")
    monkeypatch.setattr(modelos, "garantir_llm", lambda log=None: True)
    monkeypatch.setattr(base.grafo, "rotear",
                        lambda *a, **kw: {"rota": "fluxo", "tipo": "",
                                          "motivo": "teste"})
    monkeypatch.setattr(rag, "reformula", lambda q, h: q)
    monkeypatch.setattr(rag, "answer_hybrid", lambda *a, **kw: "síntese")
    monkeypatch.setattr(base.bussola, "consultar", lambda *a, **kw: None)
    monkeypatch.setattr(base.bussola, "registrar", lambda *a, **kw: None)
    return base


class TestPayloadNaoManda:
    def test_payload_ignorado(self, mundo):
        """Regra 5: mode/model/collections/mcps do QueryIn são aceitos e
        IGNORADOS — a config da administração vence (e a 1ª linha do
        raciocínio registra isso)."""
        linhas = []

        def _log(m, g="geral"):
            linhas.append(m)
        r = _processar_query(
            QueryIn(question="o que é o vatapá?", mode="rag", model="alias-y",
                    collections=["x"], mcps=["z"]), log=_log)
        assert r["mode"] == "hibrido"           # config: ambos ligados
        assert r["collections"] == ["c"]        # config: RAG_COLECOES
        assert any("payload ignora" in m for m in linhas)
        assert any(m.startswith("🎯 consulta consolidada") for m in linhas)

    def test_ambos_off_devolve_503_da_spec(self, mundo, monkeypatch):
        monkeypatch.setattr(mundo.config, "RAG_ATIVO", False)
        monkeypatch.setattr(mundo.config, "LLM_ATIVO", False)
        with pytest.raises(HTTPException) as e:
            _processar_query(QueryIn(question="o que é o vatapá?"))
        assert e.value.status_code == 503
        assert "Consulta indisponível" in e.value.detail   # MSG_INDISPONIVEL


class TestMcpsDaConfig:
    def test_mcp_real_pulado_sem_llm(self, mundo, monkeypatch):
        """Regra 4: MCPs reais exigem LLM (ReAct raciocina no modelo) — com
        LLM_ATIVO=0 são PULADOS com aviso no raciocínio."""
        monkeypatch.setattr(mundo.config, "LLM_ATIVO", False)  # modo: rag
        monkeypatch.setattr(mundo.config, "MCP_ATIVOS", "servidor-x")

        def _boom(*a, **kw):
            raise AssertionError("carregar_ferramentas foi chamado sem LLM")
        monkeypatch.setattr(mundo.mcp_registry, "carregar_ferramentas", _boom)
        linhas = []

        r = _processar_query(QueryIn(question="o que é o vatapá?"),
                             log=lambda m, g="geral": linhas.append(m))
        assert r["mode"] == "rag"                # só RAG ligado
        assert r["ferramentas"] == []            # nada de MCP
        assert any("MCPs pulados" in m for m in linhas)

    def test_pedido_de_web_so_busca_se_configurada(self, mundo, monkeypatch):
        """Regra 4: "pesquise na web" na mensagem NÃO liga a busca sozinho —
        pesquisa-web entra pela config (MCP_ATIVOS); sem ele o pedido é
        apenas INFORMATIVO no log."""
        monkeypatch.setattr(mundo.config, "LLM_ATIVO", False)  # modo: rag
        monkeypatch.setattr(mundo.config, "MCP_ATIVOS", "")

        def _boom(*a, **kw):
            raise AssertionError("busca web disparou sem pesquisa-web na config")
        monkeypatch.setattr(mundo, "_web_aprofundado", _boom)
        linhas = []
        _processar_query(QueryIn(question="pesquise na web o que é vatapá"),
                         log=lambda m, g="geral": linhas.append(m))
        assert any("NÃO" in m and "sem busca" in m for m in linhas)
