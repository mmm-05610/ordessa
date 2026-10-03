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


_ALLOWED_ROOTS = {"ordessa_lsp_api", "ordessa_harness_api",
                  "server_plugin_api", "pytest"}


def _import_roots(pyfile: Path) -> list[str]:
    import ast
    roots: list[str] = []
    for node in ast.walk(ast.parse(pyfile.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.append(node.module.split(".")[0])
    return roots


def test_only_published_contract_dists_and_stdlib_imported() -> None:
    # 全量 AST 扫描：第三方根只许三个已发布合同 dist（+pytest）；
    # 其余必须是标准库（sys.stdlib_module_names 是权威清单）。
    import sys
    offenders: list[str] = []
    for pyfile in sorted(SRC.rglob("*.py")):
        for root in _import_roots(pyfile):
            if root in _ALLOWED_ROOTS or root in sys.stdlib_module_names:
                continue
            offenders.append(f"{pyfile.name}: {root}")
    assert offenders == []
