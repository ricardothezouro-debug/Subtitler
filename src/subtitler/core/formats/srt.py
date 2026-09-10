"""SubRip (.srt) -- o formato que o YouTube e todo editor de video aceitam.

Duas particularidades que quebram players quando erradas:

* o separador de milissegundos e **virgula** (o VTT usa ponto);
* o terminador de linha e **CRLF**. E o que a maioria das ferramentas gera, e
  parsers antigos engasgam com LF puro.

Nao ha escaping: `<i>` e `<b>` sao tags validas em SRT, entao o texto vai literal.
"""
from __future__ import annotations

from typing import Sequence

from subtitler.core.cues import Cue

QUEBRA = "\r\n"


def format_timestamp(segundos: float) -> str:
    """`HH:MM:SS,mmm` -- com virgula, que e o que o SRT exige."""
    total_ms = max(0, int(round(segundos * 1000)))
    horas, resto = divmod(total_ms, 3_600_000)
    minutos, resto = divmod(resto, 60_000)
    segs, ms = divmod(resto, 1000)
    return f"{horas:02d}:{minutos:02d}:{segs:02d},{ms:03d}"


def dumps(cues: Sequence[Cue]) -> str:
    blocos: list[str] = []
    for indice, cue in enumerate(cues, start=1):
        corpo = QUEBRA.join(cue.lines)
        blocos.append(
            f"{indice}{QUEBRA}"
            f"{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}{QUEBRA}"
            f"{corpo}{QUEBRA}"
        )
    return QUEBRA.join(blocos)
