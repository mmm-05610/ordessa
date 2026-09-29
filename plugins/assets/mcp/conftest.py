"""Make the flat ``backend/`` package importable without installation.

Running ``python -m pytest plugins/assets/mcp`` from the repository root must
work with no pip install, so the package root goes on ``sys.path`` here and
tests import ``from backend.definition import ...`` (design-doc literal
paths, see specs/011-q4-mcp/reports/t01-t02.md).
"""
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))
