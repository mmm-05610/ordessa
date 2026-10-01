"""Harness-owned live facts, never populated by a resource plugin request."""
from dataclasses import dataclass
from ordessa_harness_api import AdapterContext
from ...server_acp.profile_owner import ProfileConfigurationSnapshot


@dataclass(frozen=True)
class NativeLiveModelContext(AdapterContext):
    native_snapshot: ProfileConfigurationSnapshot
