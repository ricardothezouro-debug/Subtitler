"""Conversa com o ffmpeg: sondar, normalizar e fatiar audio.

Dois cuidados que so aparecem em arquivo longo, ou seja, passam em qualquer
teste rapido e travam no video de duas horas do usuario:

* **`-nostdin`** em toda chamada. Sem isso o ffmpeg consome o stdin do
  aplicativo e coisas estranhas acontecem.
* **drenar o stderr continuamente.** O ffmpeg escreve muito ali; se o pipe
  encher e ninguem ler, ele bloqueia para sempre esperando espaco.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from subtitler.core.errors import FfmpegFalhou, SemFaixaDeAudio
from subtitler.core.ffmpeg_locator import Ferramentas, popen_kwargs

#: `progresso(fracao)` com fracao de 0.0 a 1.0
Progresso = Callable[[float], None]
Cancelar = Callable[[], bool]

_DURACAO = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_TEM_AUDIO = re.compile(r"Stream #\d+:\d+.*: Audio:", re.IGNORECASE)
_TEM_VIDEO = re.compile(r"Stream #\d+:\d+.*: Video:", re.IGNORECASE)
_TEMPO_ATUAL = re.compile(r"out_time_us=(\d+)")


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    has_audio: bool
    has_video: bool
    size_bytes: int = 0


def _ultimas_linhas(texto: str, quantas: int = 15) -> str:
    """O stderr do ffmpeg tem centenas de linhas; so as ultimas interessam."""
    linhas = [l for l in (texto or "").splitlines() if l.strip()]
    return "\n".join(linhas[-quantas:])


def run(
    ferramenta: Path,
    argumentos: Sequence[str],
    total_segundos: float = 0.0,
    progresso: Optional[Progresso] = None,
    cancelar: Optional[Cancelar] = None,
) -> str:
    """Roda o ffmpeg, drenando as saidas. Devolve o stderr completo.

    Quando `total_segundos` e `progresso` vem juntos, le `out_time_us=` do stdout
    (que so existe se `-progress pipe:1` estiver nos argumentos) e reporta.
    """
    comando = [str(ferramenta), "-hide_banner", "-nostdin", *argumentos]
    processo = subprocess.Popen(
        comando,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **popen_kwargs(),
    )

    erros: list[str] = []

    def drenar_stderr() -> None:
        # Thread propria: se ninguem ler, o pipe enche e o ffmpeg trava.
        assert processo.stderr is not None
        for linha in processo.stderr:
            erros.append(linha)

    leitor = threading.Thread(target=drenar_stderr, daemon=True)
    leitor.start()

    try:
        assert processo.stdout is not None
        for linha in processo.stdout:
            if cancelar and cancelar():
                processo.terminate()
                raise FfmpegFalhou("Cancelado.")
            if progresso and total_segundos > 0:
                achado = _TEMPO_ATUAL.search(linha)
                if achado:
                    decorrido = int(achado.group(1)) / 1_000_000
                    progresso(max(0.0, min(1.0, decorrido / total_segundos)))
    finally:
        processo.wait()
        leitor.join(timeout=5)

    stderr = "".join(erros)
    if processo.returncode != 0:
        raise FfmpegFalhou(_ultimas_linhas(stderr))
    return stderr


def probe(ferramentas: Ferramentas, arquivo: Path) -> MediaInfo:
    """Duracao e streams do arquivo.

    Usa o ffprobe quando existe (JSON, mais confiavel) e cai para o stderr do
    proprio ffmpeg quando nao -- o ffprobe e opcional de proposito, para o
    download inicial ser menor.
    """
    arquivo = Path(arquivo)
    tamanho = arquivo.stat().st_size if arquivo.exists() else 0

    if ferramentas.ffprobe is not None:
        try:
            resultado = subprocess.run(
                [
                    str(ferramentas.ffprobe), "-v", "error",
                    "-print_format", "json", "-show_format", "-show_streams",
                    str(arquivo),
                ],
                capture_output=True, text=True, timeout=120, **popen_kwargs(),
            )
            if resultado.returncode == 0:
                dados = json.loads(resultado.stdout or "{}")
                streams = dados.get("streams") or []
                tipos = {s.get("codec_type") for s in streams}
                duracao = float((dados.get("format") or {}).get("duration") or 0.0)
                info = MediaInfo(duracao, "audio" in tipos, "video" in tipos, tamanho)
                if not info.has_audio:
                    raise SemFaixaDeAudio()
                return info
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
            pass  # cai para o ffmpeg

    if ferramentas.ffmpeg is None:
        raise FfmpegFalhou("ffmpeg indisponivel para sondar o arquivo.")

    # `-i` sem saida faz o ffmpeg descrever o arquivo e sair com erro: e o
    # comportamento esperado, entao lemos o stderr em vez de tratar como falha.
    processo = subprocess.run(
        [str(ferramentas.ffmpeg), "-hide_banner", "-nostdin", "-i", str(arquivo)],
        capture_output=True, text=True, timeout=120, **popen_kwargs(),
    )
    stderr = processo.stderr or ""

    achado = _DURACAO.search(stderr)
    duracao = 0.0
    if achado:
        horas, minutos, segundos = achado.groups()
        duracao = int(horas) * 3600 + int(minutos) * 60 + float(segundos)

    info = MediaInfo(
        duration=duracao,
        has_audio=bool(_TEM_AUDIO.search(stderr)),
        has_video=bool(_TEM_VIDEO.search(stderr)),
        size_bytes=tamanho,
    )
    if not info.has_audio:
        raise SemFaixaDeAudio()
    return info


def to_flac16k(
    ferramentas: Ferramentas,
    origem: Path,
    destino: Path,
    duracao: float = 0.0,
    progresso: Optional[Progresso] = None,
    cancelar: Optional[Cancelar] = None,
    normalizar_volume: bool = False,
) -> Path:
    """Extrai o audio em FLAC 16 kHz mono -- o formato que a Groq recomenda.

    Da cerca de 1 MB por minuto, o que define quantos minutos cabem no limite
    de 25 MB do plano gratuito.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    argumentos = [
        "-y", "-i", str(origem),
        "-vn", "-sn", "-dn", "-map", "0:a:0",
        "-ac", "1", "-ar", "16000", "-sample_fmt", "s16",
    ]
    if normalizar_volume:
        argumentos += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    argumentos += [
        "-c:a", "flac", "-compression_level", "8",
        "-progress", "pipe:1", "-nostats",
        str(destino),
    ]
    run(ferramentas.ffmpeg, argumentos, duracao, progresso, cancelar)
    return destino


def slice_flac(
    ferramentas: Ferramentas,
    origem: Path,
    destino: Path,
    inicio: float,
    fim: float,
    cancelar: Optional[Cancelar] = None,
) -> Path:
    """Recorta um trecho, mantendo FLAC 16 kHz mono."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    run(
        ferramentas.ffmpeg,
        [
            "-y", "-ss", f"{inicio:.3f}", "-to", f"{fim:.3f}",
            "-i", str(origem),
            "-c:a", "flac", "-compression_level", "8",
            str(destino),
        ],
        cancelar=cancelar,
    )
    return destino
