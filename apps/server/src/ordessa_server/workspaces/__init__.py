"""Compatibility alias — the implementation moved to `ordessa_workspace` (core-cleanup stage 3).

Three-line shims, M1-P-A① alias discipline: submodules are pre-registered in
`sys.modules` before this package name is replaced, so both names resolve to
the **same** module objects and no file ever executes twice.
"""
import sys as _sys

import ordessa_workspace as _implementation
from ordessa_workspace import git_status as _git_status
from ordessa_workspace import local_environment as _local_environment
from ordessa_workspace import records as _records
from ordessa_workspace import service as _service

_sys.modules[__name__ + ".git_status"] = _git_status
_sys.modules[__name__ + ".local_environment"] = _local_environment
_sys.modules[__name__ + ".records"] = _records
_sys.modules[__name__ + ".repository"] = _records
_sys.modules[__name__ + ".service"] = _service
_sys.modules[__name__] = _implementation
