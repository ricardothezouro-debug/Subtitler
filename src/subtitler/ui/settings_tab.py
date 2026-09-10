"""Aba de Configuracoes: a chave da API e o ffmpeg.

Sao as duas coisas que precisam estar resolvidas antes de transcrever, entao
elas moram juntas e a aba Transcrever aponta para ca quando falta alguma.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from subtitler.core import ffmpeg_locator
from subtitler.core.ffmpeg_sources import plan_for
from subtitler.core.settings import MAX_PROMPT, SettingsStore, mascarar
from subtitler.ui.components import NeonPanel, NeonProgressBar
from subtitler.ui.help_dialog import ApiKeyHelpDialog
from subtitler.ui.workers import FfmpegInstallWorker, KeyCheckWorker


class SettingsTab(QWidget):
    ferramentas_mudaram = Signal()
    chave_mudou = Signal()

    def __init__(self, settings: SettingsStore, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._worker_ffmpeg: Optional[FfmpegInstallWorker] = None
        self._worker_chave: Optional[KeyCheckWorker] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(self._painel_chave())
        layout.addWidget(self._painel_ffmpeg())
        layout.addWidget(self._painel_termos())
        layout.addStretch(1)

        self.atualizar_ffmpeg()

    # ---------------------------------------------------------------- chave
    def _painel_chave(self) -> QWidget:
        painel = NeonPanel(accent="#FF4FD8")
        caixa = QVBoxLayout(painel)
        caixa.setContentsMargins(18, 16, 18, 16)
        caixa.setSpacing(10)

        cabecalho = QHBoxLayout()
        titulo = QLabel("Chave da API Groq")
        titulo.setObjectName("SectionTitle")
        cabecalho.addWidget(titulo)
        ajuda = QToolButton()
        ajuda.setText("?")
        ajuda.setToolTip("Como obter uma chave")
        ajuda.clicked.connect(lambda: ApiKeyHelpDialog(self).exec())
        cabecalho.addWidget(ajuda)
        cabecalho.addStretch(1)
        caixa.addLayout(cabecalho)

        explicacao = QLabel(
            "A transcrição acontece na nuvem. O plano gratuito da Groq dá cerca "
            "de 8 horas de áudio por dia e não pede cartão."
        )
        explicacao.setObjectName("Muted")
        explicacao.setWordWrap(True)
        caixa.addWidget(explicacao)

        linha = QHBoxLayout()
        self.campo_chave = QLineEdit()
        self.campo_chave.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_chave.setPlaceholderText("Cole aqui a sua chave (gsk_…)")
        if self.settings.api_key:
            self.campo_chave.setText(self.settings.api_key)
        linha.addWidget(self.campo_chave, 1)

        olho = QToolButton()
        olho.setText("👁")
        olho.setCheckable(True)
        olho.setToolTip("Mostrar a chave")
        olho.toggled.connect(
            lambda visivel: self.campo_chave.setEchoMode(
                QLineEdit.EchoMode.Normal if visivel else QLineEdit.EchoMode.Password
            )
        )
        linha.addWidget(olho)
        caixa.addLayout(linha)

        acoes = QHBoxLayout()
        salvar = QPushButton("Salvar")
        salvar.setObjectName("PrimaryButton")
        salvar.clicked.connect(self._salvar_chave)
        acoes.addWidget(salvar)
        testar = QPushButton("Testar chave")
        testar.clicked.connect(self._testar_chave)
        acoes.addWidget(testar)
        acoes.addStretch(1)
        caixa.addLayout(acoes)

        self.status_chave = QLabel(
            f"Chave salva: {mascarar(self.settings.api_key)}"
            if self.settings.api_key
            else "Nenhuma chave salva ainda."
        )
        self.status_chave.setObjectName("Muted")
        caixa.addWidget(self.status_chave)
        return painel

    def _salvar_chave(self) -> None:
        chave = self.campo_chave.text().strip()
        self.settings.set("api_key", chave)
        # Nunca mostrar a chave inteira depois de salva, nem em log.
        self.status_chave.setText(
            f"Chave salva: {mascarar(chave)}" if chave else "Nenhuma chave salva ainda."
        )
        self.chave_mudou.emit()

    def _testar_chave(self) -> None:
        chave = self.campo_chave.text().strip()
        if not chave:
            self.status_chave.setText("Cole uma chave antes de testar.")
            return
        self.status_chave.setText("Testando…")
        worker = KeyCheckWorker(chave)
        worker.resultado.connect(self._resultado_do_teste)
        self._worker_chave = worker  # sem esta referencia o GC leva a thread
        worker.start()

    def _resultado_do_teste(self, valida: bool, detalhe: str) -> None:
        self.status_chave.setText(
            "Chave válida." if valida else f"Chave inválida. {detalhe}".strip()
        )

    # --------------------------------------------------------------- ffmpeg
    def _painel_ffmpeg(self) -> QWidget:
        painel = NeonPanel(accent="#37F2FF")
        caixa = QVBoxLayout(painel)
        caixa.setContentsMargins(18, 16, 18, 16)
        caixa.setSpacing(10)

        titulo = QLabel("ffmpeg")
        titulo.setObjectName("SectionTitle")
        caixa.addWidget(titulo)

        self.status_ffmpeg = QLabel()
        self.status_ffmpeg.setObjectName("Muted")
        self.status_ffmpeg.setWordWrap(True)
        caixa.addWidget(self.status_ffmpeg)

        self.barra_ffmpeg = NeonProgressBar()
        self.barra_ffmpeg.setVisible(False)
        caixa.addWidget(self.barra_ffmpeg)

        acoes = QHBoxLayout()
        self.botao_ffmpeg = QPushButton("Baixar e instalar")
        self.botao_ffmpeg.clicked.connect(self._instalar_ffmpeg)
        acoes.addWidget(self.botao_ffmpeg)
        acoes.addStretch(1)
        caixa.addLayout(acoes)
        return painel

    def atualizar_ffmpeg(self) -> None:
        ferramentas = ffmpeg_locator.resolve(self.settings.get("ffmpeg_path", ""))
        if ferramentas.pronto:
            versao = ffmpeg_locator.versao(ferramentas.ffmpeg)
            # Caminho montado em runtime: nunca um caminho fixo no texto.
            self.status_ffmpeg.setText(
                f"Instalado (versão {versao})\n{ferramentas.ffmpeg}"
            )
            self.botao_ffmpeg.setText("Reinstalar")
        else:
            plano = plan_for()
            self.status_ffmpeg.setText(
                "Não encontrado. O Subtitler usa o ffmpeg para ler o áudio do "
                f"seu arquivo — é um download único de cerca de {plano.total_mb} MB."
            )
            self.botao_ffmpeg.setText("Baixar e instalar")
        self.ferramentas_mudaram.emit()

    def _instalar_ffmpeg(self) -> None:
        self.botao_ffmpeg.setEnabled(False)
        self.barra_ffmpeg.setVisible(True)
        self.barra_ffmpeg.setValue(0)
        worker = FfmpegInstallWorker()
        worker.progresso.connect(self._progresso_ffmpeg)
        worker.concluido.connect(self._ffmpeg_pronto)
        worker.falhou.connect(self._ffmpeg_falhou)
        self._worker_ffmpeg = worker
        worker.start()

    def _progresso_ffmpeg(self, pct: int, mensagem: str) -> None:
        self.barra_ffmpeg.setValue(pct)  # 0..100
        self.status_ffmpeg.setText(mensagem)

    def _ffmpeg_pronto(self) -> None:
        self.barra_ffmpeg.setVisible(False)
        self.botao_ffmpeg.setEnabled(True)
        self.atualizar_ffmpeg()

    def _ffmpeg_falhou(self, titulo: str, detalhe: str, _acao: str) -> None:
        self.barra_ffmpeg.setVisible(False)
        self.botao_ffmpeg.setEnabled(True)
        self.status_ffmpeg.setText(f"{titulo}. {detalhe}")

    # ---------------------------------------------------------------- termos
    def _painel_termos(self) -> QWidget:
        painel = NeonPanel(accent="#B9FF43")
        caixa = QVBoxLayout(painel)
        caixa.setContentsMargins(18, 16, 18, 16)
        caixa.setSpacing(10)

        titulo = QLabel("Termos e nomes")
        titulo.setObjectName("SectionTitle")
        caixa.addWidget(titulo)

        explicacao = QLabel(
            "Nomes de jogos, apelidos e siglas que você usa. Isso ajuda a "
            "transcrição a escrevê-los certo — sem isso, nomes próprios saem "
            "como o Whisper achar que soam."
        )
        explicacao.setObjectName("Muted")
        explicacao.setWordWrap(True)
        caixa.addWidget(explicacao)

        self.campo_termos = QPlainTextEdit()
        self.campo_termos.setPlaceholderText("Wo Long, DREDGE, Gamoxkun, VOD, speedrun")
        self.campo_termos.setPlainText(self.settings.prompt)
        self.campo_termos.setMaximumHeight(90)
        self.campo_termos.textChanged.connect(self._termos_mudaram)
        caixa.addWidget(self.campo_termos)

        self.contador_termos = QLabel()
        self.contador_termos.setObjectName("Muted")
        caixa.addWidget(self.contador_termos)
        self._atualizar_contador()
        return painel

    def _atualizar_contador(self) -> None:
        usados = len(self.campo_termos.toPlainText())
        self.contador_termos.setText(f"{usados} de {MAX_PROMPT} caracteres")

    def _termos_mudaram(self) -> None:
        self._atualizar_contador()
        self.settings.set("prompt", self.campo_termos.toPlainText()[:MAX_PROMPT])

    # ------------------------------------------------------------ encerramento
    def encerrar(self) -> None:
        for worker in (self._worker_ffmpeg, self._worker_chave):
            if worker is not None and worker.isRunning():
                worker.encerrar()
