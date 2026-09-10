"""Achar o ffmpeg, sem obrigar o usuario a baixar quem ja tem.

A ordem importa. E a busca no PATH nao basta no macOS: um `.app` aberto pelo
Finder herda um PATH minimo, entao `which ffmpeg` falha mesmo com o Homebrew
instalado. Por isso olhamos tambem nas pastas conhecidas dele.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from subtitler.core.ffmpeg_sources import nome_do_executavel
from subtitler.core.paths import bin_dir

# Onde o Homebrew (Apple Silicon e Intel) e o MacPorts instalam.
_PASTAS_CONHECIDAS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
    "/usr/bin",
)


@dataclass(frozen=True)
class Ferramentas:
    """Os binarios encontrados. `ffprobe` e opcional."""

    ffmpeg: Optional[Path] = None
    ffprobe: Optional[Path] = None

    @property
    def pronto(self) -> bool:
        return self.ffmpeg is not None


def popen_kwargs() -> dict:
    """Argumentos de `subprocess` corretos para cada sistema.

    `creationflags` so existe no Windows -- passa-lo no macOS levanta
    `ValueError`. E sem `CREATE_NO_WINDOW` cada chamada do ffmpeg pisca uma
    janela preta de console na cara do usuario.
    """
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def _executa(caminho: Path) -> bool:
    """So confia depois de rodar. Um binario sem permissao de execucao, ou
    baixado para a arquitetura errada, falha exatamente aqui."""
    try:
        resultado = subprocess.run(
            [str(caminho), "-version"],
            capture_output=True,
            timeout=20,
            **popen_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    saida = (resultado.stdout or b"") + (resultado.stderr or b"")
    return resultado.returncode == 0 and b"version" in saida.lower()


def _candidatos(nome: str, caminho_manual: str = "") -> list[Path]:
    executavel = nome_do_executavel(nome)
    candidatos: list[Path] = []

    if caminho_manual:
        candidatos.append(Path(caminho_manual))

    candidatos.append(bin_dir() / executavel)

    do_path = shutil.which(nome)
    if do_path:
        candidatos.append(Path(do_path))

    if sys.platform != "win32":
        candidatos.extend(Path(pasta) / nome for pasta in _PASTAS_CONHECIDAS)

    return candidatos


def encontrar(nome: str, caminho_manual: str = "") -> Optional[Path]:
    for candidato in _candidatos(nome, caminho_manual):
        if candidato.is_file() and _executa(candidato):
            return candidato
    return None


def resolve(caminho_manual_ffmpeg: str = "") -> Ferramentas:
    """Localiza ffmpeg e ffprobe, independentemente: pode existir so um."""
    ffmpeg = encontrar("ffmpeg", caminho_manual_ffmpeg)
    ffprobe = encontrar("ffprobe")
    return Ferramentas(ffmpeg=ffmpeg, ffprobe=ffprobe)


def versao(caminho: Path) -> str:
    """Primeira linha do `-version`, para mostrar na tela."""
    try:
        resultado = subprocess.run(
            [str(caminho), "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            **popen_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return "desconhecida"
    primeira = (resultado.stdout or "").splitlines()[:1]
    if not primeira:
        return "desconhecida"
    partes = primeira[0].split()
    return partes[2] if len(partes) > 2 else primeira[0]
