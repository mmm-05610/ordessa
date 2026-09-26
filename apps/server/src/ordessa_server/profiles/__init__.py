"""Compatibility alias — the implementation moved to `ordessa_server_compat.profiles`
(core-cleanup stage 3).

M1-P-A① alias discipline: submodules are pre-registered in `sys.modules`
before this package name is replaced, so both names resolve to the **same**
module objects and no file ever executes twice.
"""
import sys as _sys

import ordessa_server_compat.profiles as _implementation
from ordessa_server_compat.profiles import clone as _clone
from ordessa_server_compat.profiles import memory as _memory
from ordessa_server_compat.profiles import permissions as _permissions
from ordessa_server_compat.profiles import posture_config as _posture_config
from ordessa_server_compat.profiles import posture_translation as _posture_translation
from ordessa_server_compat.profiles import repository as _repository
from ordessa_server_compat.profiles import service as _service
from ordessa_server_compat.profiles import subagents as _subagents
_sys.modules[__name__ + ".clone"] = _clone
_sys.modules[__name__ + ".memory"] = _memory
_sys.modules[__name__ + ".permissions"] = _permissions
_sys.modules[__name__ + ".posture_config"] = _posture_config
_sys.modules[__name__ + ".posture_translation"] = _posture_translation
_sys.modules[__name__ + ".repository"] = _repository
_sys.modules[__name__ + ".service"] = _service
_sys.modules[__name__ + ".subagents"] = _subagents

_sys.modules[__name__] = _implementation
