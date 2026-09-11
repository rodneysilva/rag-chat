"""Consolidação na ingestão (spec core/specs/consolidacao.md, pedido do
dono 12/09: "antes de incluir qualquer item no Qdrant, verificar se já tem
a informação, e se tiver, consolidar; se não tiver, acrescentar").

Semelhante ≥ CONSOLIDA_SCORE funde no ponto existente (sentenças novas
anexadas, metadata completada, mesmo id); idêntico → inalterado; novo → id
determinístico (reingestão sobrepõe, não empilha). Código nunca funde."""
import pytest
from langchain_core.documents import Document

from core import consolida


class _EmbedFake:
    """Embedding de mentira: vetor estável por texto (mesmo texto = mesmo
    vetor — suficiente para o motor, que só compara no fake do Qdrant)."""

    def embed_documents(self, textos):
        return [[float(len(t) % 97), 0.5, 0.5, 0.5] for t in textos]

    def embed_query(self, texto):
        return [float(len(texto) % 97), 0.5, 0.5, 0.5]


class _Ponto:
    def __init__(self, pid, score, payload):
        self.id, self.score, self.payload = pid, score, payload


class _ClientFake:
    """Qdrant de mentira: coleção 'c' com UM ponto de maniçoba; a busca
    devolve o score configurado (o teste decide se é semelhante ou não)."""

    def __init__(self, score=0.94):
        self.score = score
        self.pontos = {"fixo-1": {
            "page_content": "[O que é: maniçoba]\nA maniçoba é um prato "
                            "paraense de folhas de mandioca cozidas por "
                            "quatro dias. É servida com arroz e carne.",
            "metadata": {"titulo": "maniçoba", "arquivo": "manicoba.md"}}}
        self.upserts = []

    def collection_exists(self, nome):
        return nome == "c"

    def query_points(self, collection_name, query, limit=3,
                     with_payload=True):
        pts = [_Ponto(pid, self.score, dict(payload))
               for pid, payload in self.pontos.items()]

        class _R:
            points = pts
        return _R()

    def upsert(self, collection_name, points):
        for p in points:
            self.pontos[str(p.id)] = {"page_content": p.payload["page_content"],
                                      "metadata": dict(p.payload["metadata"])}
        self.upserts.append(list(points))

    def count(self, collection_name):
        class _C:
            count = len(self.pontos)
        return _C()


@pytest.fixture
def embeddings(monkeypatch):
    from core import rag
    monkeypatch.setattr(rag, "embeddings", lambda: _EmbedFake())


def _chunk(txt, **meta):
    return Document(page_content=txt, metadata={"titulo": "maniçoba",
                                                "arquivo": "nova_fonte.md",
                                                **meta})


def test_fundir_textos_anexa_apenas_sentencas_novas():
    base = ("[O que é: maniçoba]\nA maniçoba é prato paraense. É servida "
            "com arroz.")
    novo = ("[O que é: maniçoba]\nA maniçoba é prato paraense. Leva folhas "
            "de mandioca cozidas por dias.")
    out, novas = consolida.fundir_textos(base, novo, limite=2000)
    assert novas == 1                                  # só a frase nova entra
    assert out.startswith("[O que é: maniçoba]")       # header da base fica
    assert "prato paraense. É servida com arroz." in out
    assert "folhas de mandioca" in out


def test_id_deterministico_estavel_por_conteudo():
    a = consolida._id_deterministico("culinaria", "mesmo texto")
    b = consolida._id_deterministico("culinaria", "mesmo  texto\n")  # ws ok
    c = consolida._id_deterministico("culinaria", "outro texto")
    d = consolida._id_deterministico("outra_colecao", "mesmo texto")
    assert a == b                       # reingestão do mesmo material…
    assert a != c and a != d            # …só não é o mesmo se muda algo


