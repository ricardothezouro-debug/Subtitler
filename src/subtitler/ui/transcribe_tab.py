"""Aba Transcrever: escolher o arquivo, gerar, ver o resultado.

Quatro blocos numerados, na ordem em que a pessoa realmente faz as coisas. O
botao principal so habilita quando chave e ffmpeg estao resolvidos -- e melhor
impedir do que deixar comecar e falhar no meio.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from subtitler.core import ffmpeg_locator
from subtitler.core.errors import Acao
from subtitler.core.groq_client import MODELOS
from subtitler.core.settings import SettingsStore
from subtitler.ui.components import NeonPanel, NeonProgressBar
from subtitler.ui.workers import ProbeWorker, TranscribeWorker

IDIOMAS = [
    ("Português", "pt"),
    ("Detectar automaticamente (menos preciso)", "auto"),
    ("Inglês", "en"),
    ("Espanhol", "es"),
    ("Francês", "fr"),
    ("Alemão", "de"),
    ("Italiano", "it"),
    ("Japonês", "ja"),
]

FILTRO = (
    "Vídeo e áudio (*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.wav *.m4a *.flac *.ogg *.aiff);;"
    "Todos (*)"
)


class TranscribeTab(QWidget):
    pedir_configuracoes = Signal()

    def __init__(self, settings: SettingsStore, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.arquivo: Optional[Path] = None
        self.pasta_saida: Optional[Path] = None
        self._worker: Optional[TranscribeWorker] = None
        self._probe: Optional[ProbeWorker] = None

        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.aviso = QLabel()
        self.aviso.setObjectName("StatusPill")
        self.aviso.setWordWrap(True)
        self.aviso.setVisible(False)
        layout.addWidget(self.aviso)

        layout.addWidget(self._bloco_arquivo())
        layout.addWidget(self._bloco_opcoes())
        layout.addWidget(self._bloco_gerar())
        layout.addWidget(self._bloco_resultado())
        layout.addStretch(1)

    # -------------------------------------------------------------- arquivo
    def _bloco_arquivo(self) -> QWidget:
        painel = NeonPanel(accent="#FF4FD8")
        caixa = QVBoxLayout(painel)
        caixa.setContentsMargins(18, 16, 18, 16)
        caixa.setSpacing(10)

        titulo = QLabel("01  |  Arquivo")
        titulo.setObjectName("Kicker")
        caixa.addWidget(titulo)

        linha = QHBoxLayout()
        escolher = QPushButton("Escolher arquivo…")
        escolher.clicked.connect(self._escolher_arquivo)
        linha.addWidget(escolher)
        linha.addStretch(1)
        caixa.addLayout(linha)

        self.rotulo_arquivo = QLabel("Nenhum arquivo escolhido — ou arraste um para cá.")
        self.rotulo_arquivo.setObjectName("Muted")
        self.rotulo_arquivo.setWordWrap(True)
        caixa.addWidget(self.rotulo_arquivo)
        return painel

    def _escolher_arquivo(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(self, "Escolher vídeo ou áudio", "", FILTRO)
        if caminho:
            self.definir_arquivo(Path(caminho))

    def definir_arquivo(self, caminho: Path) -> None:
        self.arquivo = caminho
        self.pasta_saida = caminho.parent
        self.rotulo_saida.setText(f"Salvar em: {self.pasta_saida}")
        self.rotulo_arquivo.setText(f"{caminho.name} — lendo…")
        self._atualizar_botao()

        ferramentas = ffmpeg_locator.resolve(self.settings.get("ffmpeg_path", ""))
        if not ferramentas.pronto:
            self.rotulo_arquivo.setText(caminho.name)
            return
        worker = ProbeWorker(caminho, ferramentas)
        worker.concluido.connect(self._arquivo_lido)
        worker.falhou.connect(lambda erro: self.rotulo_arquivo.setText(f"{caminho.name} — {erro}"))
        self._probe = worker
        worker.start()

    def _arquivo_lido(self, info) -> None:
        if not self.arquivo:
            return
        minutos, segundos = divmod(int(info.duration), 60)
        tipo = "vídeo" if info.has_video else "áudio"
        tamanho = self.arquivo.stat().st_size / 1024 / 1024
        self.rotulo_arquivo.setText(
            f"{self.arquivo.name}  ·  {tipo}  ·  {minutos}min {segundos}s  ·  {tamanho:.0f} MB"
        )

    # arrastar e soltar em qualquer ponto da aba
    def dragEnterEvent(self, evento):  # noqa: N802
        if evento.mimeData().hasUrls():
            evento.acceptProposedAction()

    def dropEvent(self, evento):  # noqa: N802
        for url in evento.mimeData().urls():
            caminho = Path(url.toLocalFile())
            if caminho.is_file():
                self.definir_arquivo(caminho)
                break

    # -------------------------------------------------------------- opcoes
    def _bloco_opcoes(self) -> QWidget:
        painel = NeonPanel(accent="#37F2FF")
        caixa = QVBoxLayout(painel)
        caixa.setContentsMargins(18, 16, 18, 16)
        caixa.setSpacing(10)

        titulo = QLabel("02  |  Opções")
        titulo.setObjectName("Kicker")
        caixa.addWidget(titulo)

        linha = QHBoxLayout()
        linha.addWidget(QLabel("Idioma"))
        self.combo_idioma = QComboBox()
        for rotulo, codigo in IDIOMAS:
            self.combo_idioma.addItem(rotulo, codigo)
        salvo = self.settings.get("language", "pt")
        indice = self.combo_idioma.findData(salvo)
        self.combo_idioma.setCurrentIndex(max(0, indice))
        self.combo_idioma.currentIndexChanged.connect(
            lambda: self.settings.set("language", self.combo_idioma.currentData())
        )
        linha.addWidget(self.combo_idioma)

        linha.addSpacing(16)
        linha.addWidget(QLabel("Modelo"))
        self.combo_modelo = QComboBox()
        self.combo_modelo.addItem("Mais preciso", MODELOS[0])
        self.combo_modelo.addItem("Mais rápido", MODELOS[1])
        indice = self.combo_modelo.findData(self.settings.get("model", MODELOS[0]))
        self.combo_modelo.setCurrentIndex(max(0, indice))
        self.combo_modelo.currentIndexChanged.connect(
            lambda: self.settings.set("model", self.combo_modelo.currentData())
        )
        linha.addWidget(self.combo_modelo)
        linha.addStretch(1)
        caixa.addLayout(linha)

        formatos = QHBoxLayout()
        formatos.addWidget(QLabel("Gerar"))
        salvos = set(self.settings.get("formats", ["srt"]))
        self.checks = {}
        for nome, rotulo in (("srt", "SRT"), ("vtt", "VTT"), ("txt", "TXT")):
            check = QCheckBox(rotulo)
            check.setChecked(nome in salvos)
            check.toggled.connect(self._formatos_mudaram)
            self.checks[nome] = check
            formatos.addWidget(check)

        # O core sempre soube escrever o TXT com horario na frente de cada
        # paragrafo, mas nao havia controle nenhum para ligar isso -- a opcao
        # ficava presa no valor padrao (desligado).
        formatos.addSpacing(20)
        self.check_tempos = QCheckBox("TXT com horário das falas")
        self.check_tempos.setToolTip(
            "Prefixa cada parágrafo com [hh:mm:ss] no arquivo .txt."
        )
        self.check_tempos.setChecked(bool(self.settings.get("txt_com_tempos", False)))
        self.check_tempos.toggled.connect(
            lambda ligado: self.settings.set("txt_com_tempos", bool(ligado))
        )
        formatos.addWidget(self.check_tempos)
        formatos.addStretch(1)
        caixa.addLayout(formatos)
        self._atualizar_check_tempos()

        # Nome de jogo e apelido sao o que mais sai errado, e a correcao mora
        # noutra aba -- sem um empurrao aqui o usuario nao liga uma coisa na
        # outra e conclui que a transcricao e ruim.
        linha_dica = QHBoxLayout()
        self.dica_termos = QPushButton(
            "Nomes de jogos ou apelidos saindo errado? Cadastre-os em Termos e nomes →"
        )
        self.dica_termos.setObjectName("Muted")
        self.dica_termos.setFlat(True)
        self.dica_termos.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dica_termos.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self.dica_termos.clicked.connect(self.pedir_configuracoes.emit)
        linha_dica.addWidget(self.dica_termos)
        linha_dica.addStretch(1)
        caixa.addLayout(linha_dica)

        saida = QHBoxLayout()
        escolher_pasta = QPushButton("Escolher pasta…")
        escolher_pasta.clicked.connect(self._escolher_pasta)
        saida.addWidget(escolher_pasta)
        self.rotulo_saida = QLabel("Salvar em: a pasta do arquivo escolhido")
        self.rotulo_saida.setObjectName("Muted")
        saida.addWidget(self.rotulo_saida, 1)
        caixa.addLayout(saida)
        return painel

    def _formatos_mudaram(self) -> None:
        escolhidos = [nome for nome, check in self.checks.items() if check.isChecked()]
        self.settings.set("formats", escolhidos)
        self._atualizar_check_tempos()
        self._atualizar_botao()

    def _atualizar_check_tempos(self) -> None:
        """O horario no TXT so existe se o TXT for gerado."""
        ligado = self.checks["txt"].isChecked()
        self.check_tempos.setEnabled(ligado)

    def _escolher_pasta(self) -> None:
        inicial = str(self.pasta_saida or Path.home())
        pasta = QFileDialog.getExistingDirectory(self, "Onde salvar as legendas", inicial)
        if pasta:
            self.pasta_saida = Path(pasta)
            self.rotulo_saida.setText(f"Salvar em: {self.pasta_saida}")

    # -------------------------------------------------------------- gerar
    def _bloco_gerar(self) -> QWidget:
        painel = NeonPanel(accent="#B9FF43")
        caixa = QVBoxLayout(painel)
        caixa.setContentsMargins(18, 16, 18, 16)
        caixa.setSpacing(10)

        titulo = QLabel("03  |  Gerar")
        titulo.setObjectName("Kicker")
        caixa.addWidget(titulo)

        linha = QHBoxLayout()
        self.botao_gerar = QPushButton("Gerar legendas")
        self.botao_gerar.setObjectName("PrimaryButton")
        self.botao_gerar.clicked.connect(self._gerar)
        linha.addWidget(self.botao_gerar)
        self.botao_cancelar = QPushButton("Cancelar")
        self.botao_cancelar.setVisible(False)
        self.botao_cancelar.clicked.connect(self._cancelar)
        linha.addWidget(self.botao_cancelar)
        linha.addStretch(1)
        caixa.addLayout(linha)

        self.barra = NeonProgressBar()
        self.barra.setVisible(False)
        caixa.addWidget(self.barra)

        self.detalhe = QLabel("")
        self.detalhe.setObjectName("Muted")
        self.detalhe.setWordWrap(True)
        caixa.addWidget(self.detalhe)
        return painel

    def _gerar(self) -> None:
        from subtitler.core.groq_client import GroqClient
        from subtitler.core.pipeline import Job

        if not self.arquivo:
            self.detalhe.setText("Escolha um arquivo primeiro.")
            return

        ferramentas = ffmpeg_locator.resolve(self.settings.get("ffmpeg_path", ""))
        job = Job(
            origem=self.arquivo,
            saida=self.pasta_saida or self.arquivo.parent,
            formatos=tuple(n for n, c in self.checks.items() if c.isChecked()) or ("srt",),
            idioma=self.combo_idioma.currentData(),
            prompt=self.settings.prompt,
            modelo=self.combo_modelo.currentData(),
            regras=self.settings.cue_rules(),
            txt_com_tempos=bool(self.settings.get("txt_com_tempos", False)),
        )
        cliente = GroqClient(api_key=self.settings.api_key, model=job.modelo)

        self.botao_gerar.setEnabled(False)
        self.botao_cancelar.setVisible(True)
        self.barra.setVisible(True)
        self.barra.setValue(0)
        self.resultado.setPlainText("")

        worker = TranscribeWorker(job, ferramentas, cliente)
        worker.progresso.connect(self._progresso)
        worker.esperando.connect(
            lambda s: self.detalhe.setText(
                f"Aguardando o limite do plano gratuito liberar… {s}s"
            )
        )
        worker.concluido.connect(self._concluido)
        worker.falhou.connect(self._falhou)
        self._worker = worker  # sem esta referencia o GC leva a thread
        worker.start()

    def _progresso(self, pct: int, mensagem: str) -> None:
        self.barra.setValue(pct)  # 0..100, nao 0..1
        self.detalhe.setText(f"{mensagem}  ({pct}%)")

    def _cancelar(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.detalhe.setText("Cancelando…")

    def _concluido(self, resultado) -> None:
        self._encerrar_execucao()
        self.detalhe.setText(f"Pronto — {len(resultado.arquivos)} arquivo(s) gerado(s).")
        self.lista_arquivos.setText(
            "\n".join(f"• {a.name}" for a in resultado.arquivos)
        )
        self.ultimo_destino = resultado.arquivos[0].parent
        self.botao_abrir.setEnabled(True)

        from subtitler.core.cues import build_cues

        cues = build_cues(resultado.transcricao.words, self.settings.cue_rules())
        previa = []
        for cue in cues[:10]:
            previa.append("\n".join(cue.lines))
        self.resultado.setPlainText("\n\n".join(previa))
        if not resultado.transcricao.word_level:
            self.detalhe.setText(
                self.detalhe.text() + "  O timing é aproximado: a API não devolveu "
                "os tempos por palavra."
            )

    def _falhou(self, titulo: str, detalhe: str, acao: str) -> None:
        self._encerrar_execucao()
        self.detalhe.setText(f"{titulo}. {detalhe}".strip())
        if acao in (Acao.ABRIR_CONFIGURACOES, Acao.INSTALAR_FFMPEG):
            self.pedir_configuracoes.emit()

    def _encerrar_execucao(self) -> None:
        self.botao_gerar.setEnabled(True)
        self.botao_cancelar.setVisible(False)
        self.barra.setVisible(False)

    # ----------------------------------------------------------- resultado
    def _bloco_resultado(self) -> QWidget:
        painel = NeonPanel(accent="#37F2FF")
        caixa = QVBoxLayout(painel)
        caixa.setContentsMargins(18, 16, 18, 16)
        caixa.setSpacing(10)

        titulo = QLabel("04  |  Resultado")
        titulo.setObjectName("Kicker")
        caixa.addWidget(titulo)

        self.lista_arquivos = QLabel("Nada gerado ainda.")
        self.lista_arquivos.setObjectName("Muted")
        caixa.addWidget(self.lista_arquivos)

        self.botao_abrir = QPushButton("Abrir pasta")
        self.botao_abrir.setEnabled(False)
        self.botao_abrir.clicked.connect(self._abrir_pasta)
        caixa.addWidget(self.botao_abrir)

        previa = QLabel("Prévia das primeiras legendas:")
        previa.setObjectName("Muted")
        caixa.addWidget(previa)

        self.resultado = QPlainTextEdit()
        self.resultado.setReadOnly(True)
        self.resultado.setMaximumHeight(160)
        caixa.addWidget(self.resultado)

        self.ultimo_destino: Optional[Path] = None
        return painel

    def _abrir_pasta(self) -> None:
        if self.ultimo_destino is None:
            return
        try:
            from streamer_sidekick.core.platform_utils import open_path  # type: ignore

            open_path(self.ultimo_destino)
            return
        except Exception:
            pass
        # Sem o Sidekick: mesma logica, por plataforma.
        import subprocess
        import sys

        if sys.platform == "win32":
            import os

            os.startfile(str(self.ultimo_destino))  # noqa: S606 - so no Windows
        elif sys.platform == "darwin":
            subprocess.run(["open", str(self.ultimo_destino)], check=False)
        else:
            subprocess.run(["xdg-open", str(self.ultimo_destino)], check=False)

    # ------------------------------------------------------------ estado
    def checar_precondicoes(self) -> None:
        """Chamado por QTimer, nunca no build_page: nada bloqueante na montagem."""
        faltando = []
        if not self.settings.api_key:
            faltando.append("a chave da Groq")
        if not ffmpeg_locator.resolve(self.settings.get("ffmpeg_path", "")).pronto:
            faltando.append("o ffmpeg")

        if faltando:
            self.aviso.setText(
                f"Falta {' e '.join(faltando)} — resolva em Configurações para começar."
            )
            self.aviso.setVisible(True)
        else:
            self.aviso.setVisible(False)
        self.dica_termos.setVisible(not self.settings.prompt.strip())
        self._atualizar_botao()

    def _atualizar_botao(self) -> None:
        pronto = bool(
            self.arquivo
            and self.settings.api_key
            and ffmpeg_locator.resolve(self.settings.get("ffmpeg_path", "")).pronto
        )
        self.botao_gerar.setEnabled(pronto)
        if not pronto and self.arquivo:
            self.botao_gerar.setToolTip("Configure a chave e o ffmpeg primeiro.")
        else:
            self.botao_gerar.setToolTip("")

    def encerrar(self) -> None:
        for worker in (self._worker, self._probe):
            if worker is not None and worker.isRunning():
                worker.encerrar()
