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


# --- A chave do cache -------------------------------------------------------


def _job(tmp_path: Path, **kwargs) -> Job:
    return Job(origem=tmp_path / "live.mp4", saida=tmp_path, **kwargs)


def test_trocar_de_modelo_nao_reaproveita_a_transcricao_antiga(tmp_path: Path):
    """Era isto que devolvia o resultado velho em dois segundos.

    O usuario trocava para o modelo preciso, mandava rodar de novo, e o
    pipeline achava as partes em cache -- gravadas pelo modelo anterior -- e
    pulava a transcricao inteira. A opcao nova nao tinha efeito nenhum e nada
    na tela dizia isso.
    """
    rapido = _job(tmp_path, modelo="whisper-large-v3-turbo")
    preciso = _job(tmp_path, modelo="whisper-large-v3")
    assert rapido.id != preciso.id


def test_trocar_de_idioma_ou_de_termos_tambem_refaz(tmp_path: Path):
    base = _job(tmp_path, idioma="auto")
    assert base.id != _job(tmp_path, idioma="pt").id
    assert base.id != _job(tmp_path, idioma="auto", prompt="Wo Long, DREDGE").id


def test_mudar_so_o_formato_de_saida_reaproveita(tmp_path: Path):
    """Gerar VTT depois do SRT nao pode custar uma transcricao nova."""
    srt = _job(tmp_path, formatos=("srt",))
    vtt = _job(tmp_path, formatos=("vtt", "txt"), txt_com_tempos=True)
    assert srt.id == vtt.id


def test_o_mesmo_pedido_continua_retomavel(tmp_path: Path):
    """A retomada e o motivo do cache existir: cair na parte 12 de 18 e
    continuar dali."""
    assert _job(tmp_path, idioma="pt").id == _job(tmp_path, idioma="pt").id
