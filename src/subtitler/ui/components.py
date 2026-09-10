"""Componentes visuais.

Rodando dentro do hub, reaproveitamos os do proprio Streamer Sidekick -- assim a
pagina fica identica ao resto do app de graca. Fora dele, uma copia local
suficiente para desenvolver.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QWidget

ACENTO = "#FF4FD8"
CIANO = "#37F2FF"
BORDA = "#273140"

try:  # pragma: no cover - so dentro do Sidekick
    from streamer_sidekick.ui.components import NeonPanel, NeonProgressBar  # type: ignore
except Exception:  # pragma: no cover - copia local para uso standalone

    class NeonPanel(QFrame):  # type: ignore[no-redef]
        """Painel de canto cortado com borda em gradiente."""

        def __init__(self, parent: QWidget = None, accent: str = CIANO, grid: bool = False):
            super().__init__(parent)
            self._accent = accent
            self.setObjectName("NeonPanel")
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        def paintEvent(self, evento):  # noqa: N802
            pintor = QPainter(self)
            pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
            retangulo = self.rect().adjusted(1, 1, -1, -1)
            corte = 14
            caminho = QPainterPath()
            caminho.moveTo(retangulo.left() + corte, retangulo.top())
            caminho.lineTo(retangulo.right(), retangulo.top())
            caminho.lineTo(retangulo.right(), retangulo.bottom() - corte)
            caminho.lineTo(retangulo.right() - corte, retangulo.bottom())
            caminho.lineTo(retangulo.left(), retangulo.bottom())
            caminho.lineTo(retangulo.left(), retangulo.top() + corte)
            caminho.closeSubpath()

            pintor.fillPath(caminho, QColor("#141826"))
            gradiente = QLinearGradient(retangulo.topLeft(), retangulo.bottomRight())
            gradiente.setColorAt(0.0, QColor(self._accent))
            gradiente.setColorAt(1.0, QColor(BORDA))
            pintor.setPen(QPen(gradiente, 1.4))
            pintor.drawPath(caminho)

    class NeonProgressBar(QWidget):  # type: ignore[no-redef]
        """Barra de progresso. `setValue` recebe 0..100, como a do Sidekick."""

        def __init__(self, parent: QWidget = None):
            super().__init__(parent)
            self._valor = 0.0
            self._indeterminada = False
            self.setMinimumHeight(8)

        def setValue(self, valor: float) -> None:  # noqa: N802
            self._valor = max(0.0, min(1.0, valor / 100.0))
            self._indeterminada = False
            self.update()

        def setIndeterminate(self, ligado: bool = True) -> None:  # noqa: N802
            self._indeterminada = ligado
            self.update()

        def paintEvent(self, evento):  # noqa: N802
            pintor = QPainter(self)
            pintor.fillRect(self.rect(), QColor("#0A0B12"))
            if self._indeterminada:
                pintor.fillRect(self.rect(), QColor(CIANO).darker(250))
                return
            largura = int(self.rect().width() * self._valor)
            if largura > 0:
                pintor.fillRect(0, 0, largura, self.rect().height(), QColor(CIANO))
