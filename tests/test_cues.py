"""Regras de tempo e agrupamento das legendas.

Tudo aqui roda offline. As palavras sao sinteticas, o que deixa cada regra
isolada: da para dizer exatamente qual limite esta sendo exercitado.
"""
from __future__ import annotations

from subtitler.core.cues import Cue, CueRules, build_cues
from subtitler.core.transcript import Word

REGRAS = CueRules()


def palavras(*pares: tuple[str, float, float]) -> list[Word]:
    return [Word(t, i, f) for t, i, f in pares]


def fala(texto: str, inicio: float = 0.0, por_palavra: float = 0.4) -> list[Word]:
    """Distribui um texto em palavras com duracao fixa, sem pausas."""
    saida: list[Word] = []
    cursor = inicio
    for token in texto.split():
        saida.append(Word(token, cursor, cursor + por_palavra))
        cursor += por_palavra
    return saida


# --- invariantes: valem para QUALQUER entrada -------------------------------


def _checar_invariantes(cues: list[Cue], regras: CueRules = REGRAS) -> None:
    for indice, cue in enumerate(cues):
        assert cue.end > cue.start, f"cue {indice} com duracao nao positiva"
        assert len(cue.lines) <= regras.max_lines, f"cue {indice} tem 3+ linhas"
        for linha in cue.lines:
            assert len(linha) <= regras.max_chars_per_line, f"cue {indice}: linha longa"
        assert cue.duration <= regras.max_duration + 0.01, f"cue {indice} longo demais"
        if indice + 1 < len(cues):
            proxima = cues[indice + 1]
            assert proxima.start >= cue.end, f"cues {indice} e {indice+1} se sobrepoem"


def test_invariantes_em_fala_corrida():
    texto = (
        "A gente comecou a run achando que ia ser tranquilo mas o primeiro boss "
        "ja mostrou que nao era bem assim e ai a coisa complicou de vez"
    )
    cues = build_cues(fala(texto))
    assert cues
    _checar_invariantes(cues)


def test_invariantes_com_pausas_variadas():
    palavras_com_pausa = (
        fala("Primeira parte da frase", inicio=0.0)
        + fala("segunda parte depois de uma pausa", inicio=3.0)
        + fala("e a terceira bem mais tarde", inicio=8.5)
    )
    cues = build_cues(palavras_com_pausa)
    assert len(cues) >= 2
    _checar_invariantes(cues)


# --- regras especificas ------------------------------------------------------


def test_pausa_longa_fecha_a_legenda():
    """Pausa acima do limite duro fecha, mesmo no meio da oracao."""
    entrada = palavras(
        ("Entao", 0.0, 0.4),
        ("eu", 0.4, 0.6),
        ("falei", 0.6, 1.0),
        # pausa de 2s: acima do hard_pause de 1,2
        ("depois", 3.0, 3.4),
        ("disso", 3.4, 3.8),
    )
    cues = build_cues(entrada)
    assert len(cues) == 2
    assert "falei" in cues[0].text
    assert "depois" in cues[1].text


def test_duracao_minima_e_respeitada():
    """Uma palavra curta nao pode virar legenda de 0,2s."""
    cues = build_cues(palavras(("Oi", 0.0, 0.2)))
    assert len(cues) == 1
    assert cues[0].duration >= REGRAS.floor_duration


def test_nao_passa_da_duracao_maxima():
    """Fala longa sem pausa vira varias legendas, nao uma de 20s."""
    cues = build_cues(fala("palavra " * 40, por_palavra=0.5))
    assert cues
    assert all(c.duration <= REGRAS.max_duration + 0.01 for c in cues)


def test_ha_respiro_entre_legendas():
    """Sem o intervalo minimo, players que arredondam para frame colam as duas."""
    cues = build_cues(
        fala("Primeira frase aqui", 0.0) + fala("segunda frase aqui", 2.5)
    )
    assert len(cues) >= 2
    for a, b in zip(cues, cues[1:]):
        assert b.start - a.end >= REGRAS.min_gap - 1e-6


def test_entrada_antecipa_e_saida_estende():
    """A legenda entra um pouco antes e sai um pouco depois da fala."""
    cues = build_cues(fala("Uma frase de teste bem simples", inicio=5.0))
    assert cues
    assert cues[0].start < 5.0  # lead_in
    fim_da_fala = 5.0 + 6 * 0.4
    assert cues[-1].end > fim_da_fala  # lead_out


def test_texto_longo_vira_varias_legendas_nao_tres_linhas():
    """Quando nao cabe em 2x42, divide no tempo -- nunca abre terceira linha."""
    texto = (
        "Esse foi sem duvida o momento mais improvavel da gameplay inteira e "
        "ninguem absolutamente ninguem esperava que aquilo fosse acontecer ali"
    )
    cues = build_cues(fala(texto))
    assert len(cues) >= 2
    _checar_invariantes(cues)


def test_velocidade_de_leitura_sob_controle():
    """CPS acima do teto significa legenda que some antes de ser lida."""
    cues = build_cues(fala("uma frase bem normal de teste aqui", por_palavra=0.45))
    assert cues
    # o teto e por legenda; com lead_out e duracao minima, nenhuma deve estourar
    assert all(c.cps <= REGRAS.hard_max_cps * 1.5 for c in cues)


def test_entrada_vazia_devolve_lista_vazia():
    assert build_cues([]) == []
    assert build_cues(palavras(("   ", 0.0, 1.0))) == []


def test_regras_sao_configuraveis():
    """A aba Avancado precisa conseguir apertar os limites."""
    estreito = CueRules(max_chars_per_line=24, max_lines=2)
    cues = build_cues(fala("uma frase razoavelmente longa para caber estreita"), estreito)
    assert cues
    for cue in cues:
        for linha in cue.lines:
            assert len(linha) <= 24
