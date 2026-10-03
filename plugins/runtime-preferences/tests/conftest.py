"""Test path bootstrap: the package under test is NOT pip-installed (the
write surface of dispatch P-A forbids touching the shared venv); tests insert
this package's ``src`` on sys.path. Everything else (ordessa_harness_api,
ordessa_harness, server_plugin_api, ordessa_server) resolves from the
standard workspace venv.
"""
from __future__ import annotations

from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
