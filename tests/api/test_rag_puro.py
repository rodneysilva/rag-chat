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
    SCORE_DIRETO e acima do FRACO — nem resposta-direta, nem descarte).

    🎯 CONSULTA CONSOLIDADA (spec consulta_consolidada.md): o mode do
    QueryIn NÃO decide mais nada — o fixture liga o RAG e DESLIGA a LLM
    (modo efetivo rag) e fixa o escopo em 'c' (RAG_COLECOES). Testes
    híbridos religam LLM_ATIVO no próprio corpo."""
    from api import base
    from core import rag, modelos, idioma

    monkeypatch.setattr(base.config, "RAG_ATIVO", True)
    monkeypatch.setattr(base.config, "LLM_ATIVO", False)
    monkeypatch.setattr(base.config, "RAG_COLECOES", "c")
    monkeypatch.setattr(base.config, "MCP_ATIVOS", "")
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
    monkeypatch.setattr(base.config, "LLM_ATIVO", True)  # modo efetivo: híbrido
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


def test_rag_puro_digest_inclui_paginas_da_web(cenario, monkeypatch):
    """Bug real do dono 12/09 ("não está considerando a pesquisa que fiz na
    web"): as páginas baixadas eram anexadas DEPOIS dos fragmentos da base e
    o digest (limite 4) as descartava — segundos de download invisíveis.
    Agora o rerank pontua base+web JUNTOS e o digest segue a ordem dele."""
    base, rag = cenario
    # 🎯 pesquisa-web ativa pela CONFIG (MCP_ATIVOS), não pelo payload —
    # o mcps do QueryIn é ignorado pela consulta consolidada
    monkeypatch.setattr(base.config, "MCP_ATIVOS", base.MCP_WEB)

    def _rerank(pergunta, achados, top_n=4, log=None, **kw):
        # a página da web (anexada por ÚLTIMO) é a mais relevante
        return list(reversed(achados))[:top_n], 0.9
    monkeypatch.setattr(base.rerank, "rerank", _rerank)
    web = [_doc("Receita de arroz com jambu e tucupi passo a passo.")]
    monkeypatch.setattr(base, "_web_aprofundado", lambda *a, **kw: web)
    r = _processar_query(QueryIn(question="E arroz com tucupi?", mode="rag",
                                 collections=["c"], mcps=[base.MCP_WEB]))
    assert "arroz com jambu" in r["answer"]            # a página aparece…
    assert r["answer"].index("arroz com jambu") < r["answer"].index("vatapá")
    assert not r["answer"].startswith("⚠️")             # web trouxe sinal


def test_digest_traduz_trecho_e_titulo_de_fragmento_em_ingles(monkeypatch):
    """Pedido do dono 12/09 ("o retorno tem partes em português e outras em
    inglês"): pergunta PT + trecho EN → sai em PT via opus-mt, marcado;
    título com slug de URL é decodificado E traduzido. O original não vaza."""
    from core import rag, tradutor

    def _fake_lote(textos, **kw):
        assert "traditional dish" in textos[0]          # trecho primeiro…
        assert "Cuisine of Pará" in textos[1]           # …título depois
        return ["O vatapá é um prato tradicional do Pará, com dendê.",
                "Cozinha do Pará"]
    monkeypatch.setattr(tradutor, "traduzir_lote", _fake_lote)
    docs = [Document(
        page_content="Vatapá is a traditional dish from the state of Pará, "
                     "made with dendê palm oil, bread and dried shrimp, "
                     "served with white rice.",
        metadata={"colecao": "culinaria", "titulo": "Cuisine_of_Par%C3%A1"})]
    out = rag.digest_rag("o que é o vatapá?", docs)
    assert "prato tradicional do Pará" in out
    assert "Cozinha do Pará" in out
    assert "*(traduzido)*" in out
    assert "Vatapá is" not in out


def test_digest_nao_traduz_titulo_portugues_sem_evidencia_de_ingles(
        monkeypatch):
    """'Tucupi — síntese' não tem palavra funcional nenhuma — a contagem
    PT×EN empata e traduzir seria PIOR que deixar como está (só título com
    evidência real de inglês entra no lote)."""
    from core import rag, tradutor
    chamadas = []
    monkeypatch.setattr(tradutor, "traduzir_lote",
                        lambda ts, **kw: chamadas.extend(ts) or ["x"] * len(ts))
    docs = [Document(page_content="O tucupi é um caldo amarelo extraído da "
                                  "mandioca brava, típico do Pará.",
                     metadata={"colecao": "c", "titulo": "Tucupi — síntese"})]
    out = rag.digest_rag("o que é tucupi?", docs)
    assert "caldo amarelo" in out
    assert "*(traduzido)*" not in out
    assert chamadas == []                     # nada foi enviado ao modelo


def test_resposta_direta_de_pedido_de_codigo_e_o_bloco(cenario, monkeypatch):
    """Regra 3 da spec rag_puro.md na RESPOSTA DIRETA (visto ao vivo
    12/09: "hello world em python" com top 0.673 ≥ SCORE_DIRETO devolvia a
    prosa INTEIRA do fragmento) — pedido de código devolve o BLOCO verbatim."""
    base, rag = cenario
    monkeypatch.setattr(base.config, "SCORE_DIRETO", 0.5)
    doc = _doc("Guia rápido de Python para começar. O primeiro programa "
               "é o hello world.\n\n```python\nprint(\"hello world\")\n```")
    monkeypatch.setattr(rag, "search",
                        lambda *a, **kw: ([(doc, 0.67, "c")], {}))
    r = _processar_query(QueryIn(question="hello world em python",
                                 mode="rag", collections=["c"]))
    assert 'print("hello world")' in r["answer"]
    assert "```python" in r["answer"]
    assert "Guia rápido" not in r["answer"]   # só o bloco, sem a prosa


def test_digest_pedido_de_codigo_extrai_bloco_da_base(monkeypatch):
    """Pedido do dono 12/09 ("hello world em qualquer linguagem com base no
    que tenho no qdrant, sem recorrer a llm"): a pergunta pede código e o
    fragmento TEM bloco cercado → o bloco entra INTEIRO e VERBATIM —
    EXTRAÇÃO da base, jamais geração. E bloco NÃO vai ao tradutor."""
    from core import rag, tradutor

    def _boom(*a, **kw):
        raise AssertionError("bloco de código foi enviado ao tradutor")
    monkeypatch.setattr(tradutor, "traduzir_lote", _boom)
    doc = Document(
        page_content="Exemplo clássico de primeiro programa em Python.\n\n"
                     '```python\nprint("hello world")\n```',
        metadata={"colecao": "python", "titulo": "Primeiro programa"})
    out = rag.digest_rag("hello world em python", [doc])
    assert 'print("hello world")' in out      # verbatim, extraído da base
    assert "```python" in out                 # cerca preservada (vira card)


def test_digest_codigo_puro_vira_bloco_cercado_da_linguagem():
    """Arquivo de código INTEIRO ingerido (camada codigo, sem cerca no
    texto): pedido de código entrega o trecho CERCADO na linguagem do
    arquivo — card de código na webui, não prosa solta."""
    from core import rag
    doc = Document(page_content='def ola():\n    print("hello world")',
                   metadata={"colecao": "python", "titulo": "ola.py",
                             "camada": "codigo", "arquivo": "ola.py",
                             "linguagem": "Python"})
    out = rag.digest_rag("me mostre um hello world em python", [doc])
    assert "```" in out and 'print("hello world")' in out


def test_digest_mostra_o_que_e_do_padrao_de_ingestao():
    """Regra 1 da spec rag_puro.md: a metadata do PADRÃO de ingestão
    (spec consolidacao.md) traz o_que_e — subtítulo do fragmento quando
    difere do título."""
    from core import rag
    doc = Document(
        page_content="O vatapá é um prato paraense à base de dendê.",
        metadata={"colecao": "culinaria", "titulo": "Vatapá",
                  "o_que_e": "Vatapá · Origem e preparo"})
    out = rag.digest_rag("o que é o vatapá?", [doc])
    assert "*Vatapá · Origem e preparo*" in out


def test_aviso_sem_sinal_vive_na_spec():
    """Regra do projeto: palavras ao usuário na spec (rag_puro.md), com o
    "\\n" da linha virando quebra real."""
    from core.specs import valor
    msg = valor("rag_puro", "MSG_SEM_SINAL")
    assert msg.startswith("⚠️") and "Nada na base" in msg
    assert "\n\nO material" in msg          # \n da spec vira quebra real


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
                 metadata={"colecao": "culinaria", "area": "cozinha regional",
                           "titulo": "Vatapá"}),
        Document(page_content="", metadata={}),  # vazio não ocupa número
    ]
    out = rag.digest_rag("o que é o vatapá?", docs)
    assert "<sup>" not in out                     # detrito de citação fora
    assert "[vatapá passo a passo]" not in out    # header de chunk fora
    assert "**1 · Vatapá**" in out                # título no cabeçalho
    assert "cozinha regional" in out              # ÁREA no cabeçalho…
    assert "culinaria" not in out                 # …coleção NÃO (regra 6)
    assert "prato paraense" in out                # recortou o parágrafo CERTO
    assert "Sobremesas regionais" not in out      # …não o trecho inteiro
    assert "**2" not in out                       # vazio não ganhou número
