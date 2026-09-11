# -*- coding: utf-8 -*-
"""Baixa os modelos do RagChat em um comando (multi-OS, retomável).

    python scripts/baixar_modelos.py --tipos chat,embed            # mínimo
    python scripts/baixar_modelos.py --tipos tudo --dir ~/models   # tudo
    python scripts/baixar_modelos.py --listar                      # catálogo

Tipos: chat · embed · tudo (o fork RagChat é só texto — não há modelos
de mídia para baixar)

Cada download é retomável (huggingface_hub continua de onde parou) e pula
arquivos que já existem no destino. O destino padrão é ~/models
(MODELS_DIR do .env — o servicos_llm.py pergunta/grava na 1ª execução).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from huggingface_hub import hf_hub_download
except ImportError:
    sys.exit("pip install -U huggingface_hub  (ou: pip install -r requirements.txt)")

# ═══ catálogo: (repo, arquivo, subpasta, tamanho aproximado) ═══
CATALOGO: dict[str, list[tuple[str, str, str, str]]] = {
    "chat": [
        ("Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
         "qwen2.5-coder-7b-instruct-q4_k_m.gguf", "", "4,7 GB"),
    ],
    "embed": [
        ("CompendiumLabs/bge-m3-gguf", "bge-m3-q8_0.gguf", "", "0,7 GB"),
    ],
}
ROTULOS = {"chat": "conversa (Qwen2.5-Coder 7B Q4)",
           "embed": "embedding (bge-m3 Q8)"}


def baixar(tipo: str, destino: Path) -> None:
    print(f"\n═══ {ROTULOS.get(tipo, tipo)} ═══")
    for repo, nome, sub, _gb in CATALOGO[tipo]:
        pasta = destino / sub if sub else destino
        pasta.mkdir(parents=True, exist_ok=True)
        final = pasta / nome
        if final.exists():
            print(f"✔ {final.name} já existe — pulando")
            continue
        print(f"⬇ {repo}/{nome} → {pasta}")
        hf_hub_download(repo_id=repo, filename=nome, local_dir=str(pasta))
        print(f"✅ {final.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Baixa os modelos do RagChat")
    ap.add_argument("--tipos", default="chat,embed",
                    help="chat,embed,tudo (padrão: chat,embed)")
    ap.add_argument("--dir", default=str(Path.home() / "models"),
                    help="pasta de destino (padrão: ~/models — use a MESMA do MODELS_DIR)")
    ap.add_argument("--listar", action="store_true", help="só mostra o catálogo")
    args = ap.parse_args()

    if args.listar:
        for t, itens in CATALOGO.items():
            print(f"{t:8} {ROTULOS.get(t, '')}")
            for repo, nome, _s, gb in itens:
                print(f"         {repo}/{nome} — {gb}")
        return 0

    tipos = (args.tipos or "").lower().split(",")
    if "tudo" in tipos:
        tipos = list(CATALOGO)
    invalidos = [t for t in tipos if t not in CATALOGO]
    if invalidos:
        ap.error(f"tipos inválidos: {', '.join(invalidos)} — use --listar")
    destino = Path(args.dir).expanduser()
    print(f"🎲 baixando {', '.join(tipos)} para {destino}")
    for t in tipos:
        baixar(t.strip(), destino)
    print(f"\n🎉 concluído. Rode `python servicos_llm.py` apontando para {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
