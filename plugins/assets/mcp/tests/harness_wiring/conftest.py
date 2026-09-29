"""tests/harness_wiring collection root (Q4 T013).

The package-root conftest already puts the plugin root on ``sys.path`` and
seals ``socket``/``subprocess`` for every MCP test. This directory adds the
import paths for the T04 adapter factories (``tests/adapters``) and the
service composition stack (``tests/service``) so the wiring tests reuse the
REAL in-memory DTO factories instead of duplicating them. No filesystem
seal here: the controlled C4 chain runs against real temp directories
(sqlite journal + private generations) exactly like the harness's own
controlled test — and still never spawns or touches the network (the
parent seal holds).
"""
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
for _p in (_TESTS / "adapters", _TESTS / "service"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
