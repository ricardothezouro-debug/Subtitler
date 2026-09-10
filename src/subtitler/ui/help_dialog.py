"""O "?" ao lado do campo da chave.

Pedir uma chave de API para quem so quer legendar um video e uma barreira real.
Este dialogo existe para tornar o caminho obvio: os passos exatos, o aviso de
que a chave so aparece uma vez, e um botao que ja abre a pagina certa.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

CONSOLE = "https://console.groq.com/keys"


class ApiKeyHelpDialog(QDialog):
    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Como obter uma chave da Groq")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        titulo = QLabel("Como obter uma chave da Groq")
        titulo.setObjectName("SectionTitle")
        layout.addWidget(titulo)

        passos = QLabel(
            "1.  Abra <b>console.groq.com</b> e entre com Google ou GitHub.<br>"
            "2.  No menu lateral, clique em <b>API Keys</b>.<br>"
            "3.  Clique em <b>Create API Key</b> e dê um nome qualquer.<br>"
            "4.  Copie a chave e cole aqui no Subtitler."
        )
        passos.setTextFormat(Qt.TextFormat.RichText)
        passos.setWordWrap(True)
        layout.addWidget(passos)

        aviso = QLabel(
            "A chave aparece <b>uma única vez</b> — se fechar a página sem copiar, "
            "é só criar outra.<br><br>"
            "O plano gratuito é suficiente para uso pessoal: dá cerca de "
            "<b>8 horas de áudio por dia</b>, sem cadastrar cartão."
        )
        aviso.setObjectName("Muted")
        aviso.setTextFormat(Qt.TextFormat.RichText)
        aviso.setWordWrap(True)
        layout.addWidget(aviso)

        privacidade = QLabel(
            "Sua chave fica salva apenas neste computador, na pasta de dados do "
            "Streamer Sidekick. Ela não é enviada para nenhum lugar além da própria Groq."
        )
        privacidade.setObjectName("Muted")
        privacidade.setWordWrap(True)
        layout.addWidget(privacidade)

        abrir = QPushButton("Abrir console.groq.com")
        abrir.setObjectName("PrimaryButton")
        abrir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(CONSOLE)))
        layout.addWidget(abrir)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botoes.rejected.connect(self.reject)
        botoes.accepted.connect(self.accept)
        layout.addWidget(botoes)
