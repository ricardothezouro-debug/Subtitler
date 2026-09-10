"""Leitura e saneamento da resposta da API.

Tudo offline: as respostas sao fixtures escritos a mao, no formato que a Groq
devolve com `verbose_json` + timestamps por palavra.
"""
from __future__ import annotations

from subtitler.core.transcript import (
    Segment,
    Transcript,
    Word,
    from_verbose_json,
    merge,
    sanitize,
)


def resposta(palavras, segmentos=None, idioma="pt"):
    return {
        "language": idioma,
        "words": [{"word": t, "start": i, "end": f} for t, i, f in palavras],
        "segments": segmentos or [],
    }


def test_le_palavras_e_idioma():
    t = from_verbose_json(resposta([("Ola", 0.0, 0.4), ("mundo", 0.5, 1.0)]))
    assert [w.text for w in t.words] == ["Ola", "mundo"]
    assert t.language == "pt"
    assert t.word_level is True


def test_offset_desloca_todos_os_tempos():
    """Cada fatia volta com tempos relativos a ela; o offset devolve a fatia
    para a linha do tempo do arquivo inteiro."""
    t = from_verbose_json(resposta([("um", 0.0, 0.5), ("dois", 1.0, 1.5)]), offset=600.0)
    assert t.words[0].start == 600.0
    assert t.words[1].end == 601.5


def test_aceita_json_em_texto():
    import json

    t = from_verbose_json(json.dumps(resposta([("oi", 0.0, 0.3)])))
    assert t.words[0].text == "oi"


def test_estima_tempos_quando_faltam_palavras():
    """Acontece de a API nao devolver `words`. Sem este resgate o trabalho
    inteiro morreria por falta de tempos."""
    payload = {
        "language": "pt",
        "segments": [{"text": "uma frase curta", "start": 0.0, "end": 3.0}],
    }
    t = from_verbose_json(payload)
    assert t.word_level is False, "precisa sinalizar que o timing e aproximado"
    assert [w.text for w in t.words] == ["uma", "frase", "curta"]
    assert t.words[0].start == 0.0
    assert abs(t.words[-1].end - 3.0) < 0.01
    # palavra mais longa recebe mais tempo que palavra curta
    assert t.words[1].duration > t.words[0].duration


def test_payload_invalido_nao_explode():
    assert from_verbose_json(None).words == []
    assert from_verbose_json([]).words == []
    assert from_verbose_json({}).words == []


# --- merge -------------------------------------------------------------------


def test_merge_concatena_fatias():
    a = Transcript(words=[Word("um", 0.0, 0.5)])
    b = Transcript(words=[Word("dois", 10.0, 10.5)])
    assert [w.text for w in merge([a, b]).words] == ["um", "dois"]


def test_merge_remove_frase_repetida_na_costura():
    """Em corte sem silencio damos sobreposicao para nao perder palavra -- e o
    Whisper transcreve o mesmo trecho duas vezes."""
    a = Transcript(words=[Word("e", 8.0, 8.2), Word("ai", 8.3, 8.6), Word("galera", 8.7, 9.2)])
    b = Transcript(words=[Word("e", 8.3, 8.5), Word("ai", 8.6, 8.9),
                          Word("galera", 9.0, 9.5), Word("bora", 9.6, 10.0)])
    juntado = merge([a, b], cortes_duros={1})
    assert [w.text for w in juntado.words] == ["e", "ai", "galera", "bora"]


def test_merge_sem_corte_duro_nao_remove_nada():
    """Repeticao legitima ("muito, muito bom") nao pode ser comida."""
    a = Transcript(words=[Word("muito", 0.0, 0.4)])
    b = Transcript(words=[Word("muito", 0.5, 0.9), Word("bom", 1.0, 1.3)])
    assert len(merge([a, b]).words) == 3


def test_merge_propaga_timing_aproximado():
    a = Transcript(words=[Word("a", 0, 1)], word_level=True)
    b = Transcript(words=[Word("b", 2, 3)], word_level=False)
    assert merge([a, b]).word_level is False


# --- saneamento --------------------------------------------------------------


def test_conserta_tempo_que_anda_para_tras():
    t = Transcript(words=[Word("a", 0.0, 1.0), Word("b", 0.5, 1.5)])
    limpo = sanitize(t)
    assert limpo.words[1].start >= limpo.words[0].end


def test_da_duracao_minima_a_palavra_de_duracao_zero():
    limpo = sanitize(Transcript(words=[Word("a", 1.0, 1.0)]))
    assert limpo.words[0].end > limpo.words[0].start


def test_descarta_alucinacao_sobre_silencio():
    """Os dois criterios precisam bater; so um gera falso positivo e come fala
    baixa de verdade."""
    inventado = Segment("Legendas pela comunidade", 5.0, 8.0,
                        no_speech_prob=0.9, avg_logprob=-1.4)
    real = Segment("isso aqui e fala mesmo", 0.0, 3.0,
                   no_speech_prob=0.1, avg_logprob=-0.3)
    t = Transcript(
        words=[Word("fala", 1.0, 1.5), Word("inventada", 6.0, 6.5)],
        segments=[real, inventado],
    )
    limpo = sanitize(t)
    assert [w.text for w in limpo.words] == ["fala"]
    assert len(limpo.segments) == 1


def test_nao_descarta_fala_baixa_legitima():
    """no_speech alto mas logprob bom = fala real em volume baixo."""
    baixa = Segment("falando baixinho", 0.0, 2.0, no_speech_prob=0.8, avg_logprob=-0.2)
    t = Transcript(words=[Word("baixinho", 0.5, 1.0)], segments=[baixa])
    assert len(sanitize(t).words) == 1
