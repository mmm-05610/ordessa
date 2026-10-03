"""tests/service collection root: the controlled-proof fixtures live in
``service_helpers.py`` (importable by every test module in this directory without
importing ``conftest`` itself). See ``service_helpers.py`` for the stack contract."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from service_helpers import (  # noqa: F401,E402  (re-export so fixtures are collected)
    AllowProbeAuthority,
    DenyProbeAuthority,
    FakeCredentialRecords,
    FakeSecretStore,
    FakeSubmissionGate,
    Stack,
    fake_probe_runner,
    make_client,
    raising_probe_runner,
    saved,
    stack,
    stdio_definition,
)
