"""Put src/ on the import path so tests and tools use flat imports."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
