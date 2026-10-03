"""Make the package sources importable without an editable install.

The test session runs from the repository root against
`plugins/assets/skills/tests`. In the in-tree verification venv none of
these distributions are pip-installed, so this pin adds repo `src/` roots
for THIS package plus the runtime-compat assembly (`plugins/runtime-compat`
— the product storage facade `Database`/`PRODUCT_SCHEMA_VERSION` and the
runtime-artifact digest moved out of `pacthold` here at specs/010 T009,
see docs/architecture.md 组件表), the profile-api publisher
(`plugins/profile`) and the permissions-api publisher
(`plugins/permissions/api` + its backend store `plugins/permissions/backend`). Since the package-isolation run (G21) installs the
real wheels into a fresh venv, each repo path is added ONLY when the
matching module is not already importable — an installed `ordessa_skills`
(etc.) always wins from site-packages. Only paths are added; nothing here
reorders or replaces already-importable packages, and an upstream import
that is broken stays broken and is reported, not patched.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[2]

for _module, _root in (("ordessa_skills", PLUGIN_ROOT / "src"),
                       ("pacthold_runtime_compat",
                        REPO_ROOT / "plugins" / "runtime-compat" / "src"),
                       ("ordessa_profile",
                        REPO_ROOT / "plugins" / "profile" / "src"),
                       # the permissions-api checkpoint (`bcd4387bec`):
                       # `ordessa_skills.mandatory_policy` binds to the
                       # published PUBLIC API package, and the tests drive it
                       # through the published backend store (PolicyRepository
                       # / Authorizer) so the mandatory layer is proven
                       # against the real surface, not a Q1 stand-in.
                       ("ordessa_permissions_api",
                        REPO_ROOT / "plugins" / "permissions" / "api" / "src"),
                       ("ordessa_permissions_backend",
                        REPO_ROOT / "plugins" / "permissions" / "backend" / "src")):
    if (importlib.util.find_spec(_module) is None
            and _root.is_dir() and str(_root) not in sys.path):
        sys.path.append(str(_root))
