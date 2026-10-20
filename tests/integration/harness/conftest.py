"""Explicit support roots for cross-owner controlled Harness integration tests."""
import sys
from pathlib import Path
_here = Path(__file__).resolve().parent
_repo = _here.parents[2]
for _support in (_here / "support", _here / "configuration_model", _repo / "packages/execution/agents/tests/support"):
    if str(_support) not in sys.path:
        sys.path.insert(0, str(_support))
