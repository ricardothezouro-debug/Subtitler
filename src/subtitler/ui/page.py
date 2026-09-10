"""A pagina que o hub embute.

Duas abas: Transcrever e Configuracoes. O `QTabWidget` ja e estilizado pelo tema
do Sidekick, entao nao ha nada de visual a inventar aqui.

A checagem de precondicoes acontece num `QTimer.singleShot(0, ...)`, nunca no
construtor: o padrao proibe trabalho bloqueante em `build_page()`, e procurar o
ffmpeg no disco e exatamente isso.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from subtitler.core.settings import SettingsStore
from subtitler.ui.settings_tab import SettingsTab
from subtitler.ui.transcribe_tab import TranscribeTab


class SubtitlerPage(QWidget):
    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.settings = SettingsStore()

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 22, 0)
        raiz.setSpacing(14)

        titulo = QLabel("Subtitler")
        titulo.setObjectName("PageTitle")
        raiz.addWidget(titulo)

        subtitulo = QLabel(
            "Transcreve vídeo ou áudio e gera as legendas com os tempos certos."
        )
        subtitulo.setObjectName("Muted")
        raiz.addWidget(subtitulo)

        self.abas = QTabWidget()
        self.aba_transcrever = TranscribeTab(self.settings)
        self.aba_config = SettingsTab(self.settings)

        self.abas.addTab(self._rolavel(self.aba_transcrever), "Transcrever")
        self.abas.addTab(self._rolavel(self.aba_config), "Configurações")
        raiz.addWidget(self.abas, 1)

        # Uma aba avisa a outra: mudou a chave ou o ffmpeg, o botao reavalia.
        self.aba_config.chave_mudou.connect(self.aba_transcrever.checar_precondicoes)
        self.aba_config.ferramentas_mudaram.connect(self.aba_transcrever.checar_precondicoes)
        self.aba_transcrever.pedir_configuracoes.connect(
            lambda: self.abas.setCurrentIndex(1)
        )

        QTimer.singleShot(0, self.aba_transcrever.checar_precondicoes)

    @staticmethod
    def _rolavel(conteudo: QWidget) -> QWidget:
        area = QScrollArea()
        area.setObjectName("PageScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        moldura = QWidget()
        caixa = QVBoxLayout(moldura)
        caixa.setContentsMargins(4, 8, 12, 8)
        caixa.addWidget(conteudo)
        area.setWidget(moldura)
        return area

    def encerrar(self) -> None:
        """Para as threads antes de o app sair.

        Destruir uma QThread ainda viva aborta o processo -- ja custou uma
        versao no Streamer Sidekick.
        """
        self.aba_transcrever.encerrar()
        self.aba_config.encerrar()

    def closeEvent(self, evento):  # noqa: N802
        self.encerrar()
        super().closeEvent(evento)
