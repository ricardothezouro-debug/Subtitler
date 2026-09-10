import sys
from pathlib import Path

# Torna o pacote (em src/) importavel nos testes sem instalar.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
