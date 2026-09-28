"""016 红线 — 写入面与依赖方向的静态边界。

adapters 只仿形制不 import：不得 import ``ordessa_harness`` 包码（合同词汇
只从 ``ordessa_harness_api``）、不得 import model-provider / permissions /
sandbox 域、不得 import server/pacthold 实现。
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ordessa_lsp_adapters"

FORBIDDEN_IMPORTS = (
    "import ordessa_harness\n",
    "import ordessa_harness.",
    "from ordessa_harness ",       # 但 ordessa_harness_api 合法
    "from ordessa_harness.",
    "import ordessa_model_provider",
    "from ordessa_model_provider",
    "import ordessa_permissions",
    "from ordessa_permissions",
    "import ordessa_sandbox",
    "from ordessa_sandbox",
    "import ordessa_server",
    "from ordessa_server",
    "import pacthold",
    "from pacthold",
)


def test_no_forbidden_imports() -> None:
    offenders: list[str] = []
    for pyfile in sorted(SRC.rglob("*.py")):
        text = pyfile.read_text(encoding="utf-8")
        for line in text.splitlines(keepends=True):
            stripped = line.lstrip()
            for needle in FORBIDDEN_IMPORTS:
                if stripped.startswith(needle.rstrip("\n")) and \
                        not stripped.startswith("from ordessa_harness_api") and \
                        not stripped.startswith("import ordessa_harness_api"):
                    offenders.append(f"{pyfile.name}: {stripped.strip()}")
    assert offenders == []


def test_only_published_contract_dists_imported() -> None:
    allowed = {
        "ordessa_lsp_api", "ordessa_harness_api", "server_plugin_api",
    }
    for pyfile in sorted(SRC.rglob("*.py")):
        for line in pyfile.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("from ", "import ")) and "ordessa" in stripped:
                root = stripped.split()[1].split(".")[0].rstrip(",")
                assert root in allowed, f"{pyfile.name}: unexpected dist {root!r}"
