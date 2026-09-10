"""Escrita dos formatos de legenda.

Despacho por nome, para a UI so precisar de uma lista de strings -- e para a v2
acrescentar `nome.en.srt` pelo mesmo caminho.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from subtitler.core.cues import Cue
from subtitler.core.formats import srt, txt, vtt

FORMATOS = ("srt", "vtt", "txt")


def dumps(cues: Sequence[Cue], formato: str, **opcoes) -> str:
    nome = formato.lower().lstrip(".")
    if nome == "srt":
        return srt.dumps(cues)
    if nome == "vtt":
        return vtt.dumps(cues)
    if nome == "txt":
        return txt.dumps(cues, **opcoes)
    raise ValueError(f"Formato desconhecido: {formato}")


def write(cues: Sequence[Cue], destino: Path, formato: str, **opcoes) -> Path:
    """Grava sempre em UTF-8 sem BOM, com o terminador que cada formato exige.

    `newline=""` e obrigatorio: sem ele o Python traduz o \\n do CRLF do SRT
    para \\r\\n no Windows, gerando \\r\\r\\n e quebrando players.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    conteudo = dumps(cues, formato, **opcoes)
    destino.write_text(conteudo, encoding="utf-8", newline="")
    return destino
