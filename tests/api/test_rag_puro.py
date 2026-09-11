"""Modo rag PURO (pedido do dono 11/09: "só deve ligar a gpu se for usar a
gpu, quando seleciono só a base, não precisa consultar a llm, somente o
embedding").

O fluxo inteiro do modo rag roda SEM acordar o container do chat da
estação: sem garantir_llm, sem roteador (LangGraph), sem reformulação,
sem resgate PT→EN — a resposta é o digest dos fragmentos recuperados
(embedding + Qdrant + rerank apenas). Os testes usam SENTINELAS que
explodem se qualquer um desses for tocado."""
import pytest
from langchain_core.documents import Document

from api.base import QueryIn, _processar_query


def _doc(txt: str, colecao: str = "c") -> Document:
    return Document(page_content=txt,
                    metadata={"colecao": colecao, "area": ""})


class _ClientFake:
    """Qdrant de mentira: só a coleção 'c' existe."""

    def collection_exists(self, nome: str) -> bool:
        return nome == "c"


def _proibido(motivo: str):
    def boom(*a, **kw):
        raise AssertionError(f"modo rag consultou a LLM via {motivo}")
    return boom


@pytest.fixture
def cenario(monkeypatch):
    """Monta o mundo: base com 2 fragmentos médios (0.58–0.60: fora do
    SCORE_DIRETO e acima do FRACO — nem resposta-direta, nem descarte)."""
    from api import base
    from core import rag, modelos, idioma

    achados = [
        (_doc("[vatapá passo a passo]\nO vatapá é prato paraense à base de dendê e pão."), 0.60, "c"),
        (_doc("O caruru acompanha o vatapá na tradição baiana."), 0.58, "c"),
    ]
    monkeypatch.setattr(rag, "search", lambda *a, **kw: (achados, {}))
    monkeypatch.setattr(rag, "versoes_ausentes", lambda q, d: [])
    monkeypatch.setattr(base, "QdrantClient", lambda **kw: _ClientFake())
    monkeypatch.setattr(modelos, "servido",
                        lambda porta=None, forcar=False: "alias-x")
    monkeypatch.setattr(base.config, "SCORE_DIRETO", 0.99)
    monkeypatch.setattr(base.config, "SCORE_FRACO", 0.0)
    monkeypatch.setattr(base.bussola, "consultar", lambda *a, **kw: None)
    monkeypatch.setattr(base.bussola, "registrar",
                        lambda *a, **kw: None)
    # sentinelas: qualquer caminho de LLM aqui é bug (acordaria a GPU)
    monkeypatch.setattr(modelos, "garantir_llm", _proibido("garantir_llm"))
    monkeypatch.setattr(base.grafo, "rotear", _proibido("roteador"))
    monkeypatch.setattr(rag, "reformula", _proibido("reformulação"))
    monkeypatch.setattr(idioma, "para_busca_inglesa",
                        _proibido("resgate PT→EN"))
    return base, rag


def test_rag_puro_responde_sem_acordar_a_llm(cenario):
    base, rag = cenario
    r = _processar_query(QueryIn(question="o que é o vatapá?", mode="rag",
                                 collections=["c"]))
    assert r["mode"] == "rag"
    # resposta = digest dos fragmentos (não síntese de LLM)
    assert "vatapá" in r["answer"] and "**1**" in r["answer"]
    # header de chunk é metadado de indexação — não aparece na resposta
    assert "[vatapá passo a passo]" not in r["answer"]
    assert len(r["docs"]) == 2


def test_hibrido_mantem_o_ciclo_de_energia(cenario, monkeypatch):
    """O pulo do garantir_llm é SÓ do rag: híbrido segue acordando o modelo
    na estação (ciclo de energia 10/09) e gerando com a LLM."""
    base, rag = cenario
    chamadas = []
    monkeypatch.setattr(base.modelos, "garantir_llm",
                        lambda log=None: chamadas.append(1))
    monkeypatch.setattr(base.grafo, "rotear",
                        lambda *a, **kw: {"rota": "fluxo", "tipo": "",
                                          "motivo": "teste"})
    # no híbrido os caminhos de LLM são LEGÍTIMOS (é o modo com modelo):
    # reformulação vira identidade e a geração é mockada
    monkeypatch.setattr(rag, "reformula", lambda q, h: q)
    monkeypatch.setattr(rag, "answer_hybrid",
                        lambda *a, **kw: "síntese do modelo")
    r = _processar_query(QueryIn(question="o que é o vatapá?",
                                 mode="hibrido", collections=["c"]))
    assert chamadas == [1]              # acordou (por design)
    assert r["answer"] == "síntese do modelo"


