"""Preferencias do plugin, gravadas fora da pasta dele.

A pasta do plugin e sobrescrita a cada atualizacao -- por isso o arquivo vive em
`paths.data_dir()`, que sobrevive.

O round-trip preserva chaves desconhecidas de proposito: se uma versao futura
acrescentar um campo e o usuario voltar para esta, o campo nao e apagado.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from typing import Any

from subtitler.core.cues import CueRules
from subtitler.core.paths import settings_path

PADRAO: dict[str, Any] = {
    "api_key": "",
    "model": "whisper-large-v3",
    "language": "pt",
    "formats": ["srt"],
    "output_dir": "",
    "prompt": "",
    "ffmpeg_path": "",
    "txt_com_tempos": False,
    "cue": {
        "max_chars_per_line": 42,
        "target_cps": 17.0,
        "hard_max_cps": 20.0,
        "min_duration": 1.0,
        "max_duration": 7.0,
    },
}

MAX_PROMPT = 800


class SettingsStore:
    def __init__(self, caminho=None) -> None:
        self.path = caminho or settings_path()
        self._data = self._carregar()

    # --- leitura/escrita ---------------------------------------------------
    def _carregar(self) -> dict[str, Any]:
        dados = json.loads(json.dumps(PADRAO))  # copia profunda barata
        if not self.path.exists():
            return dados
        try:
            existente = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dados
        if isinstance(existente, dict):
            dados.update(existente)  # preserva chaves desconhecidas
            if isinstance(existente.get("cue"), dict):
                dados["cue"] = {**PADRAO["cue"], **existente["cue"]}
        return dados

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        # A chave da API mora aqui: no POSIX, so o dono le.
        if sys.platform != "win32":
            try:
                os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

    # --- acesso ------------------------------------------------------------
    def get(self, chave: str, padrao: Any = None) -> Any:
        return self._data.get(chave, padrao)

    def set(self, chave: str, valor: Any) -> None:
        self._data[chave] = valor
        self.save()

    @property
    def api_key(self) -> str:
        return str(self._data.get("api_key") or "").strip()

    @property
    def prompt(self) -> str:
        return str(self._data.get("prompt") or "")[:MAX_PROMPT]

    def cue_rules(self) -> CueRules:
        bruto = self._data.get("cue") or {}
        padrao = CueRules()
        return CueRules(
            max_chars_per_line=int(bruto.get("max_chars_per_line", padrao.max_chars_per_line)),
            target_cps=float(bruto.get("target_cps", padrao.target_cps)),
            hard_max_cps=float(bruto.get("hard_max_cps", padrao.hard_max_cps)),
            min_duration=float(bruto.get("min_duration", padrao.min_duration)),
            max_duration=float(bruto.get("max_duration", padrao.max_duration)),
        )


def mascarar(chave: str) -> str:
    """Como a chave aparece na tela depois de salva. Nunca inteira, nunca em log."""
    chave = (chave or "").strip()
    if len(chave) <= 8:
        return "•" * len(chave)
    return f"{chave[:4]}…{chave[-4:]}"
