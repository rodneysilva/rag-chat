"""Rodeiro ÚNICO de linguagens de programação (Fase E — fim do drift).

Três listas divergiam (unificar_arquiteturas 7, auto 8, app 12) e a regra
"base unificada entra junto" batia diferente conforme o arquivo. Uma fonte
só: `LINGUAGENS` (coleções de linguagem que puxam a arquitetura_unificada e
entram na unificação) e `EH_DEV` (nomes fixos de coleções dev, ex-catálogo).
"""
# coleções de LINGUAGEM de programação (regra da base unificada + unificação)
LINGUAGENS = {
    "rust", "java", "csharp", "nodejs", "go", "python", "ruby", "dotnet",
    "javascript", "typescript", "kotlin", "swift", "php", "c", "cpp",
}

# coleções DEV fixas (display/agrupamento do catálogo — não só linguagens:
# frameworks e docs de modelos também são "dev")
EH_DEV = LINGUAGENS | {
    "angular", "react", "htmx", "arquitetura_unificada", "docs_flux",
    "docs_wan", "docs_bge_m3", "docs_qwen", "docs_qwen_vl",
}

# frameworks/bancos/ferramentas citáveis numa pergunta — lista ÚNICA: o
# _RE_PROG do roteador (grafo.py) e o roteamento de domínio da consulta
# (api/base.py) usam a mesma (antes vivia só no grafo)
FRAMEWORKS = (
    "flask|fastapi|django|spring|laravel|rails|express|gin|fiber|"
    "actix|axum|ktor|docker|k8s|kubernetes|postgres|mysql|mongo|redis|"
    r"asp[.\s]?net|blazor|maui|xamarin|unity|godot"
)

import re  # noqa: E402 — depois das listas (fonte única acima)

# 🧭 DETECTOR DE PERGUNTA DE CÓDIGO (sem LLM — regra 6 da spec rag_puro.md):
# nome de linguagem/framework + termos FORTES de programação em PT/EN. É o
# que separa "como desenvolvo uma api em dotnet" (busca SÓ nas coleções
# dev) de "receita de tucupi" (coleções dev fora). Nomes de 1 letra (o "c"
# de LINGUAGENS) ficam FORA — "vitamina C" não é código; termos ambíguos
# ("classe" social, "biblioteca" de prédio) também.
RE_PERGUNTA_DEV = re.compile(
    r"\b(" + "|".join(sorted(n for n in EH_DEV if len(n) > 2))
    + "|" + FRAMEWORKS
    + r"|api|end\s?point|c[óo]digo|fun[çc][ãa]o|algoritmo|framework|"
    r"backend|frontend|compil\w*|debug|depur\w*|program\w*|"
    r"sql|json|yaml|xml|regex|array|string|vari[áa]vel|"
    r"dev\b|bug\b)\b", re.I)


def pergunta_dev(pergunta: str) -> bool:
    """A pergunta fala de DESENVOLVIMENTO? (regex pura, custo zero)"""
    return bool(RE_PERGUNTA_DEV.search(pergunta or ""))
