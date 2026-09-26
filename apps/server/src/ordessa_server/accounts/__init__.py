"""Compatibility alias — the implementation moved to `ordessa_server_compat.accounts`
(core-cleanup stage 3).

M1-P-A① alias discipline: submodules are pre-registered in `sys.modules`
before this package name is replaced, so both names resolve to the **same**
module objects and no file ever executes twice.
"""
import sys as _sys

import ordessa_server_compat.accounts as _implementation
from ordessa_server_compat.accounts import assets as _assets
from ordessa_server_compat.accounts import login_engine as _login_engine
from ordessa_server_compat.accounts import records as _records
_sys.modules[__name__ + ".assets"] = _assets
_sys.modules[__name__ + ".login_engine"] = _login_engine
_sys.modules[__name__ + ".records"] = _records

_sys.modules[__name__] = _implementation
