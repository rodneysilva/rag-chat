"""🧭 Detector de pergunta de código (regra 6 da spec rag_puro.md).

Sem LLM, custo zero: `pergunta_dev` é o que separa "como desenvolvo uma
api em dotnet" (busca SÓ nas coleções dev) de "receita de tucupi" (coleções
dev fora do escopo). Falsos positivos são o pior erro possível — vitamina C
não é a linguagem C — então os negativos pesam tanto quanto os positivos.
"""
import pytest

from core.linguagens import pergunta_dev, RE_PERGUNTA_DEV
from core import grafo


@pytest.mark.parametrize("pergunta", [
    "Como desenvolvo uma api em dotnet?",       # o caso real do dono
    "hello world em python",
    "como criar um endpoint em fastapi",
    "o que é docker compose?",
    "como funciona uma função recursiva",
    "erro de SQL no postgres ao conectar",
    "me explique json schema",
    "como fazer deploy com kubernetes",
    "qual a diferença entre rust e go",
    "exemplo de regex para validar email",
    "como depurar um memory leak",
    "api rest com asp.net core",                # asp\s?net (com espaço)
])
def test_positivas(pergunta):
    assert pergunta_dev(pergunta), f"deveria detectar código: {pergunta!r}"


@pytest.mark.parametrize("pergunta", [
    "receita de tucupi",
    "como fazer tacacá?",
    "o que é psicanálise",
    "quem foi Freud",
    "vitamina C para que serve",                # "c" de 1 letra NÃO é código
    "o que é o complexo de Édipo",
    "qual o ponto de corte da carne de panela",
    "bom dia, tudo bem?",
])
def test_negativas(pergunta):
    assert not pergunta_dev(pergunta), f"falso positivo: {pergunta!r}"


def test_regex_coberta_pelo_grafo_nao_regride():
    """A lista de frameworks virou ÚNICA (linguagens.FRAMEWORKS): o _RE_PROG
    do roteador continua casando os mesmos techs de sempre."""
    for termo in ("flask", "fastapi", "django", "spring", "laravel", "rails",
                  "docker", "k8s", "postgres", "mysql", "mongo", "redis",
                  "asp.net", "asp net", "blazor", "maui", "xamarin", "unity",
                  "godot", "python", "dotnet", "rust"):
        assert grafo._RE_PROG.search(termo), f"_RE_PROG perdeu: {termo}"
