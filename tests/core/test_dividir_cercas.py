"""CORE · _dividir/_secoes_md — split de ingestão com cercas ATÔMICAS.

Regra 8 da spec rag_puro.md (verbatim em cadeia): nenhum chunk corta dentro
de bloco ```; cabeçalhos markdown só cortam na prosa (o
MarkdownHeaderTextSplitter da langchain colapsava TABS do código — bug que
este split próprio mata). Determinístico: sem rede, sem Qdrant.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langchain_core.documents import Document  # noqa: E402

from core import config  # noqa: E402
from core.ingest import _dividir, _secoes_md  # noqa: E402


def _doc(texto: str, arquivo: str = "teste.md") -> Document:
    return Document(page_content=texto,
                    metadata={"source": arquivo, "arquivo": arquivo,
                              "titulo": "Documento de teste"})


_PROSA = ("A explicação detalhada do recurso acompanha cada passo do exemplo "
          "com contexto suficiente para o embedding entender o assunto. ")


class TestSplitarComCercas:
    def test_cerca_maior_que_chunk_size_fica_inteira(self):
        cerca = "```python\n" + "x = 1\ny = x + 2\n\n" * 400 + "```"
        assert len(cerca) > config.CHUNK_SIZE
        chunks = _dividir([_doc(_PROSA * 20 + "\n\n" + cerca)], lambda m: None)
        alvo = [c for c in chunks if "x = 1" in c.page_content]
        assert len(alvo) == 1                       # cerca em UM chunk só
        assert alvo[0].page_content.count("```") == 2
        assert len(alvo[0].page_content) > config.CHUNK_SIZE   # maior, mas inteira

    def test_cerca_com_linha_em_branco_nao_e_cortada(self):
        """O caso reproduzido: '\n\n' interno da cerca era ponto de corte do
        recursive splitter — chunk nascia com cerca ABERTA."""
        cerca = "```go\nfunc A() {\n\n\treturn 1\n\n}\n```"
        doc = _doc(_PROSA * 30 + "\n\n" + cerca + "\n\n" + _PROSA * 30)
        for c in _dividir([doc], lambda m: None):
            assert c.page_content.count("```") % 2 == 0, "cerca picada!"

    def test_prosa_adjacente_e_splitada_normal(self):
        cerca = "```js\nconsole.log('oi');\n```"
        doc = _doc(_PROSA * 60 + "\n\n" + cerca + "\n\n" + _PROSA * 60)
        chunks = _dividir([doc], lambda m: None)
        assert len(chunks) > 1                       # prosa longa gera pedaços
        assert all(c.page_content.startswith("[") for c in chunks)  # header padrão
        assert chunks[0].metadata["i"] == 1 and "n" in chunks[0].metadata

    def test_prosa_curta_e_cerca_juntas_quando_cabem(self):
        cerca = ("```python\nnome = input('como voce se chama? ')\n"
                 "print('hello world,', nome)\nprint('tchau', nome)\n```")
        doc = _doc(_PROSA * 2 + "\n\n" + cerca)
        chunks = _dividir([doc], lambda m: None)
        assert len(chunks) == 1                      # cabe tudo: um chunk

    def test_dividir_e_deterministico(self):
        cerca = "```python\nfor i in range(10):\n\tprint(i)\n```"
        doc = _doc(_PROSA * 10 + "\n\n" + cerca + "\n\n" + _PROSA * 10)
        a = _dividir([doc], lambda m: None)
        b = _dividir([_doc(_PROSA * 10 + "\n\n" + cerca + "\n\n" + _PROSA * 10)],
                     lambda m: None)
        assert [c.page_content for c in a] == [c.page_content for c in b]

    def test_tabs_do_codigo_sobrevivem_ao_split(self):
        """Regressão do MarkdownHeaderTextSplitter: ele colapsava '\t' do
        código das seções — _secoes_md devolve byte a byte."""
        cerca = ("```go\nfunc main() {\n\tr := gin.Default()\n"
                 "\t\tr.GET(\"/ola\", func(c *gin.Context) {\n"
                 "\t\t\tc.JSON(http.StatusOK, gin.H{\"msg\": \"oi\"})\n"
                 "\t\t})\n\tr.Run(\":8080\")\n}\n```")
        doc = _doc("# Título\n\n## Seção\n\n" + _PROSA * 2 + "\n\n" + cerca)
        chunks = _dividir([doc], lambda m: None)
        pc = [c for c in chunks if "gin.Default" in c.page_content][0].page_content
        assert '\n\tr := gin.Default()' in pc
        assert '\n\t\tr.GET("/ola", func(c *gin.Context) {' in pc


class TestSecoesMd:
    def test_hierarquia_cumulativa(self):
        txt = ("# Título\n\nintro.\n\n## Seção A\n\nprosa a.\n\n"
               "### Sub A1\n\nprosa sub.\n\n## Seção B\n\nfinal.")
        secs = _secoes_md(txt)
        assert [s.metadata for s in secs] == [
            {"h1": "Título"},
            {"h1": "Título", "h2": "Seção A"},
            {"h1": "Título", "h2": "Seção A", "h3": "Sub A1"},
            {"h1": "Título", "h2": "Seção B"},
        ]

    def test_cerco_de_cabecalho_dentro_de_cerca_nao_corta(self):
        cerca = "```bash\n# comentario que NAO e cabecalho\ncd /tmp\n```"
        secs = _secoes_md("## Real\n\nprosa.\n\n" + cerca + "\n\nfim.")
        assert len(secs) == 1                        # 1 seção: cerca não cortou
        assert "# comentario que NAO e cabecalho" in secs[0].page_content

    def test_h4_nao_e_ponto_de_corte(self):
        secs = _secoes_md("## A\n\nprosa.\n\n#### detalhe\n\nmais prosa.")
        assert len(secs) == 1
