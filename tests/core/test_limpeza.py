"""CORE · limpeza — o pipeline de texto (usado por ingest/seed/preview).

Cobertura: normalização, remoção de infobox de wiki, detecção de lixo.
Determinístico: nenhuma rede, nenhuma LLM.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.limpeza import e_lixo, limpar_texto, _remover_tabelas_inuteis  # noqa: E402


class TestRemoverTabelasInuteis:
    def test_infobox_wiki_sai(self):
        """Infobox com células vazias/rótulos curtos é removida."""
        infobox = (
            "| *Theobroma cacao* | |\n"
            "| Kingdom: | Plantae |\n"
            "| *Clade* : | Embryophytes |\n"
            "| Order: | Malvales |\n"
            "| Family: | Malvaceae |\n"
            "| Genus: | *Theobroma* |\n"
            "| Binomial name | |\n")
        assert _remover_tabelas_inuteis(infobox).strip() == ""

    def test_tabela_de_dado_fica(self):
        """Tabela com conteúdo real (docs/comandos) sobrevive."""
        dado = ("| comando | o que faz |\n"
                "| dotnet build | compila a solucao completa |\n"
                "| dotnet run | executa o projeto |")
        assert _remover_tabelas_inuteis(dado) == dado

    def test_texto_sem_tabela_intacto(self):
        t = "paragrafo comum\nsem tabela nenhuma"
        assert _remover_tabelas_inuteis(t) == t


class TestLimparTexto:
    def test_idempotente(self):
        """Limpar 2x == limpar 1x (contrato do pipeline)."""
        t = "texto comum de documento.\n" * 5
        assert limpar_texto(limpar_texto(t)) == limpar_texto(t)

    def test_vazio(self):
        assert limpar_texto("") == ""

    def test_remove_marcacoes_web(self):
        t = "[editar] Conteúdo real do documento " + "com palavras suficientes " * 8
        limpo = limpar_texto(t)
        assert "[editar]" not in limpo


class TestELixo:
    def test_curto_demais_e_lixo(self):
        assert e_lixo("muito curto") is True

    def test_prosa_real_nao_e_lixo(self):
        prosa = ("A feijoada e um prato tipico da culinaria brasileira feito com "
                 "feijao preto e varias carnes de porco, servida com arroz, "
                 "couve, laranja e farofa. Existem varias receitas regionais "
                 "com ingredientes diferentes ao longo do pais, cada estado "
                 "com sua variacao tradicional passada de geracao em geracao.")
        assert e_lixo(prosa) is False

    def test_menu_indice_e_lixo(self):
        menu = " ".join(f"Item Menu {i}" for i in range(40))
        assert e_lixo(menu) is True


# ---------- VERBATIM: limpeza fence-aware (regra 8 da spec rag_puro.md) ------
# Caso real 13/09: o pipeline EMENDAVA linhas de código cuja anterior não
# terminava em pontuação, colapsava indentação ≥2 espaços e DELETAVA linhas
# só-símbolo (`}`) e o fechamento da cerca — o ".md quebrado" do digest.

_CERCA_PY = '''```python
def ola():
    print("hello world")
    nome = input()
    return nome
```'''


class TestLimparTextoCercas:
    def test_linhas_de_codigo_nao_sao_emendadas(self):
        limpo = limpar_texto("intro do documento.\n\n" + _CERCA_PY)
        for linha in ("def ola():", '    print("hello world")',
                      "    nome = input()", "    return nome"):
            assert linha in limpo, f"linha emendada/perdida: {linha!r}"

    def test_indentacao_preservada(self):
        limpo = limpar_texto("intro.\n\n" + _CERCA_PY)
        assert "\n    return nome" in limpo

    def test_linhas_de_simbolos_e_fechamento_sobrevivem(self):
        cerca = ("```js\nfunction foo() {\n  return 1;\n}\n"
                 "const lista = [\n  1,\n];\n```")
        limpo = limpar_texto("intro do documento.\n\n" + cerca)
        assert limpo.count("```") == 2          # fechamento não foi deletado
        assert "\n}" in limpo and "\n];" in limpo

    def test_cerca_nao_fechada_e_prosa(self):
        aberta = "```python\nprint(1)\n"       # sem fechamento: prosa, sem crash
        limpo = limpar_texto("intro.\n\n" + aberta + "\nmais prosa aqui.\n")
        assert "print(1)" in limpo
        assert limpar_texto(limpo) == limpo     # idempotente mesmo assim

    def test_idempotente_com_cercas(self):
        doc = "parágrafo introdutório do documento de teste.\n\n" + _CERCA_PY \
              + "\n\nparágrafo final explicando o exemplo anterior.\n"
        limpo = limpar_texto(doc)
        assert limpar_texto(limpo) == limpo

    def test_limpa_prosa_ao_redor_da_cerca(self):
        doc = ("[editar] Parágrafo com marcação de wiki para limpar. "
               + "palavras suficientes para o parágrafo. " * 4
               + "\n\n" + _CERCA_PY
               + "\n\n•\n1\npublicidade\n")
        limpo = limpar_texto(doc)
        assert "[editar]" not in limpo and "publicidade" not in limpo
        assert "def ola():" in limpo             # cerca verbatim no meio

    def test_sem_cerca_e_o_de_sempre(self):
        """Paridade: doc sem ``` produz a MESMA saída do pipeline de prosa."""
        from core.limpeza import _limpar_prosa
        prosa = ("O tucupi é um caldo amarelo extraído da mandioca brava.\n"
                 "Serve para preparar o tacacá no Pará.\n" * 3)
        assert limpar_texto(prosa) == _limpar_prosa(prosa)


class TestGatesCercas:
    """e_lixo/score_chunk não podem rejeitar chunk de código (regra 8-iii)."""

    def test_e_lixo_aprova_chunk_com_cerca_real(self):
        cerca = ("```csharp\nvar builder = WebApplication.CreateBuilder(args);\n"
                 "var app = builder.Build();\napp.Run();\n```")
        assert e_lixo("explicação curta\n\n" + cerca) is False

    def test_e_lixo_menu_continua_lixo(self):
        menu = " ".join(f"Item Menu {i}" for i in range(40))
        assert e_lixo(menu) is True

    def test_score_chunk_nao_pune_codigo_na_cerca(self):
        from core.limpeza import score_chunk
        cerca = ("```go\nswitch x {\ncase 1 | 2 | 3:\n\treturn \"par\"\n"
                 "case 4 | 5 | 6:\n\treturn \"impar\"\n}\n```")
        nota, _ = score_chunk("explicação do match arms\n\n" + cerca)
        assert nota >= 0.55                       # | de código ≠ tabela

    def test_score_chunk_pune_pipes_na_prosa(self):
        from core.limpeza import score_chunk
        tabela = "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 | 3 |\n" * 3
        nota, _ = score_chunk(tabela)
        assert nota <= 0.2                        # grade de dados segue lixo
