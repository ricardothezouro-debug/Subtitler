"""Os erros que so apareceriam na maquina do usuario.

O Streamer Sidekick empacotado com PyInstaller so carrega o que esta nos
`hiddenimports` do `.spec`. Um `import requests` esquecido aqui instala normal,
mas ao abrir o plugin vira `ModuleNotFoundError` -- e o usuario ve so uma pagina
de erro. Nao existe teste de integracao que pegue isso: o ambiente de
desenvolvimento tem tudo instalado.

Estes testes leem o codigo com AST e falham ANTES de o plugin ir para o catalogo.
Sao a versao automatizada das quatro armadilhas do PLUGIN_STANDARD secao 7.1.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "src" / "subtitler"

# O que o interpretador congelado do Sidekick realmente tem.
PERMITIDOS = {"PySide6", "subtitler"}


def modulos(subpasta: str = "") -> list[Path]:
    base = RAIZ / subpasta if subpasta else RAIZ
    return sorted(base.rglob("*.py"))


def _imports_de_topo(caminho: Path) -> set[str]:
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for alias in no.names:
                nomes.add(alias.name.split(".")[0])
        elif isinstance(no, ast.ImportFrom):
            if no.level == 0 and no.module:
                nomes.add(no.module.split(".")[0])
    return nomes


def _nos_de_docstring(arvore: ast.AST) -> set[int]:
    """Ids dos nos que sao docstring de modulo, classe ou funcao."""
    ids: set[int] = set()
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        corpo = getattr(no, "body", [])
        if (
            corpo
            and isinstance(corpo[0], ast.Expr)
            and isinstance(corpo[0].value, ast.Constant)
            and isinstance(corpo[0].value.value, str)
        ):
            ids.add(id(corpo[0].value))
    return ids


def test_core_nao_importa_qt():
    """`core/` tem que rodar sem display, senao nada nele e testavel offline.

    E o que permite testar as regras de legenda -- a parte que define a
    qualidade -- sem rede, sem ffmpeg e sem interface.
    """
    ofensores = []
    for caminho in modulos("core"):
        if "PySide6" in _imports_de_topo(caminho):
            ofensores.append(caminho.relative_to(RAIZ))
    assert not ofensores, f"core/ nao pode importar PySide6: {ofensores}"


def test_nenhuma_dependencia_de_terceiros():
    """Simula o build congelado: so stdlib, PySide6 e o proprio pacote."""
    stdlib = set(sys.stdlib_module_names)
    ofensores: dict[str, set[str]] = {}
    for caminho in modulos():
        estranhos = _imports_de_topo(caminho) - stdlib - PERMITIDOS
        # streamer_sidekick e opcional por design: sempre dentro de try/except.
        estranhos.discard("streamer_sidekick")
        if estranhos:
            ofensores[str(caminho.relative_to(RAIZ))] = estranhos
    assert not ofensores, (
        f"dependencias que o portable do Sidekick nao tem: {ofensores}"
    )


def test_import_do_sidekick_sempre_protegido():
    """O plugin tem que funcionar mesmo sem o Sidekick importavel."""
    for caminho in modulos():
        texto = caminho.read_text(encoding="utf-8")
        if "streamer_sidekick" not in texto:
            continue
        arvore = ast.parse(texto)
        for no in ast.walk(arvore):
            if isinstance(no, ast.ImportFrom) and (no.module or "").startswith(
                "streamer_sidekick"
            ):
                dentro_de_try = any(
                    isinstance(pai, ast.Try)
                    for pai in ast.walk(arvore)
                    if isinstance(pai, ast.Try)
                    and any(no is filho for filho in ast.walk(pai))
                )
                assert dentro_de_try, (
                    f"{caminho.name}: import do Sidekick precisa de try/except"
                )


def test_sem_caminho_de_windows_em_texto():
    """Armadilha 4: `C:\\...` numa mensagem e mentira para quem esta no Mac."""
    proibidos = ("C:\\", "%APPDATA%", "%LOCALAPPDATA%")
    # ffmpeg_sources lida com nomes de arquivo por plataforma; e a excecao.
    isentos = {"ffmpeg_sources.py", "ffmpeg_locator.py", "paths.py"}
    ofensores: list[str] = []
    for caminho in modulos():
        if caminho.name in isentos:
            continue
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        # Docstring que CITA o caminho proibido para explicar a regra nao e
        # texto de interface -- so o que pode chegar ao usuario conta.
        docstrings = _nos_de_docstring(arvore)
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Constant) or not isinstance(no.value, str):
                continue
            if id(no) in docstrings:
                continue
            if any(p in no.value for p in proibidos):
                ofensores.append(f"{caminho.name}: {no.value[:40]}")
    assert not ofensores, f"caminho de Windows em texto: {ofensores}"


def test_sem_os_startfile():
    """Armadilha 3: nao existe fora do Windows (`AttributeError`)."""
    for caminho in modulos():
        texto = caminho.read_text(encoding="utf-8")
        assert "os.startfile" not in texto, (
            f"{caminho.name}: use platform_utils.open_path"
        )


def test_creationflags_so_dentro_de_check_de_plataforma():
    """Armadilha 3: `creationflags` levanta ValueError fora do Windows."""
    for caminho in modulos():
        texto = caminho.read_text(encoding="utf-8")
        if "creationflags" not in texto:
            continue
        assert 'sys.platform == "win32"' in texto, (
            f"{caminho.name}: creationflags precisa de guarda de plataforma"
        )
