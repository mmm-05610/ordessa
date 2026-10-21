"""Cross-boundary controlled-application data: runtime snapshot and native readback.

These frozen values are the request/observation shape crossing the mechanism
boundary. Defining them reads no file, opens no connection and issues no
authority. The merge authority and native receipt are named through
contract-owned structural views (``contracts.ports``), never the mechanism's
concrete types, so there is no runtime or typing dependency on configuration or
records.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ordessa_agents.harness.definitions import AdapterContext, ApplicationTarget

from ordessa_agents.harness.contracts.ports.configuration import ConfigurationAuthorityView
from ordessa_agents.harness.contracts.ports.records import NativeActivationReceiptView


@dataclass(frozen=True)
class RuntimeSnapshot:
    target: ApplicationTarget
    context: AdapterContext
    authority: ConfigurationAuthorityView
    files: Mapping[tuple[str, ...], bytes]
    content: Mapping[str, bytes]
    private_root: Path
    before_value: object
    before_revision: str
    native_version_ref: str
    provider_generation: int
    authorization_revision: str
    secret_ref_revision: str


@dataclass(frozen=True)
class NativeReadback:
    target: ApplicationTarget
    native_session_identity: str
    applied_revision: str
    observed_value: object
    files: tuple[tuple[tuple[str, ...], str], ...]
    evidence_ref: str
    resource_changes: tuple[str, ...]
    receipt: NativeActivationReceiptView | None = None
