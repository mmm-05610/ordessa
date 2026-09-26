"""Compatibility alias — the implementation moved to `ordessa_server_compat.assets`
(core-cleanup stage 3).

M1-P-A① alias discipline: submodules are pre-registered in `sys.modules`
before this package name is replaced, so both names resolve to the **same**
module objects and no file ever executes twice.
"""
import sys as _sys

import ordessa_server_compat.assets as _implementation
from ordessa_server_compat.assets import catalog as _catalog
from ordessa_server_compat.assets import mcp as _mcp
from ordessa_server_compat.assets import mcp_probe as _mcp_probe
from ordessa_server_compat.assets import plugins as _plugins
from ordessa_server_compat.assets import records as _records
from ordessa_server_compat.assets import rendering as _rendering
from ordessa_server_compat.assets import skills as _skills
_sys.modules[__name__ + ".catalog"] = _catalog
_sys.modules[__name__ + ".mcp"] = _mcp
_sys.modules[__name__ + ".mcp_probe"] = _mcp_probe
_sys.modules[__name__ + ".plugins"] = _plugins
_sys.modules[__name__ + ".records"] = _records
_sys.modules[__name__ + ".rendering"] = _rendering
_sys.modules[__name__ + ".skills"] = _skills

_sys.modules[__name__] = _implementation
