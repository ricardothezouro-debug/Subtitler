"""Texto corrido (.txt) -- para quem quer o conteudo, nao a legenda.

E o formato que alimenta resumo, roteiro e descricao do video. Por isso nao leva
timestamps por padrao e nao tem quebra de linha artificial: quem le usa o wrap
do proprio editor.

Paragrafo novo a cada pausa longa ou a cada ~400 caracteres, o que vier
primeiro -- um bloco unico de 40 minutos e ilegivel.
"""
from __future__ import annotations

from typing import Sequence

from subtitler.core.cues import Cue

PAUSA_DE_PARAGRAFO = 2.0
MAX_CARACTERES_POR_PARAGRAFO = 400


def _marca_de_tempo(segundos: float) -> str:
    total = max(0, int(segundos))
    horas, resto = divmod(total, 3600)
    minutos, segs = divmod(resto, 60)
    return f"[{horas:02d}:{minutos:02d}:{segs:02d}]"


def dumps(cues: Sequence[Cue], com_tempos: bool = False) -> str:
    if not cues:
        return ""

    paragrafos: list[tuple[float, list[str]]] = []
    atual: list[str] = []
    inicio_do_paragrafo = cues[0].start

    for indice, cue in enumerate(cues):
        atual.append(cue.text)
        proxima = cues[indice + 1] if indice + 1 < len(cues) else None
        if proxima is None:
            continue

        pausa = proxima.start - cue.end
        tamanho = sum(len(t) + 1 for t in atual)
        if pausa >= PAUSA_DE_PARAGRAFO or tamanho >= MAX_CARACTERES_POR_PARAGRAFO:
            paragrafos.append((inicio_do_paragrafo, atual))
            atual = []
            inicio_do_paragrafo = proxima.start

    if atual:
        paragrafos.append((inicio_do_paragrafo, atual))

    linhas: list[str] = []
    for inicio, textos in paragrafos:
        corpo = " ".join(textos).strip()
        linhas.append(f"{_marca_de_tempo(inicio)} {corpo}" if com_tempos else corpo)
    return "\n\n".join(linhas) + "\n"
