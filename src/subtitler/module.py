"""Adaptador de plugin do Streamer Sidekick.

O hub carrega ferramentas como *modulos*: `module_info()` descreve o card e
`build_page()` devolve o QWidget que ele embute.

Duas regras do padrao valem especialmente aqui:

* **nada pesado no import.** `help_text()` e chamado no momento em que o modulo
  e importado, e `build_page()` roda na thread da interface. Por isso os imports
  de verdade ficam dentro das funcoes, e nada toca rede ou disco aqui.
* **funcionar sem o Sidekick importavel**, para dar para desenvolver e testar
  fora dele.
"""
from __future__ import annotations

from dataclasses import dataclass

ACCENT = "#FF4FD8"  # magenta, para o card nao se confundir com o ciano do StreamOn
MODULE_ID = "subtitler"


@dataclass(frozen=True)
class ModuleInfo:
    module_id: str
    title: str
    subtitle: str
    status: str
    accent: str


def module_info():
    """Dados do card. Usa a classe do Sidekick quando ela existe, para o objeto
    ser aceito direto pelo registro dele."""
    dados = dict(
        module_id=MODULE_ID,
        title="Subtitler",
        subtitle="Transforma vídeo ou áudio em legendas prontas: SRT, VTT e TXT.",
        status="Pronto para transcrever",
        accent=ACCENT,
    )
    try:  # pragma: no cover - so quando roda dentro do Sidekick
        from streamer_sidekick.core.modules import ModuleInfo as SidekickModuleInfo

        return SidekickModuleInfo(**dados)
    except Exception:
        return ModuleInfo(**dados)


def help_text() -> str:
    """Texto da tela Ajuda do hub. Chamado no import: mantenha barato."""
    return (
        "O Subtitler transcreve um vídeo ou áudio e gera as legendas com os "
        "tempos certos, prontas para o YouTube.\n\n"
        "Como usar:\n"
        "• Em Configurações, cole sua chave da Groq (o plano gratuito basta; "
        "há um \"?\" explicando como obter uma).\n"
        "• Na aba Transcrever, escolha o arquivo — ou arraste-o para a janela.\n"
        "• Marque os formatos que quer (SRT para o YouTube, TXT para ter o "
        "texto corrido) e clique em Gerar legendas.\n\n"
        "Na primeira vez o Subtitler baixa o ffmpeg, que ele usa para ler o "
        "áudio. É um download único.\n\n"
        "Arquivos longos são divididos automaticamente em pausas da fala, para "
        "caber no limite do plano gratuito."
    )


def build_page(config=None):
    """Devolve a página embutida no hub.

    Os imports ficam aqui dentro de propósito: importar o módulo não pode
    carregar o Qt inteiro nem tocar em disco.
    """
    from subtitler.ui.page import SubtitlerPage

    return SubtitlerPage()
