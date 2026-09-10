"""WebVTT (.vtt) -- o formato nativo da web e o que players HTML5 leem.

Diferencas em relacao ao SRT que importam:

* milissegundos separados por **ponto**, nao virgula;
* terminador **LF**, nao CRLF;
* cabecalho `WEBVTT` obrigatorio;
* e, ao contrario do SRT, **ha escaping obrigatorio**: `&`, `<` e `>` sao
  sintaxe. Um "R&D" ou um "5 < 10" sem escapar quebra a renderizacao.

Nao emitimos identificador de cue: e opcional e so adiciona ruido.
"""
from __future__ import annotations

from typing import Sequence

from subtitler.core.cues import Cue

QUEBRA = "\n"


def format_timestamp(segundos: float) -> str:
    """`HH:MM:SS.mmm` -- com ponto. Horas sempre presentes, por consistencia."""
    total_ms = max(0, int(round(segundos * 1000)))
    horas, resto = divmod(total_ms, 3_600_000)
    minutos, resto = divmod(resto, 60_000)
    segs, ms = divmod(resto, 1000)
    return f"{horas:02d}:{minutos:02d}:{segs:02d}.{ms:03d}"


def escape(texto: str) -> str:
    """`&` primeiro, senao escaparíamos duas vezes o que ja foi escapado."""
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def dumps(cues: Sequence[Cue]) -> str:
    partes: list[str] = ["WEBVTT", ""]
    for cue in cues:
        partes.append(f"{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}")
        partes.extend(escape(linha) for linha in cue.lines)
        partes.append("")
    return QUEBRA.join(partes)
