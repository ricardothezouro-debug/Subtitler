# Subtitler

Plugin do **Streamer Sidekick** que transforma vídeo ou áudio em legendas
prontas: manda o arquivo, recebe **SRT**, **VTT** e **TXT** com os tempos certos.

Feito para VOD de live: transcreve em português (ou no idioma que você escolher),
respeita as regras de legenda que o YouTube e os editores esperam, e não te
obriga a revisar quebra de linha a quebra de linha.

## Estado

Em construção. O núcleo de legendas já está de pé e testado; a integração com a
API e a interface vêm a seguir.

| Parte | Estado |
|---|---|
| Modelo de transcrição, quebra de linha, regras de cue, SRT/VTT/TXT | pronto |
| ffmpeg (download automático), extração de áudio, fatiamento | a fazer |
| API da Groq, pipeline completo | a fazer |
| Interface | a fazer |

## Como funciona

A transcrição usa a **API da Groq** (`whisper-large-v3`), que tem plano gratuito
suficiente para uso pessoal — 8 horas de áudio por dia. Você cola sua própria
chave na aba **Configurações** do plugin; há um "?" ao lado explicando como
obter uma.

O áudio é convertido para FLAC 16 kHz mono antes de subir (o formato que a Groq
recomenda) e, se for longo, fatiado em pontos de silêncio para respeitar o
limite de 25 MB por requisição do plano gratuito.

## O que torna a legenda boa

Transcrever é a parte fácil. O que separa uma legenda utilizável de um despejo
de texto são as regras de exibição:

- **42 caracteres por linha, 2 linhas** — acima disso vaza na tela do celular
- **17 caracteres por segundo** (teto de 20) — a velocidade de leitura confortável
- **1 a 7 segundos** por legenda — nem rápido demais para ler, nem tão longo que
  o espectador releia
- **quebra na fronteira certa** — depois de pontuação, nunca entre `R$` e o
  valor, nunca separando preposição do termo que ela rege
- quando não cabe em duas linhas, **divide no tempo** em vez de abrir uma terceira

Essas regras são funções puras e têm testes que rodam sem rede e sem ffmpeg.

## Desenvolvimento

```bash
python3 -m venv .venv
source .venv/bin/activate          # no Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```

Para desenvolver com uma chave, copie `.env.example` para `.env` e preencha.
O `.env` está no `.gitignore` e nunca deve ser versionado.

O plugin roda no **Windows e no macOS** — requisito do padrão de plugins do
Sidekick, verificado pelo CI nas duas plataformas.

### Dependências

Apenas **PySide6 + biblioteca padrão**. O Streamer Sidekick empacotado não
carrega bibliotecas de terceiros, então um `import requests` esquecido faria o
plugin instalar e nunca abrir. Há um teste (`tests/test_guardrails.py`) que lê o
código e falha se isso acontecer.

O ffmpeg entra como binário externo, baixado sob demanda — não como pacote Python.

## Licença

O código deste repositório é do projeto Streamer Sidekick. O **ffmpeg** baixado
em tempo de execução é software separado, distribuído sob seus próprios termos
(LGPL/GPL) e obtido de builds públicos — ele não é redistribuído aqui.
