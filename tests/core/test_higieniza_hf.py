"""🧹 Higiene do dump HF ("[linha N] campo: v | campo: v | … | text: …").

Case real do dono 12/09: a resposta de "Como desenvolvo uma api em dotnet?"
abria com dumps de metadados de datasets (repo_name, sha256, collected_at…)
— o core/hf.py antigo serializava TODAS as colunas da linha no
page_content. A função `limpar_dump_hf` limpa o que já está gravado (e
blinda o digest); o `hf.dados` NOVO grava só o conteúdo.
"""
from types import SimpleNamespace

from core.limpeza import (limpar_dump_hf, reparar_enfase,
                          reparar_enfase_traduzida)

_DUMP = (
    "# codeparrot/github-code · default/train (linhas 401–402)\n"
    "[linha 407] repo_name: dotnet/examples | path: tests/Program.cs | "
    "content_sha256: 9f2c1e | category_slice: test | collected_at: 2026-07-17 | "
    "text: using System;\nusing System.Collections.Generic;\n\n"
    "var api = WebApplication.CreateBuilder(args);\n"
    "api.MapGet(\"/\", () => \"hello\");\n"
    "[linha 408] repo_name: dotnet/examples | path: tests/Outro.cs | "
    "content_sha256: aa11bb | category_slice: test | collected_at: 2026-07-17 | "
    "text: // arquivo vazio de teste\n"
)


def test_remove_o_dump_e_preserva_o_conteudo():
    limpo = limpar_dump_hf(_DUMP)
    # metadados: fora (não poluem embedding nem resposta)
    for sujo in ("repo_name:", "content_sha256:", "collected_at:",
                 "category_slice:", " | "):
        assert sujo not in limpo, f"{sujo!r} deveria ter saído"
    # conteúdo: preservado (é o material da base)
    assert "using System.Collections.Generic;" in limpo
    assert 'api.MapGet("/", () => "hello");' in limpo
    assert "// arquivo vazio de teste" in limpo
    # cabeçalho do documento + procedência compacta
    assert limpo.startswith("# codeparrot/github-code · default/train")
    assert "[linha 407] dotnet/examples · tests/Program.cs" in limpo


def test_codigo_com_pipe_dentro_do_conteudo_nao_e_cortado():
    """Código TEM " | " (bitwise ou, shell) — o corte é no primeiro campo de
    CONTEÚDO; pipes DEPOIS dele pertencem ao conteúdo."""
    texto = ("[linha 3] repo_name: a/b | path: x.py | text: "
             "flag = a | b\nprint('ok | yes: no')\n")
    limpo = limpar_dump_hf(texto)
    assert "flag = a | b" in limpo
    assert "print('ok | yes: no')" in limpo
    assert "repo_name" not in limpo


def test_formato_desconhecido_volta_intacto():
    """Sem marcador "[linha N]" ou sem campo de conteúdo reconhecível, o
    texto sai IGUAL — a higiene nunca corrói formato que não entende."""
    prosa = "O tucupi é um caldo amarelo extraído da mandioca brava.\n"
    assert limpar_dump_hf(prosa) == prosa
    so_meta = "[linha 9] repo_name: a/b | path: x | collected_at: 2026-07\n"
    assert limpar_dump_hf(so_meta) == so_meta


def test_e_idempotente():
    """Limpar 2× = limpar 1× (a higienização pode rodar de novo na coleção)."""
    uma = limpar_dump_hf(_DUMP)
    assert limpar_dump_hf(uma) == uma


# ---------- ênfase colada (trafilatura perde os espaços de <strong>) --------
# Bug real do dono 13/09: "select**New** >**Project**" renderiza "selectNew
# >Project" — o `**` vira <strong> no markdown e engole a borda.

def test_reparar_enfase_espaca_as_bordas_do_negrito():
    fixo = reparar_enfase("From the File menu, select**New** >**Project** .")
    assert "select **New**" in fixo
    assert "> **Project**" in fixo
    assert "select**New**" not in fixo


def test_reparar_enfase_nao_toca_em_bloco_de_codigo():
    """`**` DENTRO de cerca é sintaxe (potência em python, comment block em
    C/JS) — o reparo é fence-aware, a cerca sai intacta."""
    c = ("texto com**ênfase**colada\n\n```python\nx = x**2 + y**2\n"
         "doc = /** nota */\n```")
    fixo = reparar_enfase(c)
    assert "x = x**2 + y**2" in fixo          # dentro da cerca: intocado
    assert "com **ênfase** colada" in fixo    # fora da cerca: reparado


def test_reparar_enfase_sem_negrito_volta_intacto():
    """Texto sem `**` (o caso comum) sai IGUAL — e é idempotente."""
    prosa = "O tucupi é um caldo amarelo extraído da mandioca brava.\n"
    assert reparar_enfase(prosa) == prosa
    ja_ok = "selecione **Novo** > **Projeto**"
    assert reparar_enfase(ja_ok) == ja_ok   # já espaçado: não duplica espaço


# ---------- ênfase desalinhada pela TRADUÇÃO (opus-mt move os espaços) ------
# Caso real ao vivo 13/09: "select **New** >" voltou do tradutor como
# "selecione **Novo **>" — espaço na borda INTERNA mata o negrito no
# CommonMark (o ** aparece cru na resposta).

