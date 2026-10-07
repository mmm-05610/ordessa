"""016 红线 — 写入面与依赖方向的静态边界。

adapters 只仿形制不 import：不得 import ``pacthold.harness_kit`` 包码（合同词汇
只从 ``pacthold.harness_contracts``）、不得 import model-provider / permissions /
sandbox 域、不得 import server/pacthold 实现。
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ordessa_lsp_adapters"

FORBIDDEN_IMPORTS = (
    "import pacthold.harness_kit\n",
    "import pacthold.harness_kit.",
    "from pacthold.harness_kit ",       # 但 pacthold.harness_contracts 合法
    "from pacthold.harness_kit.",
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
                        not stripped.startswith("from pacthold.harness_contracts") and \
                        not stripped.startswith("import pacthold.harness_contracts"):
                    offenders.append(f"{pyfile.name}: {stripped.strip()}")
    assert offenders == []


_ALLOWED_ROOTS = {"ordessa_lsp_api", "pacthold.harness_contracts",
                  "server_plugin_api", "pytest"}


def _import_roots(pyfile: Path) -> list[str]:
    """Absolute imported modules, keeping enough dotted detail that a grant
    under a forbidden top-level root (pacthold.harness_contracts) can be told
    apart from the bare root."""
    import ast
    roots: list[str] = []
    for node in ast.walk(ast.parse(pyfile.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.append(node.module)
    return roots


def test_only_published_contract_dists_and_stdlib_imported() -> None:
    # 全量 AST 扫描：第三方根只许三个已发布合同 dist（+pytest）；
    # 其余必须是标准库（sys.stdlib_module_names 是权威清单）。
    import sys
    offenders: list[str] = []
    for pyfile in sorted(SRC.rglob("*.py")):
        for module in _import_roots(pyfile):
            top = module.split(".")[0]
            if top in sys.stdlib_module_names:
                continue
            granted = any(module == g or module.startswith(g + ".") or g.startswith(module + ".")
                          for g in _ALLOWED_ROOTS if "." in g)
            if granted or top in _ALLOWED_ROOTS:
                continue
            offenders.append(f"{pyfile.name}: {module}")
    assert offenders == []
