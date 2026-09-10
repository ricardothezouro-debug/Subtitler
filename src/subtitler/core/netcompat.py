"""HTTPS que funciona nos dois sistemas.

Rodando como plugin usamos o helper do Streamer Sidekick, que ja resolveu este
problema: no macOS o Python nao usa o Keychain, e `urlopen` direto morre em
`CERTIFICATE_VERIFY_FAILED`. Fora do Sidekick reproduzimos a mesma logica --
contexto padrao do sistema, completado com as raizes do certifi so quando o
padrao vem vazio.

Substituir a loja do sistema seria errado: no Windows e ela que faz proxy
corporativo com raiz propria funcionar.
"""
from __future__ import annotations

import ssl
import urllib.request
from functools import lru_cache
from typing import Any


def _tem_raizes(contexto: ssl.SSLContext) -> bool:
    try:
        return int(contexto.cert_store_stats().get("x509_ca", 0)) > 0
    except Exception:
        return True


@lru_cache(maxsize=1)
def _contexto_local() -> ssl.SSLContext:
    contexto = ssl.create_default_context()
    if _tem_raizes(contexto):
        return contexto
    try:
        import certifi  # type: ignore

        contexto.load_verify_locations(cafile=certifi.where())
    except (ImportError, OSError):
        pass
    return contexto


def urlopen(request: Any, timeout: float = 30.0) -> Any:
    """`urlopen` com o contexto TLS correto para a plataforma."""
    try:
        from streamer_sidekick.core import net  # type: ignore

        return net.urlopen(request, timeout=timeout)
    except ImportError:
        return urllib.request.urlopen(request, timeout=timeout, context=_contexto_local())
