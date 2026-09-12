"""Resolução da CONSULTA CONSOLIDADA (spec core/specs/consulta_consolidada.md).

O chat (webui) e a API /v1 não escolhem modo/escopo/MCPs — a configuração
da administração (.env, cartão 🎯 Consulta do /sistema) é a fonte única.
Este módulo lê as 4 chaves e devolve o estado consolidado:

- ``modo_efetivo()``  → "hibrido" | "rag" | "livre" (ambos desligados
  levanta ``ConsultaIndisponivel`` — o chamador devolve MSG_INDISPONIVEL);
- ``escopo_config()`` → lista de coleções ou None (= TODAS as visíveis);
- ``mcps_config()``   → lista de MCPs ativos (pesquisa-web só se LISTADO);
- ``resumo()``        → tudo num dict, pronto para a 1ª linha do raciocínio.

Puro e sem IO — testável direto (tests/core/test_consulta.py).
"""
from . import config

MODO_HIBRIDO = "hibrido"
MODO_RAG = "rag"
MODO_LIVRE = "livre"


class ConsultaIndisponivel(RuntimeError):
    """RAG e LLM desligados na configuração — consulta não existe."""


def _csv(chave: str) -> list[str]:
    """CSV cru do .env → lista sem vazios, sem repetidos, ordem preservada."""
    bruto = getattr(config, chave, "") or ""
    saida: list[str] = []
    for item in bruto.split(","):
        item = item.strip()
        if item and item not in saida:
            saida.append(item)
    return saida


def rag_ativo() -> bool:
    return bool(getattr(config, "RAG_ATIVO", True))


def llm_ativo() -> bool:
    return bool(getattr(config, "LLM_ATIVO", True))


def disponivel() -> bool:
    """Há consulta possível? (ambos desligados = não)."""
    return rag_ativo() or llm_ativo()


def modo_efetivo() -> str:
    """Deriva o modo dos toggles (regra 2 da spec). Levanta se ambos off."""
    rag, llm = rag_ativo(), llm_ativo()
    if rag and llm:
        return MODO_HIBRIDO
    if rag:
        return MODO_RAG
    if llm:
        return MODO_LIVRE
    raise ConsultaIndisponivel(
        "RAG e LLM estão desligados na configuração (Sistema → 🎯 Consulta)")


def escopo_config() -> list[str] | None:
    """RAG_COLECOES (CSV); vazio = None = TODAS as visíveis (regra 3)."""
    cols = _csv("RAG_COLECOES")
    return cols or None


def mcps_config() -> list[str]:
    """MCP_ATIVOS (CSV, já ∩ registrados acontece no chamador — regra 4)."""
    return _csv("MCP_ATIVOS")


def resumo() -> dict:
    """Estado consolidado num dict — modo None = consulta indisponível."""
    try:
        modo = modo_efetivo()
    except ConsultaIndisponivel:
        modo = None
    return {
        "modo": modo,
        "rag": rag_ativo(),
        "llm": llm_ativo(),
        "colecoes": escopo_config(),
        "mcps": mcps_config(),
    }
