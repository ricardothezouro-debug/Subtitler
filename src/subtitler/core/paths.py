"""Onde o Subtitler guarda dados, na convencao de cada sistema.

Rodando como plugin (o caso normal) perguntamos ao proprio Streamer Sidekick, que
ja sabe o caminho certo de cada SO. Fora dele reproduzimos a mesma regra.

O que NAO pode acontecer aqui e o erro que o PLUGIN_STANDARD chama de armadilha
numero 1: `os.getenv("APPDATA")` cru. Essa variavel so existe no Windows -- no
macOS os dados iriam parar numa pasta oculta na home, que nao e onde o Sidekick
guarda nada.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

APP_NAME = "StreamerSidekick"
PLUGIN_ID = "subtitler"


def _fallback_root() -> Path:
    """A mesma regra do Sidekick, para quando ele nao esta importavel."""
    if sys.platform == "win32":
        base = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        xdg = os.getenv("XDG_CONFIG_HOME")
        return (Path(xdg) if xdg else Path.home() / ".config") / APP_NAME
    return Path.home() / ".streamer_sidekick"


@lru_cache(maxsize=1)
def data_dir() -> Path:
    """Pasta de dados do plugin. Fica fora da pasta do plugin, entao sobrevive
    a atualizacoes -- que e o que a regra 4 do padrao exige."""
    try:
        from streamer_sidekick.core.paths import user_data_dir  # type: ignore

        caminho = Path(user_data_dir(PLUGIN_ID))
    except Exception:
        caminho = _fallback_root() / PLUGIN_ID
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def _subpasta(nome: str) -> Path:
    caminho = data_dir() / nome
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def bin_dir() -> Path:
    """Onde o ffmpeg baixado por nos fica."""
    return _subpasta("bin")


def jobs_dir() -> Path:
    """Uma pasta por transcricao, com o audio normalizado e os pedacos ja
    transcritos. E o que permite retomar um trabalho interrompido."""
    return _subpasta("jobs")


def settings_path() -> Path:
    return data_dir() / "settings.json"
