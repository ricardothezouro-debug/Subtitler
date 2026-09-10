"""Cliente da API de transcricao da Groq, so com a biblioteca padrao.

Nao da para usar `requests` aqui: o Streamer Sidekick empacotado nao tem
bibliotecas de terceiros. Entao o corpo `multipart/form-data` e montado a mao.

Duas decisoes que valem explicacao:

* o corpo vai para um **arquivo temporario**, nao para a memoria. Um pedaco de
  25 MB concatenado em `bytes` vira pico de 50 MB ou mais -- num app que ja
  carrega o Qt inteiro, isso aparece;
* o campo `timestamp_granularities[]` aparece **duas vezes** (word e segment).
  Isso e valido em multipart e e justamente o que a montagem manual permite
  fazer sem ginastica.
"""
from __future__ import annotations

import email.utils
import json
import mimetypes
import os
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from subtitler.core.errors import ChaveRecusada, SemInternet, SubtitlerError
from subtitler.core.netcompat import urlopen

URL_TRANSCRICAO = "https://api.groq.com/openai/v1/audio/transcriptions"
URL_MODELOS = "https://api.groq.com/openai/v1/models"

MODELO_PADRAO = "whisper-large-v3"
MODELOS = ("whisper-large-v3", "whisper-large-v3-turbo")

#: 25 MB no plano gratuito. Ficamos abaixo para ter folga.
LIMITE_BYTES = 24 * 1024 * 1024

Progresso = Callable[[int, int], None]
Cancelar = Callable[[], bool]


class ArquivoGrandeDemais(SubtitlerError):
    def __init__(self) -> None:
        from subtitler.core.errors import Acao

        super().__init__(
            "Pedaco de audio grande demais",
            "O plano gratuito aceita ate 25 MB por requisicao.",
            Acao.TENTAR_DE_NOVO,
        )


class LimiteDeUso(SubtitlerError):
    """429. Carrega quanto esperar, para a interface mostrar contagem."""

    def __init__(self, esperar: float) -> None:
        from subtitler.core.errors import Acao

        self.esperar = esperar
        super().__init__(
            "Limite do plano gratuito",
            f"Aguardando {int(esperar)}s para continuar.",
            Acao.TENTAR_DE_NOVO,
        )


def parse_retry_after(valor: Optional[str], padrao: float = 30.0) -> float:
    """O cabecalho `retry-after` vem em segundos OU como data HTTP."""
    if not valor:
        return padrao
    texto = str(valor).strip()
    try:
        return max(0.0, float(texto))
    except ValueError:
        pass
    try:
        quando = email.utils.parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        return padrao
    if quando is None:
        return padrao
    import datetime as _dt

    agora = _dt.datetime.now(_dt.timezone.utc)
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=_dt.timezone.utc)
    return max(0.0, (quando - agora).total_seconds())


class _LeitorComProgresso:
    """Envolve o arquivo do corpo para reportar upload e permitir cancelar."""

    def __init__(self, caminho: Path, total: int, progresso, cancelar) -> None:
        self._arquivo = caminho.open("rb")
        self._total = total
        self._lidos = 0
        self._progresso = progresso
        self._cancelar = cancelar

    def read(self, tamanho: int = -1) -> bytes:
        if self._cancelar and self._cancelar():
            raise SubtitlerError("Cancelado")
        bloco = self._arquivo.read(tamanho)
        self._lidos += len(bloco)
        if self._progresso:
            self._progresso(self._lidos, self._total)
        return bloco

    def close(self) -> None:
        try:
            self._arquivo.close()
        except OSError:
            pass


