"""Resolve the shared controlled test-support package."""
from pathlib import Path
import sys

SUPPORT = Path(__file__).resolve().parents[4] / "packages/execution/agents/tests/support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
