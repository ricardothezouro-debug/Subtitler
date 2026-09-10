"""Detecta silencio e decide onde cortar o audio em fatias.

O plano gratuito da Groq aceita 25 MB por requisicao -- cerca de 24 minutos em
FLAC 16 kHz mono. Um VOD de live passa disso com folga, entao fatiamos.

Onde cortar importa: cortar no meio de uma palavra a perde, e faz o Whisper
alucinar nas bordas. Por isso procuramos silencio perto da fronteira desejada e
cortamos no meio dele. Quando nao ha silencio na janela, cortamos mesmo assim,
mas com sobreposicao -- e depois removemos a frase repetida (ver
`transcript.merge`).

Esta mesma deteccao e a base do cortador de audio da v2. Nota que vale registrar
agora: os tempos do Whisper derivam ate cerca de um segundo, entao cortar por
eles clipa o inicio das palavras. O silencio detectado aqui e preciso na
amostra -- e por ele que o cortador deve se guiar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from subtitler.core.ffmpeg_locator import Ferramentas
from subtitler.core.media import run

_INICIO = re.compile(r"silence_start:\s*(-?[\d.]+)")
_FIM = re.compile(r"silence_end:\s*(-?[\d.]+)")

#: Alvo de duracao por fatia. 10 min da ~10 MB: folga confortavel sob os 25 MB,
#: e uma fatia que falha custa pouco para refazer.
ALVO_SEGUNDOS = 600.0
MAX_SEGUNDOS = 900.0
#: O quanto procuramos silencio ao redor da fronteira desejada.
JANELA_DE_BUSCA = 120.0
#: Sobreposicao quando nao ha silencio onde cortar.
SOBREPOSICAO = 2.0


@dataclass(frozen=True)
class Silencio:
    start: float
    end: float

    @property
    def meio(self) -> float:
        return (self.start + self.end) / 2

    @property
    def duracao(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class Fatia:
    indice: int
    start: float
    end: float
    #: True quando o corte NAO caiu em silencio -- ai ha sobreposicao e a
    #: juncao precisa procurar frase repetida.
    corte_duro: bool = False

    @property
    def duracao(self) -> float:
        return max(0.0, self.end - self.start)


def parse_silencedetect(stderr: str) -> list[Silencio]:
    """Le os pares `silence_start` / `silence_end` do stderr do ffmpeg."""
    inicios = [float(m) for m in _INICIO.findall(stderr or "")]
    fins = [float(m) for m in _FIM.findall(stderr or "")]
    silencios = [
        Silencio(inicio, fim)
        for inicio, fim in zip(inicios, fins)
        if fim > inicio
    ]
    return sorted(silencios, key=lambda s: s.start)


#: Limiares tentados em ordem. O primeiro vale para audio limpo; os seguintes
#: existem para live com jogo ou musica por baixo da voz, onde o fundo nunca
#: deixa o sinal cair abaixo de -30 dB e o filtro nao acha pausa nenhuma.
LIMIARES_DB = (-30.0, -40.0, -50.0)

#: Abaixo disto consideramos que nao achamos pausa util e vale afrouxar.
MINIMO_DE_SILENCIOS = 3


def detect(
    ferramentas: Ferramentas,
    audio: Path,
    ruido_db: Optional[float] = None,
    duracao_minima: float = 0.35,
) -> list[Silencio]:
    """Roda o filtro `silencedetect` e devolve os trechos de silencio.

    Quando encontra pouca coisa (fundo musical, ruido de sala), afrouxa o
    limiar: um audio sem silencio nenhum nao daria onde cortar.

    Esse afrouxamento estava descrito aqui mas nunca foi implementado -- rodava
    uma vez a -30 dB e desistia. Numa live com o jogo ao fundo isso devolvia
    zero pausas, e entao TODO corte virava corte duro no relogio, com 2s de
    sobreposicao em cada costura para o removedor de repeticao resolver
    sozinho. Cada costura errada vira frase repetida ou fala perdida.
    """
    limiares = (ruido_db,) if ruido_db is not None else LIMIARES_DB
    encontrados: list[Silencio] = []
    for limiar in limiares:
        stderr = run(
            ferramentas.ffmpeg,
            [
                "-i", str(audio),
                "-af", f"silencedetect=noise={limiar}dB:d={duracao_minima}",
                "-f", "null", "-",
            ],
        )
        encontrados = parse_silencedetect(stderr)
        if len(encontrados) >= MINIMO_DE_SILENCIOS:
            break
    return encontrados


def _melhor_silencio(
    silencios: Sequence[Silencio], alvo: float, janela: float
) -> Optional[Silencio]:
    """O silencio mais longo dentro da janela ao redor do alvo."""
    candidatos = [s for s in silencios if abs(s.meio - alvo) <= janela]
    if not candidatos:
        return None
    return max(candidatos, key=lambda s: s.duracao)


def plan_chunks(
    duracao: float,
    silencios: Sequence[Silencio],
    alvo: float = ALVO_SEGUNDOS,
    maximo: float = MAX_SEGUNDOS,
    janela: float = JANELA_DE_BUSCA,
    sobreposicao: float = SOBREPOSICAO,
) -> list[Fatia]:
    """Decide os cortes. Cobre de 0 ate `duracao`, sem buraco."""
    if duracao <= 0:
        return []
    if duracao <= maximo:
        return [Fatia(0, 0.0, duracao)]

    fatias: list[Fatia] = []
    inicio = 0.0
    indice = 0

    while inicio < duracao - 0.05:
        restante = duracao - inicio
        if restante <= maximo:
            fatias.append(Fatia(indice, inicio, duracao, corte_duro=False))
            break

        desejado = inicio + alvo
        escolhido = _melhor_silencio(silencios, desejado, janela)

        if escolhido is not None and inicio < escolhido.meio < duracao:
            fim = escolhido.meio
            corte_duro = False
        else:
            fim = min(inicio + alvo, duracao)
            corte_duro = True

        # Nunca deixar a fatia passar do maximo, mesmo com silencio distante.
        fim = min(fim, inicio + maximo)
        if fim <= inicio:
            fim = min(inicio + alvo, duracao)
            corte_duro = True

        fatias.append(Fatia(indice, inicio, fim, corte_duro=corte_duro))
        # No corte duro, a proxima fatia comeca um pouco antes, para nao perder
        # a palavra que estava sendo dita.
        inicio = max(0.0, fim - sobreposicao) if corte_duro else fim
        indice += 1

    return fatias
