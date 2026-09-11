"""Consolidação na ingestão — verificar antes de incluir (spec
core/specs/consolidacao.md, pedido do dono 12/09: "antes de incluir
qualquer item no Qdrant, verificar se já tem a informação, e se tiver,
consolidar — pesquisar o que tem e complementar; se não tiver, acrescentar").

Nenhum pedaço entra na coleção sem uma busca vetorial prévia na MESMA
coleção: semelhante ≥ CONSOLIDA_SCORE → FUNDE no ponto existente (mesmo
id, sentenças novas anexadas, metadata completada, re-embed); idêntico →
inalterado; novo → id DETERMINÍSTICO (reingestão sobrepõe, não empilha).

As PALAVRAS exibidas (saída padrão etc.) vêm da spec; degradação em
silêncio: flag desligada → comportamento antigo (add_documents), erro de
busca → o pedaço entra como novo (consolidar é proteção contra duplicado,
nunca bloqueio da ingestão).
"""
import hashlib
import re
import uuid
from datetime import datetime, timezone

# header de indexação na 1ª linha do chunk ([O que é: … · parte i/n]) —
# o mesmo formato que o digest/a resposta direta removem na exibição
_RE_HEADER = re.compile(r"^(\[[^\]\n]{3,260}\])\r?\n")


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm(frase: str) -> str:
    """Sentença normalizada p/ comparação (sem acento/caixa/espaço extra)."""
    import unicodedata
    t = unicodedata.normalize("NFD", frase or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"\s+", " ", t).strip(" \t\r\n.;:!?…\"'")


def _frases(texto: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.!?…])\s+", texto or "")
            if f.strip()]


def fundir_textos(base: str, novo: str, limite: int) -> tuple[str, int]:
    """Funde o CORPO do pedaço novo no existente: cabeçalho da base
    preservado; sentenças do novo que a base não tem são anexadas ao fim,
    respeitando o limite. Devolve (texto fundido, nº de sentenças novas)."""
    m = _RE_HEADER.match(base)
    header, corpo = (m.group(1), base[m.end():]) if m else ("", base)
    m2 = _RE_HEADER.match(novo)
    corpo_novo = novo[m2.end():] if m2 else novo
    vistas = {_norm(f) for f in _frases(corpo)}
    aplicadas = 0
    for f in _frases(corpo_novo):
        if _norm(f) in vistas:
            continue
        if len(corpo) + len(f) + 2 > max(0, limite - len(header)):
            break                      # limite do chunk: o que coube, coube
        corpo = (corpo.rstrip() + "\n" + f) if corpo.strip() else f
        vistas.add(_norm(f))
        aplicadas += 1
    out = (header + "\n" + corpo.strip()) if header else corpo.strip()
    return out, aplicadas


def _palavra(chave: str, padrao: str, **subs) -> str:
    """Texto de exibição da spec de consolidação (regra do projeto)."""
    from .specs import valor as _valor
    try:
        texto = _valor("consolidacao", chave, padrao)
    except Exception:
        texto = padrao
    for k, v in subs.items():
        texto = texto.replace("{" + k + "}", str(v))
    return texto


def _id_deterministico(colecao: str, conteudo: str) -> str:
    """uuid5 estável do conteúdo NA coleção: reingerir o mesmo material
    sobrepõe o ponto (fim da pilha de duplicados entre ingestões)."""
    chave = re.sub(r"\s+", " ", conteudo).strip()
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
                          f"{colecao}:{hashlib.md5(chave.encode('utf-8')).hexdigest()}"))


