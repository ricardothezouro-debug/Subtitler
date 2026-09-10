"""Onde quebrar a linha de uma legenda.

Quebrar no lugar errado custa mais legibilidade do que quase qualquer outra
coisa numa legenda. "de | manha" e "R$ | 1.500" obrigam o olho a voltar; ja
quebrar depois de uma virgula acompanha a respiracao de quem fala.

A escolha e feita por penalidade: entre todos os espacos possiveis, vence o de
menor custo. Alguns espacos tem custo infinito -- sao os que nunca podem ser
escolhidos, mesmo que o resultado fique desequilibrado.

Funcao pura: entra texto, sai lista de linhas. Nenhuma rede, nenhum Qt.
"""
from __future__ import annotations

import re
from typing import Optional

MAX_CHARS_POR_LINHA = 42
MAX_LINHAS = 2

PROIBIDO = float("inf")

# Palavras que puxam o que vem depois: quebrar entre elas e o proximo termo
# separa coisas que se leem juntas.
_ARTIGOS_E_DETERMINANTES = {
    "o", "a", "os", "as", "um", "uma", "uns", "umas",
    "este", "esta", "estes", "estas", "esse", "essa", "esses", "essas",
    "aquele", "aquela", "aqueles", "aquelas", "meu", "minha", "seu", "sua",
    "nosso", "nossa", "dele", "dela", "cada", "todo", "toda", "todos", "todas",
}
_PREPOSICOES = {
    "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
    "para", "pra", "por", "pelo", "pela", "com", "sem", "sob", "sobre",
    "entre", "ate", "desde", "apos", "ante", "contra", "perante", "a", "ao", "aos",
}
_PRONOMES_OBLIQUOS = {"me", "te", "se", "lhe", "nos", "vos", "lhes", "o", "a"}
_CONJUNCOES = {
    "e", "mas", "porem", "porque", "que", "quando", "se", "ou", "entao",
    "embora", "pois", "como", "onde", "enquanto", "portanto", "logo", "ja",
}
_UNIDADES = {
    "km", "m", "cm", "mm", "kg", "g", "mg", "l", "ml", "h", "min", "s",
    "%", "reais", "mil", "milhoes", "bilhoes", "fps", "gb", "mb", "kb", "tb",
}
_SIMBOLOS_ANTES_DE_NUMERO = {"r$", "us$", "$", "€", "£", "#", "n°", "nº"}

_FIM_DE_FRASE = (".", "!", "?", "…")
_PAUSA_MEDIA = (",", ";", ":", "—", "–")

_ESPACOS = re.compile(r"\s+")
_SO_LETRAS = re.compile(r"[^\w]", re.UNICODE)


def normalizar(texto: str) -> str:
    """Colapsa espacos e cola a pontuacao na palavra anterior."""
    limpo = _ESPACOS.sub(" ", str(texto or "")).strip()
    return re.sub(r"\s+([,.;:!?…])", r"\1", limpo)


def _nu(palavra: str) -> str:
    """A palavra sem pontuacao nem acento de comparacao, em minusculas."""
    return _SO_LETRAS.sub("", palavra).casefold()


def _e_numero(palavra: str) -> bool:
    return bool(re.match(r"^[\d.,]+$", palavra.strip()))


def peso_sintatico(anterior: str, seguinte: str) -> float:
    """Custo de quebrar a linha ENTRE estas duas palavras.

    Menor e melhor. `PROIBIDO` nunca e escolhido.
    """
    ant = anterior.strip()
    seg = seguinte.strip()
    ant_nu = _nu(ant)
    seg_nu = _nu(seg)

    # --- proibicoes: separam coisas que se leem como uma unidade ------------
    if ant_nu in _ARTIGOS_E_DETERMINANTES:
        return PROIBIDO
    if ant_nu in _PREPOSICOES:
        return PROIBIDO
    if ant_nu in _PRONOMES_OBLIQUOS and not ant.endswith(_FIM_DE_FRASE):
        return PROIBIDO
    # numero e a unidade que o acompanha: "10 | km", "5 | %"
    if _e_numero(ant) and (seg_nu in _UNIDADES or seg.startswith("%")):
        return PROIBIDO
    # simbolo e o numero que ele qualifica: "R$ | 1.500"
    if ant.casefold() in _SIMBOLOS_ANTES_DE_NUMERO and _e_numero(seg):
        return PROIBIDO
    # nome proprio composto: "Joao | da Silva"
    if ant[:1].isupper() and seg_nu in _PREPOSICOES:
        return PROIBIDO
    # sigla pontuada no meio
    if len(ant) <= 2 and ant.endswith(".") and seg[:1].isupper():
        return PROIBIDO

    # --- preferencias -------------------------------------------------------
    if ant.endswith(_FIM_DE_FRASE):
        return 0.0
    if ant.endswith(_PAUSA_MEDIA):
        return 1.0
    if seg_nu in _CONJUNCOES:
        return 2.0
    if seg_nu in _PREPOSICOES:
        return 3.0
    return 6.0


def _custo_total(anterior: str, seguinte: str, len1: int, len2: int) -> float:
    base = peso_sintatico(anterior, seguinte)
    if base == PROIBIDO:
        return PROIBIDO
    # Desequilibrio pesa, e linha de cima maior pesa um pouco mais: legenda
    # "bottom-heavy" cobre menos imagem e e a convencao dos guias de estilo.
    desequilibrio = abs(len1 - len2) / 8.0
    topo_maior = 1.0 if len1 > len2 else 0.0
    return base + desequilibrio + topo_maior


def best_split(texto: str, max_chars: int = MAX_CHARS_POR_LINHA) -> Optional[int]:
    """Indice da palavra que inicia a segunda linha, ou None se nao houver corte.

    Devolve None quando nenhum corte deixa as duas linhas dentro do limite.
    """
    palavras = normalizar(texto).split(" ")
    if len(palavras) < 2:
        return None

    melhor_indice: Optional[int] = None
    melhor_custo = PROIBIDO

    for corte in range(1, len(palavras)):
        linha1 = " ".join(palavras[:corte])
        linha2 = " ".join(palavras[corte:])
        if len(linha1) > max_chars or len(linha2) > max_chars:
            continue
        # Uma linha muito menor que a outra fica visualmente estranha, mas isso
        # e preferencia, nao proibicao: so entra no custo.
        custo = _custo_total(palavras[corte - 1], palavras[corte], len(linha1), len(linha2))
        if custo < melhor_custo:
            melhor_custo = custo
            melhor_indice = corte

    return melhor_indice if melhor_custo < PROIBIDO else None


def wrap(
    texto: str,
    max_chars: int = MAX_CHARS_POR_LINHA,
    max_lines: int = MAX_LINHAS,
) -> Optional[list[str]]:
    """Quebra o texto em ate `max_lines` linhas de ate `max_chars`.

    Devolve None quando nao cabe -- e o sinal para quem chamou DIVIDIR A LEGENDA
    NO TEMPO em vez de gerar uma terceira linha. Tres linhas cobrem imagem
    demais; e melhor mostrar duas legendas em sequencia.
    """
    limpo = normalizar(texto)
    if not limpo:
        return None
    # Uma linha so, quando cabe: legenda de uma linha e lida mais rapido.
    if len(limpo) <= max_chars:
        return [limpo]
    if max_lines < 2:
        return None

    corte = best_split(limpo, max_chars)
    if corte is None:
        return None

    palavras = limpo.split(" ")
    return [" ".join(palavras[:corte]), " ".join(palavras[corte:])]
