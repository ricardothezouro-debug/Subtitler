"""De palavras com tempo para legendas prontas.

O Whisper devolve frases inteiras, longas demais e cortadas em lugar errado para
legenda. Transformar isso em legenda boa e um problema de tres restricoes que
brigam entre si:

* **espaco** -- 2 linhas de 42 caracteres, senao vaza na tela do celular;
* **tempo** -- nem tao curta que o olho nao alcance, nem tao longa que a pessoa
  releia e se distraia;
* **velocidade** -- caracteres por segundo, que e o que de fato mede se da para
  ler antes de sumir.

Quando as tres nao cabem juntas, a saida e sempre DIVIDIR a legenda, nunca
espremer texto nem abrir uma terceira linha.

Funcao pura: entra lista de `Word`, sai lista de `Cue`. Nenhuma rede, nenhum Qt.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Sequence

from subtitler.core.linebreak import (
    MAX_CHARS_POR_LINHA,
    PROIBIDO,
    best_split,
    normalizar,
    peso_sintatico,
    wrap,
)
from subtitler.core.transcript import Word

_FIM_DE_FRASE = (".", "!", "?", "…")


@dataclass(frozen=True)
class CueRules:
    """Os numeros que definem a legenda. Todos ajustaveis na aba Avancado."""

    #: Padrao Netflix. Acima disso a linha vaza nas laterais no celular.
    max_chars_per_line: int = MAX_CHARS_POR_LINHA
    #: Tres linhas cobrem imagem demais.
    max_lines: int = 2
    #: Velocidade de leitura confortavel em pt-BR (en-US usa 20).
    target_cps: float = 17.0
    #: Teto absoluto. Passou disso, divide -- esticar nao resolve.
    hard_max_cps: float = 20.0
    #: Abaixo disso o olho nao completa a leitura.
    min_duration: float = 1.0
    #: Piso absoluto (5/6 s), usado so quando a legenda seguinte nao da espaco.
    floor_duration: float = 0.833
    #: Acima disso o espectador relê e se distrai.
    max_duration: float = 7.0
    #: 2 frames a 24fps. Sem esse respiro os cues "piscam" colados.
    min_gap: float = 0.084
    #: Entra um pouco antes, para nao parecer atrasada.
    lead_in: float = 0.06
    #: O Whisper corta o fim da palavra com agressividade.
    lead_out: float = 0.24
    #: Pausa que justifica fechar a legenda (fronteira media entre oracoes).
    pause_split: float = 0.60
    #: Pausa que OBRIGA fechar, mesmo no meio da oracao.
    hard_pause: float = 1.20
    #: Legenda mais curta que isto vira apendice da vizinha.
    merge_under_duration: float = 1.0
    merge_under_chars: int = 14

    @property
    def max_chars_per_cue(self) -> int:
        return self.max_chars_per_line * self.max_lines


@dataclass(frozen=True)
class Cue:
    """Uma legenda: quando entra, quando sai, e as linhas exibidas."""

    start: float
    end: float
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return " ".join(self.lines)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def cps(self) -> float:
        """Caracteres por segundo -- a medida real de legibilidade."""
        if self.duration <= 0:
            return float("inf")
        return len(self.text) / self.duration


def _texto(palavras: Sequence[Word]) -> str:
    return normalizar(" ".join(p.text for p in palavras))


def _fronteira_ruim(grupo: Sequence[Word], proxima: Optional[Word]) -> bool:
    """Terminar a legenda aqui separaria coisas que se leem juntas?

    As mesmas proibicoes da quebra de linha valem entre legendas -- terminar em
    "R$" ou em "em" e pior do que quebrar a linha ali, porque a continuacao so
    aparece depois que a legenda inteira trocar.
    """
    if not grupo or proxima is None:
        return False
    return peso_sintatico(grupo[-1].text, proxima.text) == PROIBIDO


def _recuar_para_boa_fronteira(
    grupo: list[Word], seguinte: Optional[Word], regras: CueRules
) -> int:
    """Quantas palavras devolver para o proximo grupo, buscando bom corte.

    Fechar exatamente onde estourou o limite quase sempre corta no meio de uma
    ideia. Recuamos ate encontrar uma fronteira sintatica boa, contanto que
    sobre texto suficiente -- abaixo de ~55%% do limite a legenda fica picotada.
    """
    if len(grupo) < 2:
        return 0

    minimo = int(regras.max_chars_per_cue * 0.55)
    melhor_recuo = 0
    melhor_peso = PROIBIDO

    # Tenta terminar em cada uma das ultimas palavras, da mais tardia para a
    # mais recuada -- assim, em caso de empate, mantem a legenda mais cheia.
    for recuo in range(0, min(len(grupo) - 1, 8)):
        fim = len(grupo) - recuo
        candidato = grupo[:fim]
        if len(_texto(candidato)) < minimo:
            break
        proxima = grupo[fim] if fim < len(grupo) else seguinte
        if proxima is None:
            peso = 0.0
        else:
            peso = peso_sintatico(candidato[-1].text, proxima.text)
        if peso < melhor_peso:
            melhor_peso = peso
            melhor_recuo = recuo
        if peso == 0.0:
            break  # fim de frase: nao ha corte melhor

    return melhor_recuo if melhor_peso < PROIBIDO else 0


def _agrupar(palavras: Sequence[Word], regras: CueRules) -> list[list[Word]]:
    """Junta palavras em grupos que caibam numa legenda.

    Fecha quando estourar caracteres ou duracao, quando a pausa indicar
    fronteira de fala, ou ao fim de uma frase que nao tem como continuar.
    """
    grupos: list[list[Word]] = []
    atual: list[Word] = []

    def fechar(ate: int = 0) -> None:
        """Fecha o grupo atual, devolvendo `ate` palavras para o proximo."""
        nonlocal atual
        if not atual:
            return
        if ate > 0:
            grupos.append(atual[:-ate])
            atual = atual[-ate:]
        else:
            grupos.append(atual)
            atual = []

    for indice, palavra in enumerate(palavras):
        atual.append(palavra)
        proxima = palavras[indice + 1] if indice + 1 < len(palavras) else None

        texto = _texto(atual)
        duracao = atual[-1].end - atual[0].start
        pausa = (proxima.start - palavra.end) if proxima else float("inf")
        fim_de_frase = palavra.text.endswith(_FIM_DE_FRASE)

        if len(texto) > regras.max_chars_per_cue or duracao > regras.max_duration:
            # Estourou COM esta palavra: ela volta para o proximo grupo, e ainda
            # recuamos ate uma fronteira que nao parta uma ideia ao meio.
            if len(atual) > 1:
                sobra = atual[:-1]
                recuo = _recuar_para_boa_fronteira(sobra, palavra, regras)
                grupos.append(sobra[: len(sobra) - recuo] if recuo else sobra)
                atual = sobra[len(sobra) - recuo :] + [palavra] if recuo else [palavra]
            else:
                fechar()
            continue

        if proxima is None:
            continue

        # Nunca terminar a legenda separando preposicao, artigo ou simbolo do
        # que vem depois.
        if _fronteira_ruim(atual, proxima):
            continue

        if pausa >= regras.hard_pause:
            fechar()
        elif pausa >= regras.pause_split and (fim_de_frase or len(texto) > 24):
            fechar()
        elif fim_de_frase:
            # Fim de frase fecha quando a proxima frase nao caberia junto -- e o
            # que evita "beleza? Hoje a gente vai" numa legenda so.
            restante = _texto([p for p in palavras[indice + 1 :][:12]])
            if len(texto) + 1 + len(restante) > regras.max_chars_per_cue:
                fechar()

    fechar()
    return [g for g in grupos if g]


def _dividir_grupo(grupo: list[Word], regras: CueRules) -> list[list[Word]]:
    """Parte um grupo que nao cabe em 2 linhas, no melhor ponto sintatico.

    E o que acontece quando `wrap` devolve None: em vez de abrir uma terceira
    linha, mostramos duas legendas em sequencia.
    """
    if len(grupo) < 2:
        return [grupo]

    texto = _texto(grupo)
    corte = best_split(texto, regras.max_chars_per_line)
    if corte is None or corte >= len(grupo):
        # Sem ponto sintatico viavel: parte no meio, que ao menos respeita o
        # limite de caracteres.
        corte = len(grupo) // 2

    esquerda, direita = grupo[:corte], grupo[corte:]
    if not esquerda or not direita:
        return [grupo]

    resultado: list[list[Word]] = []
    for metade in (esquerda, direita):
        if wrap(_texto(metade), regras.max_chars_per_line, regras.max_lines) is None:
            resultado.extend(_dividir_grupo(metade, regras))
        else:
            resultado.append(metade)
    return resultado


def _ajustar_tempos(cues: list[Cue], regras: CueRules) -> list[Cue]:
    """Aplica entrada, saida, duracao minima e o respiro entre legendas."""
    ajustados: list[Cue] = []

    for indice, cue in enumerate(cues):
        inicio = max(0.0, cue.start - regras.lead_in)
        fim = cue.end + regras.lead_out

        anterior_fim = ajustados[-1].end if ajustados else 0.0
        proxima_inicio = cues[indice + 1].start if indice + 1 < len(cues) else None

        # Nao invadir a legenda anterior.
        inicio = max(inicio, anterior_fim + regras.min_gap)
        # Nem a proxima.
        if proxima_inicio is not None:
            teto = proxima_inicio - regras.lead_in - regras.min_gap
            fim = min(fim, teto) if teto > inicio else fim

        # Curta demais: estica ate onde a proxima permitir.
        if fim - inicio < regras.min_duration:
            desejado = inicio + regras.min_duration
            if proxima_inicio is not None:
                fim = min(desejado, proxima_inicio - regras.min_gap)
            else:
                fim = desejado
        # Se ainda ficou abaixo do piso absoluto, aceita o piso.
        if fim - inicio < regras.floor_duration:
            fim = inicio + regras.floor_duration

        if fim <= inicio:
            fim = inicio + regras.floor_duration

        ajustados.append(replace(cue, start=inicio, end=fim))

    return ajustados


def build_cues(
    palavras: Sequence[Word], regras: Optional[CueRules] = None
) -> list[Cue]:
    """Transforma palavras com tempo em legendas prontas para exibir."""
    regras = regras or CueRules()
    palavras = [p for p in palavras if p.text.strip()]
    if not palavras:
        return []

    grupos: list[list[Word]] = []
    for grupo in _agrupar(palavras, regras):
        if wrap(_texto(grupo), regras.max_chars_per_line, regras.max_lines) is None:
            grupos.extend(_dividir_grupo(grupo, regras))
        else:
            grupos.append(grupo)

    brutos: list[Cue] = []
    for grupo in grupos:
        linhas = wrap(_texto(grupo), regras.max_chars_per_line, regras.max_lines)
        if linhas is None:
            # Ultimo recurso: trunca no limite em vez de descartar a fala.
            linhas = [_texto(grupo)[: regras.max_chars_per_line]]
        brutos.append(Cue(start=grupo[0].start, end=grupo[-1].end, lines=tuple(linhas)))

    return _ajustar_tempos(brutos, regras)
