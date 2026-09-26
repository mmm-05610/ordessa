"""Compatibility alias — the implementation moved to `ordessa_server_compat.model_configs`
(core-cleanup stage 3).

M1-P-A① alias discipline: submodules are pre-registered in `sys.modules`
before this package name is replaced, so both names resolve to the **same**
module objects and no file ever executes twice.
"""
import sys as _sys

import ordessa_server_compat.model_configs as _implementation
from ordessa_server_compat.model_configs import probe as _probe
from ordessa_server_compat.model_configs import provider_protocols as _provider_protocols
from ordessa_server_compat.model_configs import reasoning_knobs as _reasoning_knobs
from ordessa_server_compat.model_configs import repository as _repository
from ordessa_server_compat.model_configs import service as _service
_sys.modules[__name__ + ".probe"] = _probe
_sys.modules[__name__ + ".provider_protocols"] = _provider_protocols
_sys.modules[__name__ + ".reasoning_knobs"] = _reasoning_knobs
_sys.modules[__name__ + ".repository"] = _repository
_sys.modules[__name__ + ".service"] = _service

_sys.modules[__name__] = _implementation
