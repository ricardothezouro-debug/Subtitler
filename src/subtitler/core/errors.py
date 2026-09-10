"""Erros que a interface sabe mostrar sem precisar entender o que aconteceu.

Cada erro carrega tres coisas: um titulo curto, o detalhe, e a ACAO que resolve.
A UI so le esses tres campos e monta o banner -- ela nao precisa de um `if` para
cada tipo de falha, e nenhum erro chega ao usuario como stack trace.

Regra que vale para todas as mensagens: nada de caminho fixo de Windows. Quando
precisar citar uma pasta, monte em runtime a partir de `paths.data_dir()` --
`C:\\...` numa mensagem e mentira para quem esta no Mac.
"""
from __future__ import annotations


class Acao:
    """O que o usuario pode fazer a respeito."""

    NENHUMA = "nenhuma"
    ABRIR_CONFIGURACOES = "abrir_configuracoes"
    INSTALAR_FFMPEG = "instalar_ffmpeg"
    TENTAR_DE_NOVO = "tentar_de_novo"
    ESCOLHER_ARQUIVO = "escolher_arquivo"


class SubtitlerError(Exception):
    """Base de tudo que a UI mostra como banner."""

    def __init__(self, titulo: str, detalhe: str = "", acao: str = Acao.NENHUMA) -> None:
        super().__init__(f"{titulo} {detalhe}".strip())
        self.titulo = titulo
        self.detalhe = detalhe
        self.acao = acao


class ChaveAusente(SubtitlerError):
    def __init__(self) -> None:
        super().__init__(
            "Falta a chave da API",
            "Cole sua chave da Groq em Configuracoes. O plano gratuito e suficiente.",
            Acao.ABRIR_CONFIGURACOES,
        )


class ChaveRecusada(SubtitlerError):
    def __init__(self) -> None:
        super().__init__(
            "A chave foi recusada",
            "A Groq nao aceitou esta chave. Confira em Configuracoes.",
            Acao.ABRIR_CONFIGURACOES,
        )


class FfmpegAusente(SubtitlerError):
    def __init__(self) -> None:
        super().__init__(
            "Falta o ffmpeg",
            "O Subtitler usa o ffmpeg para ler audio. E um download unico.",
            Acao.INSTALAR_FFMPEG,
        )


class FfmpegFalhou(SubtitlerError):
    def __init__(self, detalhe: str) -> None:
        super().__init__("O ffmpeg falhou", detalhe, Acao.TENTAR_DE_NOVO)


class SemFaixaDeAudio(SubtitlerError):
    def __init__(self) -> None:
        super().__init__(
            "Este arquivo nao tem audio",
            "Escolha um video ou audio que contenha uma faixa de som.",
            Acao.ESCOLHER_ARQUIVO,
        )


class SemInternet(SubtitlerError):
    def __init__(self) -> None:
        super().__init__(
            "Sem conexao com a internet",
            "A transcricao acontece na nuvem. Verifique sua conexao.",
            Acao.TENTAR_DE_NOVO,
        )


class LimiteAtingido(SubtitlerError):
    """429. Carrega quantos segundos esperar, para a UI mostrar contagem."""

    def __init__(self, esperar_segundos: float) -> None:
        self.esperar_segundos = esperar_segundos
        super().__init__(
            "Limite do plano gratuito atingido",
            f"Aguardando {int(esperar_segundos)}s para continuar.",
            Acao.TENTAR_DE_NOVO,
        )


class EspacoInsuficiente(SubtitlerError):
    def __init__(self, precisa_mb: int, livre_mb: int) -> None:
        super().__init__(
            "Espaco em disco insuficiente",
            f"Sao necessarios cerca de {precisa_mb} MB e ha {livre_mb} MB livres.",
            Acao.NENHUMA,
        )


class Cancelado(SubtitlerError):
    """Nao e erro: o usuario pediu para parar. A UI mostra em cinza, nao vermelho."""

    def __init__(self) -> None:
        super().__init__("Cancelado", "", Acao.NENHUMA)
