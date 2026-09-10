"""Trabalho demorado fora da thread da interface.

O `core/` reporta por callbacks e nao conhece Qt; e aqui que callback vira
`Signal`. Dois cuidados que ja custaram caro no Streamer Sidekick:

* **guardar a referencia do worker.** Sem isso o coletor de lixo leva a QThread
  e o app quebra.
* **encerrar antes de sair.** Destruir uma QThread ainda viva aborta o processo
  -- por isso `cancel()` seguido de `wait()` no fechamento.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal


class _Cancelavel(QThread):
    """Base com bandeira de cancelamento cooperativo."""

    def __init__(self) -> None:
        super().__init__()
        self._parar = threading.Event()

    def cancel(self) -> None:
        self._parar.set()

    def cancelado(self) -> bool:
        return self._parar.is_set()

    def encerrar(self, timeout_ms: int = 5000) -> None:
        self.cancel()
        self.wait(timeout_ms)


class TranscribeWorker(_Cancelavel):
    """Roda o pipeline inteiro."""

    progresso = Signal(int, str)          # 0..100, mensagem
    esperando = Signal(int)               # segundos restantes no limite gratuito
    concluido = Signal(object)            # pipeline.Resultado
    falhou = Signal(str, str, str)        # titulo, detalhe, acao

    def __init__(self, job, ferramentas, cliente) -> None:
        super().__init__()
        self._job = job
        self._ferramentas = ferramentas
        self._cliente = cliente

    def run(self) -> None:  # pragma: no cover - precisa de thread real
        from subtitler.core import pipeline
        from subtitler.core.errors import Acao, SubtitlerError

        try:
            resultado = pipeline.run_job(
                self._job,
                self._ferramentas,
                self._cliente,
                progresso=lambda pct, msg: self.progresso.emit(pct, msg),
                cancelar=self.cancelado,
                aviso_de_espera=lambda s: self.esperando.emit(s),
            )
        except SubtitlerError as erro:
            self.falhou.emit(erro.titulo, erro.detalhe, erro.acao)
        except Exception as erro:  # nunca deixar excecao subir da thread
            self.falhou.emit("Algo deu errado", str(erro), Acao.TENTAR_DE_NOVO)
        else:
            self.concluido.emit(resultado)


class FfmpegInstallWorker(_Cancelavel):
    """Baixa o ffmpeg sem travar a interface."""

    progresso = Signal(int, str)
    concluido = Signal()
    falhou = Signal(str, str, str)

    def run(self) -> None:  # pragma: no cover - precisa de rede
        from subtitler.core import ffmpeg_installer
        from subtitler.core.errors import Acao, SubtitlerError

        def relatar(baixados: int, total: int) -> None:
            pct = int(baixados / total * 100) if total else 0
            mb = baixados / 1024 / 1024
            total_mb = total / 1024 / 1024 if total else 0
            self.progresso.emit(
                pct, f"Baixando… {mb:.0f} MB de {total_mb:.0f} MB"
            )

        try:
            ffmpeg_installer.install(progresso=relatar, cancelar=self.cancelado)
        except SubtitlerError as erro:
            self.falhou.emit(erro.titulo, erro.detalhe, erro.acao)
        except Exception as erro:
            self.falhou.emit("Não foi possível baixar", str(erro), Acao.TENTAR_DE_NOVO)
        else:
            self.concluido.emit()


class KeyCheckWorker(_Cancelavel):
    """Testa a chave sem gastar cota de áudio."""

    resultado = Signal(bool, str)

    def __init__(self, chave: str) -> None:
        super().__init__()
        self._chave = chave

    def run(self) -> None:  # pragma: no cover - precisa de rede
        from subtitler.core.groq_client import GroqClient

        try:
            valida = GroqClient(api_key=self._chave).check_key()
        except Exception as erro:
            self.resultado.emit(False, str(erro))
        else:
            self.resultado.emit(valida, "" if valida else "A Groq recusou esta chave.")


class ProbeWorker(_Cancelavel):
    """Le duracao e streams do arquivo escolhido -- rapido, mas nao instantaneo."""

    concluido = Signal(object)
    falhou = Signal(str)

    def __init__(self, arquivo: Path, ferramentas) -> None:
        super().__init__()
        self._arquivo = arquivo
        self._ferramentas = ferramentas

    def run(self) -> None:  # pragma: no cover - precisa de ffmpeg
        from subtitler.core import media

        try:
            info = media.probe(self._ferramentas, self._arquivo)
        except Exception as erro:
            self.falhou.emit(str(erro))
        else:
            self.concluido.emit(info)
