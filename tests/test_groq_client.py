"""Cliente da API, sem tocar a rede.

O `abrir` do cliente e injetavel justamente para isto: os testes trocam por uma
funcao falsa e conferem o que teria sido enviado.
"""
from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from subtitler.core.errors import ChaveRecusada, SemInternet
from subtitler.core.groq_client import (
    ArquivoGrandeDemais,
    GroqClient,
    LimiteDeUso,
    parse_retry_after,
)


class RespostaFalsa:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._corpo = json.dumps(payload).encode()
        self.status = status

    def read(self) -> bytes:
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def audio_falso(tmp_path: Path, tamanho: int = 2048) -> Path:
    caminho = tmp_path / "pedaco.flac"
    caminho.write_bytes(b"\x00" * tamanho)
    return caminho


def erro_http(codigo: int, headers=None, corpo: bytes = b"") -> urllib.error.HTTPError:
    import io

    return urllib.error.HTTPError(
        "https://x", codigo, "erro", headers or {}, io.BytesIO(corpo)
    )


# --- montagem do corpo -------------------------------------------------------


def test_envia_os_campos_certos(tmp_path):
    capturado = {}

    def abrir_falso(requisicao, timeout=None):
        capturado["headers"] = dict(requisicao.headers)
        # o corpo e um leitor com progresso; drena para inspecionar
        capturado["corpo"] = b"".join(iter(lambda: requisicao.data.read(8192), b""))
        return RespostaFalsa({"text": "ok", "words": [], "segments": []})

    cliente = GroqClient(api_key="chave-secreta", abrir=abrir_falso)
    cliente.transcribe(audio_falso(tmp_path), idioma="pt", prompt="Wo Long")

    corpo = capturado["corpo"].decode("utf-8", "replace")
    assert 'name="model"' in corpo and "whisper-large-v3" in corpo
    assert "verbose_json" in corpo
    assert 'name="language"' in corpo and "pt" in corpo
    assert "Wo Long" in corpo
    # Os DOIS granularities: palavra para o timing, segmento para a confianca.
    assert corpo.count('name="timestamp_granularities[]"') == 2
    assert "word" in corpo and "segment" in corpo
    assert 'filename="pedaco.flac"' in corpo


def test_cabecalhos_de_autenticacao_e_tamanho(tmp_path):
    capturado = {}

    def abrir_falso(requisicao, timeout=None):
        capturado.update({k.lower(): v for k, v in requisicao.headers.items()})
        return RespostaFalsa({})

    GroqClient(api_key="abc123", abrir=abrir_falso).transcribe(audio_falso(tmp_path))
    assert capturado["authorization"] == "Bearer abc123"
    assert capturado["content-type"].startswith("multipart/form-data; boundary=")
    assert int(capturado["content-length"]) > 0


def test_idioma_auto_nao_vai_no_corpo(tmp_path):
    capturado = {}

    def abrir_falso(requisicao, timeout=None):
        capturado["corpo"] = b"".join(iter(lambda: requisicao.data.read(8192), b""))
        return RespostaFalsa({})

    GroqClient(api_key="k", abrir=abrir_falso).transcribe(audio_falso(tmp_path), idioma="auto")
    assert 'name="language"' not in capturado["corpo"].decode("utf-8", "replace")


def test_corpo_temporario_e_apagado(tmp_path):
    """Sem isso, cada pedaco deixaria 25 MB de lixo no disco."""
    vistos = []

    def abrir_falso(requisicao, timeout=None):
        import tempfile

        vistos.extend(Path(tempfile.gettempdir()).glob("subtitler_upload_*"))
        return RespostaFalsa({})

    GroqClient(api_key="k", abrir=abrir_falso).transcribe(audio_falso(tmp_path))
    assert all(not caminho.exists() for caminho in vistos)


def test_recusa_arquivo_acima_do_limite(tmp_path):
    grande = tmp_path / "grande.flac"
    grande.write_bytes(b"\x00" * (25 * 1024 * 1024))
    with pytest.raises(ArquivoGrandeDemais):
        GroqClient(api_key="k", abrir=lambda *a, **k: RespostaFalsa({})).transcribe(grande)


# --- tratamento de erro ------------------------------------------------------


def test_401_vira_chave_recusada(tmp_path):
    def abrir_falso(*_, **__):
        raise erro_http(401)

    with pytest.raises(ChaveRecusada):
        GroqClient(api_key="ruim", abrir=abrir_falso).transcribe(audio_falso(tmp_path))


def test_429_carrega_o_tempo_de_espera(tmp_path):
    def abrir_falso(*_, **__):
        raise erro_http(429, {"retry-after": "42"})

    with pytest.raises(LimiteDeUso) as capturado:
        GroqClient(api_key="k", abrir=abrir_falso).transcribe(audio_falso(tmp_path))
    assert capturado.value.esperar == 42.0


def test_413_vira_arquivo_grande(tmp_path):
    def abrir_falso(*_, **__):
        raise erro_http(413)

    with pytest.raises(ArquivoGrandeDemais):
        GroqClient(api_key="k", abrir=abrir_falso).transcribe(audio_falso(tmp_path))


def test_sem_rede_vira_mensagem_clara(tmp_path):
    def abrir_falso(*_, **__):
        raise urllib.error.URLError("sem rota")

    with pytest.raises(SemInternet):
        GroqClient(api_key="k", abrir=abrir_falso).transcribe(audio_falso(tmp_path))


# --- retry-after -------------------------------------------------------------


def test_retry_after_em_segundos():
    assert parse_retry_after("30") == 30.0
    assert parse_retry_after("2.5") == 2.5


def test_retry_after_como_data_http():
    """O cabecalho pode vir como data -- e vem, dependendo do proxy."""
    import datetime as dt
    import email.utils

    futuro = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60)
    esperar = parse_retry_after(email.utils.format_datetime(futuro))
    assert 50 <= esperar <= 70


def test_retry_after_ausente_ou_invalido_usa_padrao():
    assert parse_retry_after(None) == 30.0
    assert parse_retry_after("depois") == 30.0


# --- verificacao de chave ----------------------------------------------------


def test_check_key_aceita_200():
    assert GroqClient(api_key="k", abrir=lambda *a, **k: RespostaFalsa({}, 200)).check_key()


def test_check_key_recusa_401_sem_lancar():
    """Testar a chave nao pode explodir na cara do usuario -- devolve False."""

    def abrir_falso(*_, **__):
        raise erro_http(401)

    assert GroqClient(api_key="ruim", abrir=abrir_falso).check_key() is False
