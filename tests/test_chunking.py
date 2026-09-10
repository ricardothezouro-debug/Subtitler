"""Deteccao de silencio e plano de corte.

Offline: o stderr do ffmpeg e um fixture de texto, e os silencios sao listas
sinteticas. O que se testa aqui e a decisao, nao a execucao.
"""
from __future__ import annotations

from pathlib import Path

from subtitler.core.silence import (
    MAX_SEGUNDOS,
    Silencio,
    parse_silencedetect,
    plan_chunks,
)

STDERR = """\
[silencedetect @ 0x14f] silence_start: 12.5
[silencedetect @ 0x14f] silence_end: 13.2 | silence_duration: 0.7
[silencedetect @ 0x14f] silence_start: 601.44
[silencedetect @ 0x14f] silence_end: 603.1 | silence_duration: 1.66
[silencedetect @ 0x14f] silence_start: 1180.0
[silencedetect @ 0x14f] silence_end: 1180.5 | silence_duration: 0.5
"""


def test_le_os_silencios_do_stderr():
    silencios = parse_silencedetect(STDERR)
    assert len(silencios) == 3
    assert silencios[1].start == 601.44
    assert silencios[1].end == 603.1
    assert abs(silencios[1].duracao - 1.66) < 0.01
    assert abs(silencios[1].meio - 602.27) < 0.01


def test_stderr_sem_silencio_devolve_lista_vazia():
    assert parse_silencedetect("") == []
    assert parse_silencedetect("nada aqui") == []


def test_par_incompleto_e_ignorado():
    """Silencio que comeca e nao termina (fim do arquivo) nao vira fatia."""
    assert parse_silencedetect("silence_start: 5.0") == []


# --- plano de corte ----------------------------------------------------------


def test_audio_curto_nao_e_fatiado():
    fatias = plan_chunks(300.0, [])
    assert len(fatias) == 1
    assert fatias[0].start == 0.0 and fatias[0].end == 300.0


def test_corta_no_meio_do_silencio_quando_existe():
    silencios = parse_silencedetect(STDERR)
    fatias = plan_chunks(1500.0, silencios)
    assert len(fatias) >= 2
    # a primeira fatia termina no meio do silencio de ~602s
    assert abs(fatias[0].end - 602.27) < 0.01
    assert fatias[0].corte_duro is False


def test_corte_duro_quando_nao_ha_silencio_perto():
    fatias = plan_chunks(1500.0, [])
    assert fatias[0].corte_duro is True
    # a fatia seguinte comeca ANTES do fim da anterior: e a sobreposicao que
    # evita perder a palavra que estava sendo dita
    assert fatias[1].start < fatias[0].end


def test_nenhuma_fatia_passa_do_maximo():
    silencios = [Silencio(1400.0, 1402.0)]  # silencio longe demais do alvo
    for fatias in (plan_chunks(5000.0, []), plan_chunks(5000.0, silencios)):
        assert all(f.duracao <= MAX_SEGUNDOS + 0.01 for f in fatias)


def test_cobertura_continua_do_inicio_ao_fim():
    """Nenhum buraco: cada fatia comeca no fim da anterior (ou antes, se houve
    sobreposicao). Um buraco significaria fala perdida."""
    fatias = plan_chunks(3000.0, parse_silencedetect(STDERR))
    assert fatias[0].start == 0.0
    assert abs(fatias[-1].end - 3000.0) < 0.01
    for anterior, seguinte in zip(fatias, fatias[1:]):
        assert seguinte.start <= anterior.end


def test_duracao_zero_devolve_nada():
    assert plan_chunks(0.0, []) == []


def test_indices_sao_sequenciais():
    fatias = plan_chunks(3000.0, [])
    assert [f.indice for f in fatias] == list(range(len(fatias)))


# --- O limiar de silencio numa live com jogo ao fundo ------------------------


class _FfmpegFalso:
    """Responde como o ffmpeg responderia para audio com fundo constante.

    So encontra pausas quando o limiar desce o suficiente -- e o que acontece
    numa live: o audio do jogo nunca deixa o sinal cair abaixo de -30 dB.
    """

    def __init__(self, limiar_que_funciona: float) -> None:
        self.limiar_que_funciona = limiar_que_funciona
        self.tentativas: list[float] = []

    def __call__(self, binario, args):
        limiar = float(
            [a for a in args if "silencedetect" in a][0]
            .split("noise=")[1]
            .split("dB")[0]
        )
        self.tentativas.append(limiar)
        if limiar > self.limiar_que_funciona:
            return ""  # nada abaixo do limiar: nenhuma pausa encontrada
        return "".join(
            f"[silencedetect @ 0x0] silence_start: {i * 100}\n"
            f"[silencedetect @ 0x0] silence_end: {i * 100 + 1.2} | "
            f"silence_duration: 1.2\n"
            for i in range(1, 6)
        )


def test_afrouxa_o_limiar_quando_o_fundo_nao_deixa_achar_pausa(monkeypatch):
    """Sem isto, live com jogo ao fundo nao tinha UMA pausa para cortar.

    E ai todo corte virava corte duro no relogio, com 2s de sobreposicao em
    cada costura -- fonte de frase repetida e de fala perdida.
    """
    from subtitler.core import silence
    from subtitler.core.ffmpeg_locator import Ferramentas

    falso = _FfmpegFalso(limiar_que_funciona=-40.0)
    monkeypatch.setattr(silence, "run", falso)

    achados = silence.detect(Ferramentas("ffmpeg", "ffprobe"), Path("x.flac"))

    assert len(achados) == 5, "devia ter achado as pausas ao afrouxar"
    assert falso.tentativas == [-30.0, -40.0], "parou assim que achou o bastante"


def test_audio_limpo_nao_afrouxa_a_toa(monkeypatch):
    """Afrouxar sem precisar cortaria no meio de uma respiracao curta."""
    from subtitler.core import silence
    from subtitler.core.ffmpeg_locator import Ferramentas

    falso = _FfmpegFalso(limiar_que_funciona=-30.0)
    monkeypatch.setattr(silence, "run", falso)

    silence.detect(Ferramentas("ffmpeg", "ffprobe"), Path("x.flac"))
    assert falso.tentativas == [-30.0], "uma passada basta em audio limpo"


def test_limiar_explicito_e_respeitado(monkeypatch):
    from subtitler.core import silence
    from subtitler.core.ffmpeg_locator import Ferramentas

    falso = _FfmpegFalso(limiar_que_funciona=-50.0)
    monkeypatch.setattr(silence, "run", falso)

    silence.detect(Ferramentas("ffmpeg", "ffprobe"), Path("x.flac"), ruido_db=-35.0)
    assert falso.tentativas == [-35.0], "quem pede um limiar quer aquele limiar"