def test_reparar_enfase_traduzida_aperta_borda_interna():
    fixo = reparar_enfase_traduzida(
        "No menu **File **, selecione **Novo **> **Project** .")
    assert "**File**," in fixo
    assert "**Novo** > **Project**" in fixo
    assert "**Novo **" not in fixo       # cerca interna nunca com espaço


def test_reparar_enfase_traduzida_italico_e_borda_externa():
    fixo = reparar_enfase_traduzida(
        "nomeie o projeto*EndoApi* e confirme o termo*importante*.")
    assert "projeto *EndoApi* e" in fixo        # borda externa espaçada
    assert "termo *importante*." in fixo        # pontuação final anexa
    assert "projeto*EndoApi*" not in fixo


def test_reparar_enfase_traduzida_nao_confunde_multiplicacao():
    """Asterisco literal de multiplicação não vira ênfase — e cerca de
    código continua verbatim."""
    orig = "calcule a * b e * c\n\n```python\nx = a * b * c\n```"
    fixo = reparar_enfase_traduzida(orig)
    assert fixo == orig                   # nada de ênfase aqui: idêntico


def test_higienizar_colecao_reembeda_o_dump_no_mesmo_id(monkeypatch):
    """A passada corretiva: chunk de CÓDIGO com dump sai re-embedado no
    MESMO id com o texto limpo; código limpo e prosa seguem intactos."""
    from core import higieniza, rag
    from langchain_core.documents import Document  # noqa: F401 — ambiente

    dump = ("[linha 1] repo_name: x/y | path: a.cs | text: "
            "using System;\nclass A {}\n")
    codigo_limpo = "def soma(a, b):\n    return a + b\n"
    prosa = ("O vatapá é um prato paraense à base de dendê, pão e camarão "
             "seco, servido com arroz branco. É um dos pratos mais "
             "conhecidos da culinária afro-brasileira do Norte do Brasil, "
             "apreciado em festas religiosas e do cotidiano.") * 2

    pontos = [
        SimpleNamespace(id="p1", payload={
            "page_content": dump, "metadata": {"camada": "codigo"}}),
        SimpleNamespace(id="p2", payload={
            "page_content": codigo_limpo,
            "metadata": {"camada": "codigo", "arquivo": "soma.py"}}),
        SimpleNamespace(id="p3", payload={
            "page_content": prosa, "metadata": {"camada": "prosa"}}),
    ]

    class _ClientFake:
        def __init__(self):
            self.upserts = []

        def collection_exists(self, nome):
            return True

        def scroll(self, collection_name, limit, with_payload,
                   with_vectors, offset=None, **kw):
            return (pontos, None) if offset is None else ([], None)

        def upsert(self, collection_name, points):
            self.upserts.extend(points)

        def delete(self, **kw):
            raise AssertionError("nada deveria ser apagado neste cenário")

        def count(self, colecao, exact=True):
            return SimpleNamespace(count=len(pontos))

    cliente = _ClientFake()
    monkeypatch.setattr(higieniza, "QdrantClient", lambda **kw: cliente)
    monkeypatch.setattr(rag, "embeddings",
                        lambda: SimpleNamespace(
                            embed_documents=lambda ts: [[0.1] * 8] * len(ts)))
    resumo = higieniza.higienizar_colecao("dotnet", log=lambda *a, **kw: None)

    assert resumo["reembedados"] == 1            # só o chunk com dump
    [ponto] = cliente.upserts
    assert ponto.id == "p1"                       # mesmo id (in-place)
    assert "repo_name" not in ponto.payload["page_content"]
    assert "using System;" in ponto.payload["page_content"]
    assert resumo["apagados_ruido"] == 0


def test_hf_dados_grava_so_o_conteudo(monkeypatch):
    """Preventivo: o formato NOVO de hf.dados() não serializa mais as
    colunas de metadado no page_content — o maior campo é o conteúdo, o
    resto vira procedência de uma linha; dataset/config/split vão para a
    metadata do Document."""
    from core import hf

    class _Resp:
        status_code = 200

        def __init__(self, payload):
            self._p = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._p

    def _fake_get(url, params=None, **kw):
        if url.endswith("/splits"):
            return _Resp({"splits": [{"config": "default", "split": "train"}]})
        if (params or {}).get("offset", 0) > 0:   # fim da paginação
            return _Resp({"rows": []})
        return _Resp({"rows": [
            {"row": {"repo_name": "dotnet/examples", "path": "A.cs",
                     "content_sha256": "9f2c", "text": "using System;"}},
            {"row": {"repo_name": "dotnet/examples", "path": "B.cs",
                     "content_sha256": "aa11",
                     "text": "Console.WriteLine(\"oi\");"}},
        ]})

    monkeypatch.setattr(hf.httpx, "get", _fake_get)
    docs = hf.dados("dotnet/examples", max_linhas=10,
                    log=lambda *a, **kw: None)
    assert len(docs) == 1
    texto = docs[0].page_content
    assert " | " not in texto                    # dump de pipes: nunca mais
    assert "repo_name" not in texto
    assert "[linha 1] dotnet/examples · A.cs" in texto
    assert "using System;" in texto
    assert 'Console.WriteLine("oi");' in texto
    md = docs[0].metadata
    assert md["dataset"] == "dotnet/examples"
    assert md["config"] == "default" and md["split"] == "train"
