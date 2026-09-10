"""Do arquivo do usuario ate os arquivos de legenda.

Orquestra: sondar, normalizar, fatiar, transcrever, juntar, exportar. Nao sabe
nada de Qt -- reporta por callbacks, e quem quiser barra de progresso que
traduza para sinal.

Cada trabalho tem uma pasta propria com o audio normalizado e cada pedaco ja
transcrito em JSON. E o que permite **retomar**: se cair no pedaco 12 de 18, a
proxima tentativa reaproveita os 11 primeiros em vez de reenviar tudo.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

from subtitler.core import formats, media, silence
from subtitler.core.cues import CueRules, build_cues
from subtitler.core.errors import Cancelado, EspacoInsuficiente, SubtitlerError
from subtitler.core.ffmpeg_locator import Ferramentas
from subtitler.core.groq_client import (
    GroqClient,
    LimiteDeUso,
    codigo_de_idioma,
    esperar_com_cancelamento,
)
from subtitler.core.paths import jobs_dir
from subtitler.core.transcript import Transcript, from_verbose_json, merge, sanitize

#: `progresso(porcentagem 0..100, mensagem)`.
#: Inteiro de proposito: a barra do Sidekick espera 0..100, e passar 0..1 a
#: deixa parada sem erro nenhum.
Progresso = Callable[[int, str], None]
Cancelar = Callable[[], bool]
Aviso = Callable[[int], None]

#: Espaco exigido por minuto de midia (FLAC + fatias), com folga.
MB_POR_MINUTO = 2.5
#: Acima disto desistimos de esperar o limite gratuito liberar.
MAX_ESPERA = 15 * 60


@dataclass
class Job:
    origem: Path
    saida: Path
    formatos: Sequence[str] = ("srt",)
    idioma: str = "auto"
    prompt: str = ""
    modelo: str = "whisper-large-v3"
    regras: CueRules = field(default_factory=CueRules)
    txt_com_tempos: bool = False

    @property
    def id(self) -> str:
        """Identifica o trabalho -- e, com ele, o cache que pode ser retomado.

        Entra tudo o que muda a TRANSCRICAO: o arquivo, o modelo, o idioma e os
        termos. Antes era so o caminho do arquivo, e isso enganava feio: trocar
        para o modelo preciso e rodar de novo devolvia o resultado antigo em
        dois segundos, porque as partes em cache eram reaproveitadas como se
        nada tivesse mudado. O usuario mexia nas opcoes e nada acontecia.

        Formato de saida e regras de legenda ficam DE FORA de proposito: mudar
        de SRT para VTT nao deve custar uma transcricao nova.
        """
        assinatura = "\n".join(
            [str(self.origem), self.modelo, self.idioma, self.prompt]
        )
        digest = hashlib.sha1(assinatura.encode("utf-8")).hexdigest()[:10]
        return f"{self.origem.stem[:32]}-{digest}"


@dataclass
class Resultado:
    arquivos: list[Path]
    transcricao: Transcript
    duracao: float
    tem_video: bool


def _fase(inicio: int, fim: int, fracao: float) -> int:
    """Mapeia o progresso de uma fase para a barra global."""
    return int(inicio + (fim - inicio) * max(0.0, min(1.0, fracao)))


def _checar_espaco(origem: Path, duracao: float) -> None:
    precisa = int((duracao / 60) * MB_POR_MINUTO) + 50
    try:
        livre = shutil.disk_usage(origem.parent).free // (1024 * 1024)
    except OSError:
        return
    if livre < precisa:
        raise EspacoInsuficiente(precisa, int(livre))


def run_job(
    job: Job,
    ferramentas: Ferramentas,
    cliente: GroqClient,
    progresso: Optional[Progresso] = None,
    cancelar: Optional[Cancelar] = None,
    aviso_de_espera: Optional[Aviso] = None,
) -> Resultado:
    def relatar(pct: int, mensagem: str) -> None:
        if progresso:
            progresso(pct, mensagem)

    def parar() -> bool:
        return bool(cancelar and cancelar())

    def checar_cancelamento() -> None:
        if parar():
            raise Cancelado()

    pasta = jobs_dir() / job.id
    (pasta / "partes").mkdir(parents=True, exist_ok=True)

    # --- 1. sondar --------------------------------------------------------
    relatar(1, "Lendo o arquivo…")
    info = media.probe(ferramentas, job.origem)
    _checar_espaco(job.origem, info.duration)
    checar_cancelamento()

    # --- 2. normalizar ----------------------------------------------------
    relatar(3, "Extraindo o áudio…")
    master = pasta / "master.flac"
    if not master.exists():
        media.to_flac16k(
            ferramentas, job.origem, master, info.duration,
            progresso=lambda f: relatar(_fase(3, 28, f), "Extraindo o áudio…"),
            cancelar=parar,
        )
    checar_cancelamento()

    # --- 3. fatiar --------------------------------------------------------
    from subtitler.core.groq_client import LIMITE_BYTES

    if master.stat().st_size <= LIMITE_BYTES:
        fatias = [silence.Fatia(0, 0.0, info.duration)]
        relatar(32, "Áudio cabe numa requisição.")
    else:
        relatar(29, "Procurando pausas para dividir…")
        silencios = silence.detect(ferramentas, master)
        fatias = silence.plan_chunks(info.duration, silencios)
        relatar(32, f"Dividido em {len(fatias)} partes.")
    checar_cancelamento()

    # --- 4. transcrever ---------------------------------------------------
    partes: list[Transcript] = []
    cortes_duros = {f.indice for f in fatias if f.corte_duro}
    # Em "auto" o Whisper detecta o idioma DE CADA FATIA, isolada. Num VOD
    # dividido em 18 partes ele pode decidir "espanhol" ou "galego" num trecho
    # de portugues -- e o resultado sai cheio de palavra trocada, sem erro
    # nenhum aparecendo. Fixamos o que a primeira fatia detectou e mandamos
    # explicito nas seguintes.
    idioma_efetivo = job.idioma

    for posicao, fatia in enumerate(fatias):
        checar_cancelamento()
        rotulo = (
            f"Transcrevendo parte {posicao + 1} de {len(fatias)}…"
            if len(fatias) > 1
            else "Transcrevendo…"
        )
        base = _fase(33, 93, posicao / len(fatias))
        proximo = _fase(33, 93, (posicao + 1) / len(fatias))
        relatar(base, rotulo)

        cache = pasta / "partes" / f"{fatia.indice}.json"
        if cache.exists():
            # Retomada: esta parte ja foi transcrita numa tentativa anterior.
            guardado = json.loads(cache.read_text("utf-8"))
            idioma_efetivo = _fixar_idioma(idioma_efetivo, guardado)
            partes.append(from_verbose_json(guardado, fatia.start))
            continue

        if len(fatias) == 1:
            pedaco = master
        else:
            pedaco = pasta / f"parte_{fatia.indice:03d}.flac"
            if not pedaco.exists():
                media.slice_flac(ferramentas, master, pedaco, fatia.start, fatia.end, parar)

        bruto = _transcrever_com_paciencia(
            cliente, pedaco, job, idioma_efetivo, parar, aviso_de_espera,
            lambda enviados, total: relatar(
                _fase(base, proximo, (enviados / total) if total else 0.0), rotulo
            ),
        )
        idioma_efetivo = _fixar_idioma(idioma_efetivo, bruto)
        cache.write_text(json.dumps(bruto, ensure_ascii=False), encoding="utf-8")
        partes.append(from_verbose_json(bruto, fatia.start))

        if pedaco != master:
            pedaco.unlink(missing_ok=True)

    # --- 5. juntar --------------------------------------------------------
    relatar(94, "Juntando as partes…")
    transcricao = sanitize(merge(partes, cortes_duros))
    (pasta / "transcript.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "language": transcricao.language,
                "word_level": transcricao.word_level,
                "words": [{"text": w.text, "start": w.start, "end": w.end}
                          for w in transcricao.words],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # --- 6. exportar ------------------------------------------------------
    relatar(96, "Gerando as legendas…")
    cues = build_cues(transcricao.words, job.regras)
    arquivos: list[Path] = []
    for formato in job.formatos:
        destino = _destino_livre(job.saida, job.origem.stem, formato)
        opcoes = {"com_tempos": job.txt_com_tempos} if formato == "txt" else {}
        arquivos.append(formats.write(cues, destino, formato, **opcoes))

    # O master.flac e o unico arquivo grande aqui (~1 MB por minuto de video).
    # limpar_job() existia para isso e nunca era chamado por ninguem, entao cada
    # transcricao deixava o audio inteiro no disco para sempre. Os JSONs ficam:
    # sao pequenos e sao o que permite retomar sem reenviar nada.
    master.unlink(missing_ok=True)

    relatar(100, "Pronto.")
    return Resultado(
        arquivos=arquivos,
        transcricao=transcricao,
        duracao=info.duration,
        tem_video=info.has_video,
    )


def _fixar_idioma(atual: str, resposta: object) -> str:
    """Troca "auto" pelo idioma que a API acabou de detectar.

    So age uma vez: assim que ha um codigo, ele vale para todas as fatias
    seguintes. Se a API devolver algo que nao reconhecemos, continua em "auto".
    """
    if atual and atual != "auto":
        return atual
    if not isinstance(resposta, dict):
        return atual
    return codigo_de_idioma(resposta.get("language")) or atual


def _transcrever_com_paciencia(
    cliente: GroqClient,
    audio: Path,
    job: Job,
    idioma: str,
    parar: Callable[[], bool],
    aviso: Optional[Aviso],
    progresso_upload,
) -> dict:
    """Envia, e se bater no limite gratuito, espera e tenta de novo.

    O plano gratuito libera 2 horas de audio por hora. Um VOD longo VAI pausar
    -- e melhor esperar avisando do que devolver um erro que parece defeito.
    """
    esperado = 0.0
    while True:
        try:
            return cliente.transcribe(
                audio, idioma=idioma, prompt=job.prompt,
                progresso=progresso_upload, cancelar=parar,
            )
        except LimiteDeUso as limite:
            esperado += limite.esperar
            if esperado > MAX_ESPERA:
                raise SubtitlerError(
                    "O limite do plano gratuito não liberou",
                    "As partes já transcritas foram guardadas: é só tentar de novo mais tarde.",
                ) from limite
            esperar_com_cancelamento(limite.esperar, parar, aviso)


def _destino_livre(pasta: Path, nome: str, formato: str) -> Path:
    """Evita sobrescrever um arquivo que ja existe."""
    pasta = Path(pasta)
    candidato = pasta / f"{nome}.{formato}"
    contador = 2
    while candidato.exists():
        candidato = pasta / f"{nome} ({contador}).{formato}"
        contador += 1
    return candidato


def limpar_job(job_id: str) -> None:
    """Apaga o audio intermediario depois de terminado."""
    alvo = jobs_dir() / job_id
    if alvo.exists():
        shutil.rmtree(alvo, ignore_errors=True)