def test_semelhante_funde_no_mesmo_id(embeddings):
    client = _ClientFake(score=0.94)
    logs = []
    res = consolida.consolidar(client, "c", [
        _chunk("[O que é: maniçoba]\nA maniçoba também leva paçoca de "
               "castanha no acompanhamento.")], log=logs.append)
    assert res["consolidados"] == 1 and res["novos"] == 0
    # mesmo id do ponto existente — nada novo foi criado
    assert [str(p.id) for lote in client.upserts for p in lote] == ["fixo-1"]
    payload = client.pontos["fixo-1"]
    assert "paçoca de castanha" in payload["page_content"]   # complementou
    assert payload["metadata"]["atualizado_em"]              # alteração datada
    assert payload["metadata"]["consolidacoes"] == 1
    assert "nova_fonte.md" in payload["metadata"]["origens_extras"]
    # saída padrão (regra 6): resumo no formato fixo
    assert any("📥 saída:" in l for l in logs)


def test_identico_e_inalterado_nada_grava(embeddings):
    client = _ClientFake(score=0.97)
    mesmo = ("[O que é: maniçoba]\nA maniçoba é um prato paraense de folhas "
             "de mandioca cozidas por quatro dias. É servida com arroz e "
             "carne.")
    res = consolida.consolidar(client, "c", [_chunk(mesmo)])
    assert res["inalterados"] == 1 and client.upserts == []


def test_codigo_nunca_funde_no_meio(embeddings):
    client = _ClientFake(score=0.95)
    res = consolida.consolidar(client, "c", [
        _chunk("print('hello world')", camada="codigo")])
    assert res["inalterados"] == 1 and client.upserts == []


def test_informacao_nova_ganha_id_deterministico(embeddings):
    client = _ClientFake(score=0.40)
    pedaco = _chunk("[O que é: tucupi]\nO tucupi é um caldo amarelo da "
                    "mandioca brava.")
    res = consolida.consolidar(client, "c", [pedaco])
    assert res["novos"] == 1
    pid = str(client.upserts[0][0].id)
    assert pid != "fixo-1"
    # reingestão do MESMO material sobrepõe (mesmo id) — não empilha
    client2 = _ClientFake(score=0.40)
    consolida.consolidar(client2, "c", [pedaco])
    assert str(client2.upserts[0][0].id) == pid
    # padrão de metadata (regra 5): criado_em/atualizado_em presentes
    md = client.pontos[pid]["metadata"]
    assert md.get("criado_em") and md.get("atualizado_em")


def test_palavras_vivem_na_spec_nao_no_codigo():
    """Regra do projeto: o texto exibido vem da spec — a linha existe e o
    {campo} é substituído (mesmo padrão do tradutor)."""
    from core.specs import valor
    for chave in ("MSG_INICIO", "MSG_CONSOLIDANDO", "MSG_NOVO", "MSG_SAIDA"):
        assert valor("consolidacao", chave), f"{chave} sumiu da spec"
    saida = valor("consolidacao", "MSG_SAIDA")
    assert "{novos}" in saida and "{colecao}" in saida


def test_dividir_gera_header_padrao_e_metadata():
    """Regra 5 da spec consolidacao.md: todo pedaço nasce com o cabeçalho
    '[O que é: … · Para que serve: … · parte i/n]' na 1ª linha (viaja no
    embedding) e o_que_e/pra_que_serve na metadata."""
    from core import ingest
    texto = ("A maniçoba é um prato típico do estado do Pará, no norte do "
             "Brasil. As folhas da mandioca brava são moídas e cozidas por "
             "quatro dias para perder o ácido cianídrico. Depois do cozido "
             "longo, o caldo ganha carnes de porco e charque, paçoca de "
             "castanha e goma. O prato é servido com arroz branco e farinha "
             "de mandioca, especialmente nas festas de Belém.")
    doc = Document(page_content=texto, metadata={
        "source": "mani.md", "arquivo": "mani.md", "titulo": "Maniçoba",
        "descricao": "prato típico do Pará"})
    chunks = ingest._dividir([doc], lambda *a: None)
    c = chunks[0]
    assert c.page_content.startswith(
        "[O que é: Maniçoba · Para que serve: prato típico do Pará · parte 1/")
    assert c.page_content.split("\n", 1)[0].endswith("]")
    assert c.metadata["o_que_e"] == "Maniçoba"
    assert c.metadata["pra_que_serve"] == "prato típico do Pará"
