"""O que a transcricao e, depois de normalizada.

A resposta da Groq vem com segmentos (frases inteiras, longas demais para
legenda) e, quando pedimos, com palavras individuais e seus tempos. E a palavra
que interessa: e dela que sai o tempo exato de entrada e saida de cada legenda.

Este modulo nao fala com a rede nem com o Qt. Entra JSON, sai dado limpo.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# Acima disto o Whisper provavelmente inventou fala onde havia silencio ou
# musica. Os dois criterios precisam bater: so um deles gera falso positivo e
# come fala baixa de verdade.
_LIMIAR_SEM_FALA = 0.6
_LIMIAR_LOGPROB = -1.0

_ESPACOS = re.compile(r"\s+")


@dataclass(frozen=True)
class Word:
    """Uma palavra com o instante em que comeca e termina, em segundos."""

    text: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class Segment:
    """Uma frase como o Whisper a devolveu, com os indicadores de confianca."""

    text: str
    start: float
    end: float
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0

    @property
    def provavel_alucinacao(self) -> bool:
        return (
            self.no_speech_prob > _LIMIAR_SEM_FALA
            and self.avg_logprob < _LIMIAR_LOGPROB
        )


@dataclass
class Transcript:
    words: list[Word] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    language: Optional[str] = None
    #: False quando a API nao devolveu palavras e tivemos que estimar os tempos.
    #: A UI avisa o usuario, porque a legenda fica visivelmente menos precisa.
    word_level: bool = True

    @property
    def duration(self) -> float:
        if self.words:
            return self.words[-1].end
        if self.segments:
            return self.segments[-1].end
        return 0.0

    def texto(self) -> str:
        return " ".join(w.text for w in self.words).strip()


def _limpar(texto: str) -> str:
    return _ESPACOS.sub(" ", str(texto or "")).strip()


def _palavras_estimadas(segmento: Segment) -> list[Word]:
    """Distribui o tempo do segmento entre suas palavras.

    Usado so quando a API nao devolve `words` -- acontece. Sem este resgate o
    trabalho inteiro morreria por falta de tempos. A divisao e proporcional ao
    numero de caracteres, que aproxima melhor que dividir por igual: palavra
    longa realmente leva mais tempo para ser dita.
    """
    partes = [p for p in _limpar(segmento.text).split(" ") if p]
    if not partes:
        return []
    total = sum(len(p) for p in partes) or 1
    duracao = max(0.0, segmento.end - segmento.start)

    palavras: list[Word] = []
    cursor = segmento.start
    for parte in partes:
        fatia = duracao * (len(parte) / total)
        palavras.append(Word(parte, cursor, cursor + fatia))
        cursor += fatia
    return palavras


def from_verbose_json(payload: Any, offset: float = 0.0) -> Transcript:
    """Le a resposta `verbose_json` da Groq.

    `offset` desloca todos os tempos: quando o audio foi fatiado, cada pedaco
    volta com tempos relativos ao proprio pedaco, e e aqui que eles voltam para
    a linha do tempo do arquivo inteiro.
    """
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        return Transcript()

    segmentos: list[Segment] = []
    for bruto in payload.get("segments") or []:
        if not isinstance(bruto, dict):
            continue
        texto = _limpar(bruto.get("text", ""))
        if not texto:
            continue
        segmentos.append(
            Segment(
                text=texto,
                start=float(bruto.get("start", 0.0)) + offset,
                end=float(bruto.get("end", 0.0)) + offset,
                no_speech_prob=float(bruto.get("no_speech_prob", 0.0) or 0.0),
                avg_logprob=float(bruto.get("avg_logprob", 0.0) or 0.0),
            )
        )

    palavras: list[Word] = []
    nivel_palavra = True
    for bruto in payload.get("words") or []:
        if not isinstance(bruto, dict):
            continue
        texto = _limpar(bruto.get("word", bruto.get("text", "")))
        if not texto:
            continue
        palavras.append(
            Word(
                text=texto,
                start=float(bruto.get("start", 0.0)) + offset,
                end=float(bruto.get("end", 0.0)) + offset,
            )
        )

    if not palavras and segmentos:
        nivel_palavra = False
        for segmento in segmentos:
            palavras.extend(_palavras_estimadas(segmento))

    return Transcript(
        words=palavras,
        segments=segmentos,
        language=payload.get("language"),
        word_level=nivel_palavra,
    )


def _normalizar_token(texto: str) -> str:
    return re.sub(r"[^\w]", "", texto, flags=re.UNICODE).casefold()


def _remover_repeticao_na_costura(
    anteriores: list[Word], seguintes: list[Word], janela: float = 1.5
) -> list[Word]:
    """Tira a frase que o Whisper repete no comeco de uma fatia.

    Quando um corte cai no meio da fala (sem silencio onde cortar), damos alguns
    segundos de sobreposicao entre as fatias para nao perder palavra. O efeito
    colateral e o Whisper transcrever o mesmo trecho duas vezes. Comparamos os
    tokens ao redor da emenda e descartamos a repeticao.
    """
    if not anteriores or not seguintes:
        return seguintes

    limite = anteriores[-1].end
    cauda = [w for w in anteriores if w.end >= limite - janela]
    if not cauda:
        return seguintes

    tokens_cauda = [_normalizar_token(w.text) for w in cauda]
    maior = min(len(tokens_cauda), len(seguintes), 12)

    for tamanho in range(maior, 1, -1):
        inicio = [_normalizar_token(w.text) for w in seguintes[:tamanho]]
        if inicio and inicio == tokens_cauda[-tamanho:]:
            return seguintes[tamanho:]
    return seguintes


def merge(partes: Iterable[Transcript], cortes_duros: Optional[set[int]] = None) -> Transcript:
    """Junta as fatias numa transcricao unica.

    `cortes_duros` traz os indices das fatias que comecaram sem silencio -- so
    nelas vale a pena procurar repeticao.
    """
    cortes_duros = cortes_duros or set()
    palavras: list[Word] = []
    segmentos: list[Segment] = []
    idioma: Optional[str] = None
    nivel_palavra = True

    for indice, parte in enumerate(partes):
        if idioma is None:
            idioma = parte.language
        nivel_palavra = nivel_palavra and parte.word_level

        novas = parte.words
        if indice in cortes_duros:
            novas = _remover_repeticao_na_costura(palavras, novas)

        palavras.extend(novas)
        segmentos.extend(parte.segments)

    return Transcript(
        words=palavras,
        segments=segmentos,
        language=idioma,
        word_level=nivel_palavra,
    )


def sanitize(transcricao: Transcript) -> Transcript:
    """Conserta o que a API entrega torto, antes de virar legenda.

    Tres coisas: tempo que anda para tras, palavra de duracao zero, e trechos
    alucinados em cima de silencio ou musica.
    """
    alucinados = [s for s in transcricao.segments if s.provavel_alucinacao]

    def dentro_de_alucinacao(palavra: Word) -> bool:
        meio = (palavra.start + palavra.end) / 2
        return any(s.start <= meio <= s.end for s in alucinados)

    limpas: list[Word] = []
    anterior_fim = 0.0
    for palavra in transcricao.words:
        if not palavra.text or dentro_de_alucinacao(palavra):
            continue
        inicio = max(float(palavra.start), anterior_fim)
        fim = max(float(palavra.end), inicio + 0.02)
        limpas.append(Word(palavra.text, inicio, fim))
        anterior_fim = fim

    return Transcript(
        words=limpas,
        segments=[s for s in transcricao.segments if not s.provavel_alucinacao],
        language=transcricao.language,
        word_level=transcricao.word_level,
    )
