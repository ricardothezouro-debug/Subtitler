"""De onde baixar o ffmpeg, por plataforma.

Escolhemos o `eugeneware/ffmpeg-static` por tres motivos praticos:

* **binario unico por plataforma**, comprimido com gzip -- que a stdlib
  descompacta. Alternativas vem em `.zip` com DLLs soltas ou em `.7z`, que
  exigiria biblioteca de terceiro (proibido aqui);
* **18 a 28 MB** por binario, contra 111 MB dos builds monoliticos;
* fica em **releases do GitHub**, com URL previsivel e estavel. Outras fontes
  que testei responderam 403 e 404 intermitentes.

O ffprobe e opcional: a duracao tambem sai do stderr do proprio ffmpeg. Baixamos
os dois quando da, mas o app funciona so com o ffmpeg.
"""
from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from typing import Optional

_BASE = "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1"

# Fallback do Windows, caso a fonte primaria saia do ar. Vem em zip com a pasta
# bin/ inteira -- mais pesado, mas tambem so precisa da stdlib.
_FALLBACK_WIN = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip"
)


@dataclass(frozen=True)
class Binario:
    """Um executavel a baixar."""

    nome: str  # "ffmpeg" ou "ffprobe"
    url: str
    tamanho_mb: int
    #: gzip de arquivo unico, ou zip com varios membros
    formato: str = "gz"
    #: para zip: sufixo do membro a extrair
    membro: Optional[str] = None


@dataclass(frozen=True)
class PlanoDeDownload:
    chave: str
    binarios: tuple[Binario, ...]
    #: mostrado ao usuario ANTES de comecar
    total_mb: int

    @property
    def obrigatorios(self) -> tuple[Binario, ...]:
        return tuple(b for b in self.binarios if b.nome == "ffmpeg")


def _sufixo_executavel() -> str:
    return ".exe" if sys.platform == "win32" else ""


def chave_da_plataforma(
    plataforma: Optional[str] = None, arquitetura: Optional[str] = None
) -> str:
    plataforma = plataforma or sys.platform
    arquitetura = (arquitetura or platform.machine()).lower()
    if plataforma == "win32":
        return "win32-x64"
    if plataforma == "darwin":
        return "darwin-arm64" if arquitetura in ("arm64", "aarch64") else "darwin-x64"
    return "linux-arm64" if arquitetura in ("arm64", "aarch64") else "linux-x64"


# Tamanho aproximado de cada binario, por plataforma (MB).
_TAMANHOS = {
    "darwin-arm64": 18,
    "darwin-x64": 24,
    "win32-x64": 28,
    "linux-x64": 27,
    "linux-arm64": 24,
}


def plan_for(
    plataforma: Optional[str] = None, arquitetura: Optional[str] = None
) -> PlanoDeDownload:
    """O que baixar nesta maquina."""
    chave = chave_da_plataforma(plataforma, arquitetura)
    tamanho = _TAMANHOS.get(chave, 28)
    binarios = tuple(
        Binario(nome=nome, url=f"{_BASE}/{nome}-{chave}.gz", tamanho_mb=tamanho)
        for nome in ("ffmpeg", "ffprobe")
    )
    return PlanoDeDownload(chave=chave, binarios=binarios, total_mb=tamanho * 2)


def fallback_for(plataforma: Optional[str] = None) -> Optional[Binario]:
    """Segunda fonte, quando a primaria falha. So existe para Windows."""
    if (plataforma or sys.platform) != "win32":
        return None
    return Binario(
        nome="ffmpeg",
        url=_FALLBACK_WIN,
        tamanho_mb=76,
        formato="zip",
        membro="bin/ffmpeg.exe",
    )


def nome_do_executavel(nome: str) -> str:
    return f"{nome}{_sufixo_executavel()}"
