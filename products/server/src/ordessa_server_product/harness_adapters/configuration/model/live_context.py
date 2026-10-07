"""Harness-owned live facts, never populated by a resource plugin request."""
from dataclasses import dataclass
from pacthold.harness_contracts import AdapterContext
from ....acp_channel.profile_owner import ProfileConfigurationSnapshot


@dataclass(frozen=True)
class NativeLiveModelContext(AdapterContext):
    native_snapshot: ProfileConfigurationSnapshot
    credential_binding: object = None
