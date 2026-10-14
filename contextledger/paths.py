"""Stable checkout resource root, independent of functional subpackage depth."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
