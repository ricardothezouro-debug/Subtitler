"""Os tres formatos de saida, conferidos caractere a caractere.

Formato de legenda e um daqueles casos em que "quase certo" quebra o player sem
dar erro: virgula trocada por ponto, LF onde devia ser CRLF, um `&` nao
escapado. Por isso os testes comparam texto exato, nao "contem".
"""
from __future__ import annotations

from subtitler.core.cues import Cue
from subtitler.core.formats import dumps, write
from subtitler.core.formats import srt, txt, vtt


def cue(inicio: float, fim: float, *linhas: str) -> Cue:
    return Cue(start=inicio, end=fim, lines=tuple(linhas))


# --- timestamps --------------------------------------------------------------


def test_srt_usa_virgula_e_vtt_usa_ponto():
    """Trocar isso e o erro mais comum -- e o player recusa o arquivo inteiro."""
    assert srt.format_timestamp(3723.004) == "01:02:03,004"
    assert vtt.format_timestamp(3723.004) == "01:02:03.004"


def test_timestamp_com_horas_e_zero():
    assert srt.format_timestamp(0.0) == "00:00:00,000"
    assert vtt.format_timestamp(0.0) == "00:00:00.000"


def test_timestamp_arredonda_milissegundos():
    assert srt.format_timestamp(1.2345) == "00:00:01,234"
    assert srt.format_timestamp(1.2356) == "00:00:01,236"


def test_timestamp_negativo_vira_zero():
    """Lead-in pode empurrar o inicio para antes de zero."""
    assert srt.format_timestamp(-0.5) == "00:00:00,000"


# --- SRT ---------------------------------------------------------------------


def test_srt_completo():
    saida = dumps([cue(0.0, 1.5, "Primeira linha", "Segunda linha"),
                   cue(2.0, 3.0, "Sozinha")], "srt")
    esperado = (
        "1\r\n"
        "00:00:00,000 --> 00:00:01,500\r\n"
        "Primeira linha\r\nSegunda linha\r\n"
        "\r\n"
        "2\r\n"
        "00:00:02,000 --> 00:00:03,000\r\n"
        "Sozinha\r\n"
    )
    assert saida == esperado


def test_srt_nao_escapa_tags():
    """`<i>` e formatacao valida em SRT; escapar quebraria o italico."""
    saida = dumps([cue(0.0, 1.0, "<i>sussurrando</i> & tal")], "srt")
    assert "<i>sussurrando</i> & tal" in saida
    assert "&amp;" not in saida


def test_srt_indices_comecam_em_um():
    saida = dumps([cue(0, 1, "a"), cue(2, 3, "b"), cue(4, 5, "c")], "srt")
    assert saida.startswith("1\r\n")
    assert "\r\n2\r\n" in saida
    assert "\r\n3\r\n" in saida


# --- VTT ---------------------------------------------------------------------


def test_vtt_tem_cabecalho_e_usa_lf():
    saida = dumps([cue(0.0, 1.0, "Ola")], "vtt")
    assert saida.startswith("WEBVTT\n\n")
    assert "\r\n" not in saida


def test_vtt_escapa_o_que_e_sintaxe():
    """Aqui `&` e `<` SAO sintaxe -- sem escapar, a renderizacao quebra."""
    saida = dumps([cue(0.0, 1.0, "R&D e 5 < 10 > 3")], "vtt")
    assert "R&amp;D e 5 &lt; 10 &gt; 3" in saida


def test_vtt_escapa_e_comercial_antes_dos_sinais():
    """Ordem importa: escapar `<` antes de `&` geraria `&amp;lt;`."""
    assert vtt.escape("<") == "&lt;"
    assert vtt.escape("&lt;") == "&amp;lt;"


# --- TXT ---------------------------------------------------------------------


def test_txt_junta_em_paragrafo_corrido():
    saida = dumps([cue(0.0, 1.0, "Primeira parte"), cue(1.1, 2.0, "segunda parte")], "txt")
    assert saida.strip() == "Primeira parte segunda parte"


def test_txt_quebra_paragrafo_em_pausa_longa():
    saida = dumps(
        [cue(0.0, 1.0, "Fim de um assunto"), cue(5.0, 6.0, "Comeco de outro")], "txt"
    )
    assert saida.strip().split("\n\n") == ["Fim de um assunto", "Comeco de outro"]


def test_txt_com_tempos_prefixa_o_paragrafo():
    saida = dumps([cue(65.0, 66.0, "Ola")], "txt", com_tempos=True)
    assert saida.startswith("[00:01:05] Ola")


def test_txt_vazio():
    assert dumps([], "txt") == ""


# --- escrita em disco --------------------------------------------------------


def test_write_preserva_crlf_do_srt(tmp_path):
    """newline="" e obrigatorio: sem ele o Windows transformaria \\r\\n em \\r\\r\\n."""
    destino = write([cue(0.0, 1.0, "teste")], tmp_path / "a.srt", "srt")
    bruto = destino.read_bytes()
    assert b"\r\n" in bruto
    assert b"\r\r\n" not in bruto


def test_write_grava_utf8_sem_bom(tmp_path):
    destino = write([cue(0.0, 1.0, "coração é ótimo")], tmp_path / "a.vtt", "vtt")
    bruto = destino.read_bytes()
    assert not bruto.startswith(b"\xef\xbb\xbf")
    assert "coração é ótimo" in bruto.decode("utf-8")


def test_formato_desconhecido_falha_claro():
    import pytest

    with pytest.raises(ValueError, match="desconhecido"):
        dumps([], "ass")
