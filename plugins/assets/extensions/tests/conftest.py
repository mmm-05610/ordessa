"""Make the package sources importable without an editable install.

Same discipline as the Skills conftest: repo `src/` roots are appended
ONLY when the matching module is not already importable — an installed
distribution always wins. The published dependencies (`pacthold`,
`server_plugin_api`, `ordessa_harness_api`) come from the verification
venv (docs/baseline.md); only THIS package needs the path pin.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

if (importlib.util.find_spec("ordessa_extensions") is None
        and (PLUGIN_ROOT / "src").is_dir()):
    sys.path.append(str(PLUGIN_ROOT / "src"))
