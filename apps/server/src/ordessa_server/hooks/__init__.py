"""Compatibility alias — the implementation moved to `ordessa_server_compat.hooks`
(core-cleanup stage 3).

M1-P-A① alias discipline: submodules are pre-registered in `sys.modules`
before this package name is replaced, so both names resolve to the **same**
module objects and no file ever executes twice.
"""
import sys as _sys

import ordessa_server_compat.hooks as _implementation
from ordessa_server_compat.hooks import model as _model
from ordessa_server_compat.hooks import records as _records
from ordessa_server_compat.hooks import rendering as _rendering
from ordessa_server_compat.hooks import triggers as _triggers
_sys.modules[__name__ + ".model"] = _model
_sys.modules[__name__ + ".records"] = _records
_sys.modules[__name__ + ".rendering"] = _rendering
_sys.modules[__name__ + ".triggers"] = _triggers

_sys.modules[__name__] = _implementation