@dataclass
class GroqClient:
    api_key: str
    model: str = MODELO_PADRAO
    #: injetavel nos testes, para nenhum teste tocar a rede
    abrir: Callable[..., Any] = urlopen

    # --- montagem do corpo -------------------------------------------------
    def _montar_corpo(self, audio: Path, campos: list[tuple[str, str]]) -> tuple[Path, str, int]:
        """Escreve o multipart num arquivo temporario. Devolve (caminho, boundary, tamanho)."""
        boundary = f"----subtitler{uuid.uuid4().hex}"
        descritor, nome = tempfile.mkstemp(prefix="subtitler_upload_", suffix=".bin")
        os.close(descritor)
        corpo = Path(nome)

        tipo = mimetypes.guess_type(audio.name)[0] or "application/octet-stream"
        with corpo.open("wb") as saida:
            for chave, valor in campos:
                saida.write(f"--{boundary}\r\n".encode())
                saida.write(
                    f'Content-Disposition: form-data; name="{chave}"\r\n\r\n'.encode()
                )
                saida.write(f"{valor}\r\n".encode("utf-8"))

            saida.write(f"--{boundary}\r\n".encode())
            saida.write(
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{audio.name}"\r\n'.encode("utf-8")
            )
            saida.write(f"Content-Type: {tipo}\r\n\r\n".encode())
            with audio.open("rb") as entrada:
                while True:
                    bloco = entrada.read(1024 * 256)
                    if not bloco:
                        break
                    saida.write(bloco)
            saida.write(b"\r\n")
            saida.write(f"--{boundary}--\r\n".encode())

        return corpo, boundary, corpo.stat().st_size

    def _campos(self, idioma: str, prompt: str) -> list[tuple[str, str]]:
        campos = [
            ("model", self.model),
            ("response_format", "verbose_json"),
            ("temperature", "0"),
            # Os dois: precisamos das palavras (timing preciso) e dos segmentos
            # (indicadores de confianca, que filtram alucinacao).
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
        ]
        if idioma and idioma != "auto":
            campos.append(("language", idioma))
        if prompt:
            campos.append(("prompt", prompt[:800]))
        return campos

    # --- chamadas ----------------------------------------------------------
    def transcribe(
        self,
        audio: Path,
        idioma: str = "auto",
        prompt: str = "",
        progresso: Optional[Progresso] = None,
        cancelar: Optional[Cancelar] = None,
        timeout: float = 600.0,
    ) -> dict:
        """Envia um pedaco de audio e devolve o `verbose_json` cru."""
        audio = Path(audio)
        if audio.stat().st_size > LIMITE_BYTES:
            raise ArquivoGrandeDemais()

        corpo, boundary, tamanho = self._montar_corpo(audio, self._campos(idioma, prompt))
        leitor = _LeitorComProgresso(corpo, tamanho, progresso, cancelar)
        requisicao = urllib.request.Request(
            URL_TRANSCRICAO,
            data=leitor,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(tamanho),
                "User-Agent": "Subtitler",
            },
            method="POST",
        )

        try:
            with self.abrir(requisicao, timeout=timeout) as resposta:
                return json.loads(resposta.read().decode("utf-8"))
        except urllib.error.HTTPError as erro:
            raise self._traduzir(erro) from erro
        except urllib.error.URLError as erro:
            raise SemInternet() from erro
        finally:
            leitor.close()
            try:
                corpo.unlink(missing_ok=True)
            except OSError:
                pass

    def check_key(self, timeout: float = 20.0) -> bool:
        """Confere a chave sem gastar cota de audio."""
        requisicao = urllib.request.Request(
            URL_MODELOS,
            headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": "Subtitler"},
        )
        try:
            with self.abrir(requisicao, timeout=timeout) as resposta:
                return 200 <= getattr(resposta, "status", 200) < 300
        except urllib.error.HTTPError as erro:
            if erro.code in (401, 403):
                return False
            raise self._traduzir(erro) from erro
        except urllib.error.URLError as erro:
            raise SemInternet() from erro

    @staticmethod
    def _traduzir(erro: urllib.error.HTTPError) -> SubtitlerError:
        if erro.code in (401, 403):
            return ChaveRecusada()
        if erro.code == 429:
            cabecalho = None
            try:
                cabecalho = erro.headers.get("retry-after")
            except Exception:
                pass
            return LimiteDeUso(parse_retry_after(cabecalho))
        if erro.code == 413:
            return ArquivoGrandeDemais()
        detalhe = ""
        try:
            detalhe = (erro.read() or b"")[:300].decode("utf-8", "replace")
        except Exception:
            pass
        from subtitler.core.errors import Acao

        return SubtitlerError(
            f"A Groq respondeu {erro.code}", detalhe, Acao.TENTAR_DE_NOVO
        )


def esperar_com_cancelamento(segundos: float, cancelar: Optional[Cancelar], aviso=None) -> None:
    """Espera o `retry-after` sem travar o cancelamento do usuario."""
    fim = time.monotonic() + max(0.0, segundos)
    while True:
        restante = fim - time.monotonic()
        if restante <= 0:
            return
        if cancelar and cancelar():
            raise SubtitlerError("Cancelado")
        if aviso:
            aviso(int(restante))
        time.sleep(min(0.25, restante))