def test_rag_puro_frago_nao_zera_a_base(cenario, monkeypatch):
    """top abaixo do SCORE_FRACO: o descarte protege o PROMPT da LLM
    (contexto fraco = alucinação) — no rag puro não há prompt, o material
    recuperado É a resposta (validado ao vivo: 'receita de frango' trazia
    4 fragmentos reais e o guardrail zerava tudo)."""
    base, rag = cenario
    monkeypatch.setattr(base.config, "SCORE_FRACO", 0.55)
    fracos = [(_doc("Fragmento medíocre sobre culinária."), 0.50, "c"),
              (_doc("Outro fragmento medíocre."), 0.48, "c")]
    monkeypatch.setattr(rag, "search", lambda *a, **kw: (fracos, {}))
    monkeypatch.setattr(base.rerank, "rerank", lambda *a, **kw: None)
    # rerank indisponível NÃO é "sem sinal" — notas None = não olhou
    monkeypatch.setattr(base.rerank, "notas_de", lambda *a, **kw: None)
    r = _processar_query(QueryIn(question="o que é o vatapá?", mode="rag",
                                 collections=["c"]))
    assert len(r["docs"]) == 2            # nada descartado: a base responde
    assert "culinária" in r["answer"]
    assert "Nada na base responde" not in r["answer"]  # sem aviso indevido


def test_rag_puro_sem_sinal_avisa_em_vez_de_responder_outro_assunto(
        cenario, monkeypatch):
    """Caso real do dono 12/09 ("receita de frango" → churrasco/picanha):
    o reranker bilíngue OLHOU os fragmentos e nenhum é relevante → a
    resposta AVISA que a base não cobre a pergunta (o material segue
    visível, como referência — não como resposta)."""
    base, rag = cenario
    monkeypatch.setattr(base.rerank, "rerank", lambda *a, **kw: None)
    monkeypatch.setattr(base.rerank, "notas_de",
                        lambda *a, **kw: [0.020, 0.023])
    r = _processar_query(QueryIn(question="receita de frango", mode="rag",
                                 collections=["c"]))
    assert r["answer"].startswith("⚠️")   # aviso na frente…
    assert "Nada na base responde" in r["answer"]
    assert "vatapá" in r["answer"]        # …material segue como referência


def test_digest_rag_sanitiza_recorta_e_numera():
    """Pedido do dono 12/09: '<sup> aparecendo', fragmento-monstro inteiro e
    resposta de outra pergunta — o digest limpa detritos de citação, cabeça
    com o TÍTULO e recorta o parágrafo mais parecido com a pergunta."""
    from core import rag
    gigante = (
        "A cozinha da região Norte do Brasil reúne pratos típicos e "
        "tradições indígenas de vários estados amazônicos. " * 12 + "\n\n"
        "O vatapá é um prato paraense à base de dendê, pão e camarão seco, "
        "servido com arroz branco e farinha.<sup> </sup>\n\n"
        "Sobremesas regionais variam de cidade a cidade e seguem receitas "
        "de família passadas de geração em geração. " * 8
    )
    docs = [
        Document(page_content="[vatapá passo a passo]\n" + gigante,
                 metadata={"colecao": "culinaria", "titulo": "Vatapá"}),
        Document(page_content="", metadata={}),  # vazio não ocupa número
    ]
    out = rag.digest_rag("o que é o vatapá?", docs)
    assert "<sup>" not in out                     # detrito de citação fora
    assert "[vatapá passo a passo]" not in out    # header de chunk fora
    assert "**1 · Vatapá**" in out                # título no cabeçalho
    assert "culinaria" in out                     # coleção no cabeçalho
    assert "prato paraense" in out                # recortou o parágrafo CERTO
    assert "Sobremesas regionais" not in out      # …não o trecho inteiro
    assert "**2" not in out                       # vazio não ganhou número
