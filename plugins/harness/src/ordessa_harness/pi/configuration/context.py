"""Harness-internal C2 context, populated only by native owner readback.

Resource plugins never supply this object or its native facts. The public C2
context remains unchanged; the brand implementation and runtime share it.
"""
from dataclasses import dataclass
from ordessa_harness_api import AdapterContext
from ...server_acp.profile_owner import ProfileConfigurationSnapshot


@dataclass(frozen=True)
class PiLiveModelContext(AdapterContext):
    native_snapshot: ProfileConfigurationSnapshot
