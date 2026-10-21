"""Public, dependency-free contract for the host-owned ACP admission port.

The channel plugin supplies identities from its owned registry. The host port
answers whether a particular submission or permission answer may cross the
transport. These values carry no permit, secret, raw transport, or principal
chosen by a renderer. The implementing product verifies those facts itself.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Protocol


ACP_ADMISSION_PORT = "acp.admission.gate"
ACP_ADMISSION_PORT_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _identity(name: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"ACP {name} must be a non-empty string")


@dataclass(frozen=True)
class AcpChannelBinding:
    """Host/owner observed channel identity, never a renderer assertion."""

    connection_id: str
    execution_id: str
    ledger_session_id: str
    harness_id: str
    workspace_id: str
    native_session_id: str | None = None
    runtime_generation: int | None = None

    def __post_init__(self) -> None:
        for name in ("connection_id", "execution_id", "ledger_session_id", "harness_id", "workspace_id"):
            _identity(name, getattr(self, name))
        if self.native_session_id is not None:
            _identity("native_session_id", self.native_session_id)
        if self.runtime_generation is not None and (
                type(self.runtime_generation) is not int or self.runtime_generation < 0):
            raise ValueError("ACP runtime_generation must be a non-negative integer when observed")


@dataclass(frozen=True)
class AcpAttachmentReference:
    """One content-service issued attachment reference, not its local bytes."""

    name: str
    uri: str
    sha256: str
    mime_type: str | None = None

    def __post_init__(self) -> None:
        _identity("attachment name", self.name)
        _identity("attachment uri", self.uri)
        if not isinstance(self.sha256, str) or _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("ACP attachment sha256 must be lowercase hex")
        if self.mime_type is not None:
            _identity("attachment mime_type", self.mime_type)


@dataclass(frozen=True)
class AcpSubmissionRequest:
    """One immutable next-submit snapshot for the same owned ACP channel."""

    submission_id: str
    native_session_id: str
    text: str
    attachments: tuple[AcpAttachmentReference, ...]
    configuration_digest: str
    command_id: str | None = None

    def __post_init__(self) -> None:
        _identity("submission_id", self.submission_id)
        _identity("native_session_id", self.native_session_id)
        if not isinstance(self.text, str):
            raise ValueError("ACP submission text must be a string")
        if not isinstance(self.attachments, tuple) or any(
                not isinstance(item, AcpAttachmentReference) for item in self.attachments):
            raise ValueError("ACP attachments must be an immutable tuple of references")
        if (not isinstance(self.configuration_digest, str)
                or _SHA256.fullmatch(self.configuration_digest) is None):
            raise ValueError("ACP configuration_digest must be lowercase sha256")
        if self.command_id is not None:
            _identity("command_id", self.command_id)


@dataclass(frozen=True)
class AcpPermissionDecision:
    """Exact answer identity; the port checks it against the observed request."""

    native_session_id: str
    interaction_id: str
    run_id: str
    option_id: str

    def __post_init__(self) -> None:
        for name in ("native_session_id", "interaction_id", "run_id", "option_id"):
            _identity(name, getattr(self, name))


@dataclass(frozen=True)
class AcpAdmissionResult:
    """Accepted, refused, or Unknown; the three shapes cannot overlap."""

    kind: Literal["accepted", "refused", "unknown"]
    submission_id: str | None = None
    code: str | None = None
    operation_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "accepted":
            _identity("accepted submission_id", self.submission_id)
            if any(value is not None for value in (self.code, self.operation_id, self.reason)):
                raise ValueError("ACP accepted admission carries only submission_id")
        elif self.kind == "refused":
            _identity("refusal code", self.code)
            _identity("refusal reason", self.reason)
            if self.submission_id is not None or self.operation_id is not None:
                raise ValueError("ACP refused admission carries only code and reason")
        elif self.kind == "unknown":
            _identity("unknown operation_id", self.operation_id)
            _identity("unknown reason", self.reason)
            if self.submission_id is not None or self.code is not None:
                raise ValueError("ACP Unknown admission carries only operation_id and reason")
        else:
            raise ValueError("ACP admission kind is invalid")


class AcpAdmissionPort(Protocol):
    """The `ServerPluginContext.ports[ACP_ADMISSION_PORT]` surface.

    This is deliberately not runtime-checkable: method names alone cannot
    distinguish a host-internal gate that accepts Mapping/dict values from a
    compatible public DTO adapter. Composition must install an explicit
    adapter, then exercise the typed return contract.

    Absence is a refusal. A binding's optional native session or generation
    fields remain None until an authoritative source observed them. An
    implementation must resolve any missing evidence itself or refuse; it
    must bind the request to the selected principal, live channel, runtime
    generation and one-use permit. This structural protocol alone grants no
    authority. The owner converts camelCase wire members to these named DTO
    fields before invoking the port; the DTO is never sent to the renderer.

    Version 1 describes this DTO/result shape. `ready` is separate: it is
    true only while a product authority and authoritative native-session and
    generation evidence are configured. A matching version alone is never
    evidence that submission is available.
    """

    @property
    def public_acp_admission_port_version(self) -> Literal[1]: ...

    @property
    def ready(self) -> bool: ...

    def authorize_submission(self, binding: AcpChannelBinding,
                             submission: AcpSubmissionRequest) -> AcpAdmissionResult: ...

    def authorize_permission(self, binding: AcpChannelBinding,
                             decision: AcpPermissionDecision) -> AcpAdmissionResult: ...
