"""tests/contract collection root.

Every helper and fixture lives in ``contract_helpers.py`` (uniquely named):
NO test module in this tree may ``from conftest import ...`` — sibling
directories each carry their own ``conftest.py`` and the basename collision is
a known failure mode here. This file only puts the directory on ``sys.path``
and re-exports the helper fixtures so pytest collects them.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract_helpers import (  # noqa: F401,E402  (re-export: fixtures collect)
    FAKE_STDIO_SERVER,
    AllowProbeAuthority,
    DenyProbeAuthority,
    LoopbackHttpFake,
    RegisteredSurface,
    Stack,
    contract_primitives,
    remote_definition,
    seed,
    stdio_definition,
)
