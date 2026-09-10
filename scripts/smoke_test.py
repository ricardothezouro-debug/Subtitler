"""Sobe a pagina inteira sem display e derruba tudo em seguida.

Os testes de unidade nao pegam a classe de bug que mais doi num plugin: erro que
so aparece com o Qt de pe -- objectName inexistente, layout quebrado, thread que
nao morre. Este script exercita o caminho que o hub percorre.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python scripts/smoke_test.py
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from subtitler import __version__, module
from subtitler.core import ffmpeg_locator
from subtitler.core.paths import data_dir


def main() -> int:
    app = QApplication(sys.argv)

    print(f"versao      : {__version__}")
    print(f"plataforma  : {sys.platform}")
    print(f"dados       : {data_dir()}")

    info = module.module_info()
    print(f"module_info : {info.title} ({info.module_id})")
    print(f"help_text   : {len(module.help_text())} caracteres")

    pagina = module.build_page()
    print(f"build_page  : {type(pagina).__name__}")

    # Alternar as abas e onde estouraria um layout quebrado.
    for indice in range(pagina.abas.count()):
        pagina.abas.setCurrentIndex(indice)
        app.processEvents()
        print(f"  aba ok    : {pagina.abas.tabText(indice)}")

    pagina.aba_transcrever.checar_precondicoes()
    app.processEvents()

    ferramentas = ffmpeg_locator.resolve()
    print(f"ffmpeg      : {'encontrado' if ferramentas.pronto else 'ausente (normal no CI)'}")

    def encerrar() -> None:
        pagina.encerrar()
        pagina.close()
        print("smoke test OK")
        sys.stdout.flush()
        # Sai como o Sidekick sai: destruir uma QThread viva aborta o processo.
        os._exit(0)

    QTimer.singleShot(1500, encerrar)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
