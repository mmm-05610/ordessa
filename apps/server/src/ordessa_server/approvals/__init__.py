"""Compatibility alias — the implementation moved to `ordessa_server_compat.approvals`
(core-cleanup stage 3).

M1-P-A① alias discipline: submodules are pre-registered in `sys.modules`
before this package name is replaced, so both names resolve to the **same**
module objects and no file ever executes twice.
"""
import sys as _sys

import ordessa_server_compat.approvals as _implementation
from ordessa_server_compat.approvals import records as _records
_sys.modules[__name__ + ".records"] = _records

_sys.modules[__name__] = _implementation
