"""O idioma entre fatias -- a maior fonte de palavra trocada num VOD longo."""
from __future__ import annotations

from pathlib import Path

import pytest

from subtitler.core.groq_client import codigo_de_idioma
from subtitler.core.pipeline import Job, _fixar_idioma, _transcrever_com_paciencia


def test_codigo_de_idioma_traduz_o_nome_por_extenso():
    """A API devolve "portuguese"; o campo `language` da requisicao quer "pt"."""
    assert codigo_de_idioma("portuguese") == "pt"
    assert codigo_de_idioma("Portuguese") == "pt"
    assert codigo_de_idioma("  ENGLISH ") == "en"
    assert codigo_de_idioma("pt") == "pt"


def test_codigo_de_idioma_nao_inventa_quando_nao_conhece():
    """Devolver lixo aqui seria pior que continuar em auto."""
    assert codigo_de_idioma("klingon") == ""
    assert codigo_de_idioma(None) == ""
    assert codigo_de_idioma(123) == ""
    assert codigo_de_idioma("") == ""


def test_fixar_idioma_so_age_uma_vez():
    assert _fixar_idioma("auto", {"language": "portuguese"}) == "pt"
    # ja resolvido: uma fatia que detectou espanhol nao muda o resto
    assert _fixar_idioma("pt", {"language": "spanish"}) == "pt"
    # escolha explicita do usuario e intocavel
    assert _fixar_idioma("en", {"language": "portuguese"}) == "en"
    # resposta sem idioma reconhecivel mantem auto
    assert _fixar_idioma("auto", {"language": "klingon"}) == "auto"
    assert _fixar_idioma("auto", {}) == "auto"
    assert _fixar_idioma("auto", None) == "auto"


class _ClienteFalso:
    def __init__(self) -> None:
        self.idiomas_recebidos: list[str] = []

    def transcribe(self, audio, idioma="auto", prompt="", progresso=None, cancelar=None):
        self.idiomas_recebidos.append(idioma)
        return {"language": "portuguese", "text": "oi", "words": [], "segments": []}


def test_a_fatia_seguinte_recebe_o_idioma_ja_detectado(tmp_path: Path):
    """Sem isto, cada fatia era detectada isolada.

    Num VOD dividido em 18 partes o Whisper podia decidir "espanhol" ou
    "galego" num trecho de portugues -- e o texto saia cheio de palavra
    trocada, sem erro nenhum aparecendo na tela.
    """
    cliente = _ClienteFalso()
    job = Job(origem=tmp_path / "v.mp4", saida=tmp_path, idioma="auto")
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"")

    idioma = job.idioma
    for _ in range(3):
        bruto = _transcrever_com_paciencia(
            cliente, audio, job, idioma, lambda: False, None, lambda *a: None
        )
        idioma = _fixar_idioma(idioma, bruto)

    assert cliente.idiomas_recebidos == ["auto", "pt", "pt"]


def test_escolha_explicita_do_usuario_vale_para_todas_as_fatias(tmp_path: Path):
    cliente = _ClienteFalso()
    job = Job(origem=tmp_path / "v.mp4", saida=tmp_path, idioma="en")
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"")

    idioma = job.idioma
    for _ in range(3):
        bruto = _transcrever_com_paciencia(
            cliente, audio, job, idioma, lambda: False, None, lambda *a: None
        )
        idioma = _fixar_idioma(idioma, bruto)

    # a API respondeu "portuguese" toda vez; a escolha do usuario ganha
    assert cliente.idiomas_recebidos == ["en", "en", "en"]
