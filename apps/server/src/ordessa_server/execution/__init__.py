"""Compatibility alias — the implementation moved to `ordessa_server_compat.execution`
(core-cleanup stage 3).

M1-P-A① alias discipline: submodules are pre-registered in `sys.modules`
before this package name is replaced, so both names resolve to the **same**
module objects and no file ever executes twice.
"""
import sys as _sys

import ordessa_server_compat.execution as _implementation
from ordessa_server_compat.execution import artifact_store as _artifact_store
from ordessa_server_compat.execution import change_set as _change_set
from ordessa_server_compat.execution import control_plane_sync as _control_plane_sync
from ordessa_server_compat.execution import delegation as _delegation
from ordessa_server_compat.execution import execution_contract as _execution_contract
from ordessa_server_compat.execution import first_run_lock as _first_run_lock
from ordessa_server_compat.execution import inventory as _inventory
from ordessa_server_compat.execution import local_channel as _local_channel
from ordessa_server_compat.execution import placement as _placement
from ordessa_server_compat.execution import protocols as _protocols
from ordessa_server_compat.execution import session_store_guard as _session_store_guard
from ordessa_server_compat.execution import sidecar as _sidecar
from ordessa_server_compat.execution import sidecar_backend as _sidecar_backend
from ordessa_server_compat.execution import state_capture as _state_capture
from ordessa_server_compat.execution import usage as _usage

_sys.modules[__name__ + ".artifact_store"] = _artifact_store
_sys.modules[__name__ + ".change_set"] = _change_set
_sys.modules[__name__ + ".control_plane_sync"] = _control_plane_sync
_sys.modules[__name__ + ".delegation"] = _delegation
_sys.modules[__name__ + ".execution_contract"] = _execution_contract
_sys.modules[__name__ + ".first_run_lock"] = _first_run_lock
_sys.modules[__name__ + ".inventory"] = _inventory
_sys.modules[__name__ + ".local_channel"] = _local_channel
_sys.modules[__name__ + ".placement"] = _placement
_sys.modules[__name__ + ".protocols"] = _protocols
_sys.modules[__name__ + ".session_store_guard"] = _session_store_guard
_sys.modules[__name__ + ".sidecar"] = _sidecar
_sys.modules[__name__ + ".sidecar_backend"] = _sidecar_backend
_sys.modules[__name__ + ".state_capture"] = _state_capture
_sys.modules[__name__ + ".usage"] = _usage

_sys.modules[__name__] = _implementation
