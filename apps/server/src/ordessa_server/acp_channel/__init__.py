"""Compatibility alias — the implementation moved to `ordessa_harness.server_acp`
(core-cleanup stage 3).

M1-P-A① alias discipline: submodules are pre-registered in `sys.modules`
before this package name is replaced, so both names resolve to the **same**
module objects and no file ever executes twice.
"""
import sys as _sys

import ordessa_harness.server_acp as _implementation
from ordessa_harness.server_acp import access_entry as _access_entry
from ordessa_harness.server_acp import registry as _registry
from ordessa_harness.server_acp import runs as _runs
from ordessa_harness.server_acp import transport as _transport

_sys.modules[__name__ + ".access_entry"] = _access_entry
_sys.modules[__name__ + ".registry"] = _registry
_sys.modules[__name__ + ".runs"] = _runs
_sys.modules[__name__ + ".transport"] = _transport
_sys.modules[__name__] = _implementation
