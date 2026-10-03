"""T011 evidence-two runner: import *every* pacthold module in a bare venv.

Runs under venv #2 which holds ONLY the pacthold wheel + pytest (no
``pacthold_runtime_compat``, no ordessa_* distributions — see
``/tmp/a-t011-installed.txt``).  Walks ``pkgutil.walk_packages`` over the
installed ``pacthold`` package, imports each module one by one and prints a
per-module OK/FAIL table.

Counterexample guard: after the walk, the script asserts that importing
``pacthold_runtime_compat`` raises ``ModuleNotFoundError`` — the business
distribution is genuinely absent, so any core module that secretly depended
on it would already have shown up as a FAIL above.

Exit code: 0 only when every module imports AND the compat import is absent.
Usage:  <venv2-python> import_scan.py   (stdout is tee'd to
/tmp/a-t011-imports.txt by the runner shell)
"""
from __future__ import annotations

import importlib
import pkgutil
import sys
import traceback


def main() -> int:
    import pacthold

    print(f"pacthold package origin: {pacthold.__file__}")
    names = [pacthold.__name__]
    names += [info.name for info in pkgutil.walk_packages(pacthold.__path__, prefix="pacthold.")]
    names = sorted(set(names))

    failures = 0
    for name in names:
        try:
            importlib.import_module(name)
            print(f"OK   {name}")
        except BaseException:  # noqa: BLE001 - report, never hide
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc(file=sys.stdout)

    print(f"\nmodules walked: {len(names)}  failures: {failures}")

    # Counterexample guard: the business distribution must be absent here.
    compat_absent = False
    try:
        importlib.import_module("pacthold_runtime_compat")
    except ModuleNotFoundError as exc:
        compat_absent = True
        print(f"ABSENT-GUARD OK  pacthold_runtime_compat -> ModuleNotFoundError: {exc}")
    except BaseException as exc:  # noqa: BLE001
        print(f"ABSENT-GUARD FAIL  pacthold_runtime_compat raised {type(exc).__name__}, not ModuleNotFoundError")
    else:
        print("ABSENT-GUARD FAIL  pacthold_runtime_compat is importable — environment is NOT bare")

    ok = failures == 0 and compat_absent
    print(f"VERDICT: {'GREEN' if ok else 'RED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
