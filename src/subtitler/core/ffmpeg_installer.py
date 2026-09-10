"""Baixa o ffmpeg quando o usuario nao tem.

Tres cuidados que fazem a diferenca entre "funciona" e "nao acontece nada":

* **o bit de execucao.** Nem `gzip` nem `zipfile` preservam permissoes. Sem o
  `chmod`, o macOS recusa o binario com `PermissionError` e parece que o
  download falhou.
* **verificar rodando.** So consideramos instalado depois de `ffmpeg -version`
  responder. E o unico jeito de detectar arquitetura errada ou download
  truncado -- no arm64, um binario invalido morre com "Killed: 9", sem stack.
* **nao engolir erro.** A falha volta como excecao com o motivo real. Um
  `except` silencioso aqui deixaria o usuario olhando para uma tela que nunca
  muda.
"""
from __future__ import annotations

import gzip
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

from subtitler.core.errors import SubtitlerError
from subtitler.core.ffmpeg_sources import (
    Binario,
    PlanoDeDownload,
    fallback_for,
    nome_do_executavel,
    plan_for,
)
from subtitler.core.ffmpeg_locator import _executa
from subtitler.core.netcompat import urlopen
from subtitler.core.paths import bin_dir

BLOCO = 64 * 1024

#: `progresso(baixados, total)` em bytes. total=0 quando o servidor nao informa.
Progresso = Callable[[int, int], None]
Cancelar = Callable[[], bool]


class FalhaNoDownload(SubtitlerError):
    def __init__(self, detalhe: str) -> None:
        from subtitler.core.errors import Acao

        super().__init__("Nao foi possivel baixar o ffmpeg", detalhe, Acao.TENTAR_DE_NOVO)


def _baixar(url: str, destino: Path, progresso: Optional[Progresso], cancelar: Optional[Cancelar]) -> None:
    requisicao = urllib.request.Request(url, headers={"User-Agent": "Subtitler"})
    destino.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(requisicao, timeout=120) as resposta:
        total = int(resposta.headers.get("Content-Length") or 0)
        baixados = 0
        with destino.open("wb") as saida:
            while True:
                if cancelar and cancelar():
                    raise FalhaNoDownload("Cancelado pelo usuario.")
                bloco = resposta.read(BLOCO)
                if not bloco:
                    break
                saida.write(bloco)
                baixados += len(bloco)
                if progresso:
                    progresso(baixados, total)


def _extrair_gz(origem: Path, destino: Path) -> None:
    with gzip.open(origem, "rb") as entrada, destino.open("wb") as saida:
        shutil.copyfileobj(entrada, saida)


def _extrair_zip(origem: Path, destino: Path, sufixo_do_membro: str) -> None:
    with zipfile.ZipFile(origem) as arquivo:
        alvo = next(
            (n for n in arquivo.namelist() if n.replace("\\", "/").endswith(sufixo_do_membro)),
            None,
        )
        if alvo is None:
            raise FalhaNoDownload(f"O pacote nao contem {sufixo_do_membro}.")
        with arquivo.open(alvo) as entrada, destino.open("wb") as saida:
            shutil.copyfileobj(entrada, saida)


def _instalar_um(
    binario: Binario,
    progresso: Optional[Progresso],
    cancelar: Optional[Cancelar],
) -> Path:
    pasta = bin_dir()
    temporario = pasta / f".{binario.nome}.download"
    parcial = pasta / f".{binario.nome}.parcial"
    final = pasta / nome_do_executavel(binario.nome)

    try:
        _baixar(binario.url, temporario, progresso, cancelar)
        if binario.formato == "zip":
            _extrair_zip(temporario, parcial, binario.membro or binario.nome)
        else:
            _extrair_gz(temporario, parcial)

        # Sem isto o macOS recusa o binario e parece que nada aconteceu.
        parcial.chmod(0o755)

        if not _executa(parcial):
            raise FalhaNoDownload(
                f"O {binario.nome} baixado nao executou nesta maquina. "
                "Pode ser arquitetura incompativel ou download incompleto."
            )

        # So agora vira o binario oficial: nunca deixamos um meio-instalado.
        parcial.replace(final)
        return final
    finally:
        for lixo in (temporario, parcial):
            try:
                lixo.unlink(missing_ok=True)
            except OSError:
                pass


def install(
    plano: Optional[PlanoDeDownload] = None,
    progresso: Optional[Progresso] = None,
    cancelar: Optional[Cancelar] = None,
) -> dict:
    """Baixa e verifica. Devolve `{"ffmpeg": Path, "ffprobe": Path|None}`.

    O ffprobe e opcional: se ele falhar, seguimos com o ffmpeg, que ja resolve.
    Falhar por causa do opcional seria pior que a doenca.
    """
    plano = plano or plan_for()
    resultado: dict = {"ffmpeg": None, "ffprobe": None}
    erro_do_ffmpeg: Optional[Exception] = None

    for binario in plano.binarios:
        try:
            resultado[binario.nome] = _instalar_um(binario, progresso, cancelar)
        except Exception as exc:
            if binario.nome == "ffmpeg":
                erro_do_ffmpeg = exc
            # ffprobe que falha nao interrompe: seguimos sem ele.

    if resultado["ffmpeg"] is None:
        alternativa = fallback_for()
        if alternativa is not None:
            try:
                resultado["ffmpeg"] = _instalar_um(alternativa, progresso, cancelar)
                return resultado
            except Exception as exc:
                erro_do_ffmpeg = exc
        raise FalhaNoDownload(str(erro_do_ffmpeg or "Origem indisponivel."))

    return resultado