def consolidar(client, colecao: str, chunks, log=print) -> dict:
    """Grava `chunks` na coleção CONSOLIDANDO com o que já existe (regras
    e palavras na spec core/specs/consolidacao.md). Retorna a SAÍDA PADRÃO
    {novos, consolidados, inalterados, total_pontos}."""
    from qdrant_client.models import PointStruct
    from . import config, rag
    log = log or print
    if not chunks:
        return {"novos": 0, "consolidados": 0, "inalterados": 0,
                "total_pontos": (client.count(colecao).count
                                 if client.collection_exists(colecao) else 0)}
    tem_colecao = client.collection_exists(colecao)
    limiar = float(getattr(config, "CONSOLIDA_SCORE", 0.92))
    log(_palavra("MSG_INICIO",
                 "🔎 consultando a coleção antes de incluir ({total} pedaço"
                 "(s))…", total=len(chunks), limiar=limiar))
    emb = rag.embeddings()
    vetores = emb.embed_documents([c.page_content for c in chunks])
    novos, consolidados, inalterados = [], 0, 0
    for c, vec in zip(chunks, vetores):
        parecido = None
        if tem_colecao:
            try:
                r = client.query_points(collection_name=colecao, query=vec,
                                        limit=3, with_payload=True)
                parecido = next((p for p in r.points
                                 if p.score >= limiar), None)
            except Exception as e:
                log(f"⚠️ consulta de consolidação falhou ({str(e)[:80]}) — "
                    "o pedaço entra como novo")
        if parecido is not None:
            payload = parecido.payload or {}
            base_txt = str(payload.get("page_content") or "")
            base_meta = dict(payload.get("metadata") or {})
            # código nunca é fundido no meio: ≥limiar = já está lá
            if c.metadata.get("camada") == "codigo":
                inalterados += 1
                continue
            texto, novas = fundir_textos(base_txt, c.page_content,
                                         int(config.CHUNK_SIZE))
            if novas == 0:
                inalterados += 1   # a base já tinha esta informação completa
                continue
            meta = {**base_meta}
            for k, v in c.metadata.items():
                if v and not meta.get(k):
                    meta[k] = v      # funde metadata: preenche o que faltava
            meta["atualizado_em"] = _agora()
            meta["consolidacoes"] = int(base_meta.get("consolidacoes") or 0) + 1
            extras = list(base_meta.get("origens_extras") or [])
            origem_nova = str(c.metadata.get("arquivo") or
                              c.metadata.get("source") or "")
            if origem_nova and origem_nova not in extras \
                    and origem_nova != base_meta.get("arquivo"):
                extras.append(origem_nova)
            meta["origens_extras"] = extras[:8]
            try:
                client.upsert(collection_name=colecao, points=[PointStruct(
                    id=parecido.id,
                    vector=emb.embed_query(texto),
                    payload={"page_content": texto, "metadata": meta})])
                consolidados += 1
                log(_palavra("MSG_CONSOLIDANDO",
                             "🔁 consolidando (score {score}): {titulo} "
                             "+{novas} frase(s)", score=f"{parecido.score:.3f}",
                             titulo=(meta.get("titulo")
                                     or meta.get("arquivo") or "?")[:60],
                             novas=novas))
            except Exception as e:
                log(f"⚠️ fusão falhou ({str(e)[:80]}) — o pedaço entra como novo")
                novos.append(_ponto_novo(c, vec, colecao))
        else:
            novos.append(_ponto_novo(c, vec, colecao))
    if novos:
        log(_palavra("MSG_NOVO",
                     "⬆️ {novos} pedaço(s) novo(s) — id determinístico",
                     novos=len(novos)))
        for i in range(0, len(novos), 256):
            client.upsert(collection_name=colecao, points=novos[i:i + 256])
    total = client.count(colecao).count
    resumo = {"novos": len(novos), "consolidados": consolidados,
              "inalterados": inalterados, "total_pontos": total}
    log(_palavra("MSG_SAIDA",
                 "📥 saída: {novos} novo(s) · {consolidados} consolidado(s) · "
                 "{inalterados} inalterado(s) — {colecao} ficou com {total} "
                 "ponto(s)", **resumo, total=total, colecao=colecao))
    return resumo


def _ponto_novo(c, vec, colecao: str):
    """PointStruct do pedaço novo: id determinístico + padrão de metadata
    (criado_em/atualizado_em — o_que_e/pra_que_serve vêm do _dividir)."""
    from qdrant_client.models import PointStruct
    meta = {k: v for k, v in (c.metadata or {}).items() if v}
    agora = _agora()
    meta.setdefault("criado_em", agora)
    meta.setdefault("atualizado_em", agora)
    return PointStruct(id=_id_deterministico(colecao, c.page_content),
                       vector=vec,
                       payload={"page_content": c.page_content,
                                "metadata": meta})
