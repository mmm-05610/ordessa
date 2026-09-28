from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1, PromptFragmentV1, WorkspaceV1
from pacthold.work_core import ExecutionProjection, ExecutionStartReceipt, ExecutionStartRequest, Freshness, Outcome, Phase, ProviderDescriptor, Ref, RefType
from pacthold_runtime_compat.runtime_composition import (
    HarnessCommandSpec, RuntimeBinding,
    RuntimeHostV1, SandboxV1, TerminalSessionV1, declare_source,
)

from .profiles import OpenCodeProfileAuthority, OpenCodeProfileRef

OpenCodeProfileV1 = AgentBoxProfileV1
from .projection import OpenCodeProjector, ProfileRuntimeSource, ExecutableRuntimeSource, HelperRuntimeSource


class OpenCodeProfileV1:
    contract_id = "agent-box.opencode-profile@1"

    def __init__(self, profile_id: str, revision: int, digest_value: str):
        self.profile_id, self.revision, self.digest = profile_id, revision, digest_value


@dataclass(frozen=True)
class OpenCodeContinuationV1:
    contract_id = "agent-box.opencode-continuation@1"
    session_id: str
    project_id: str = ""

    def __post_init__(self) -> None:
        if not self.session_id or any(c in self.session_id for c in "\0\n\r"):
            raise ValueError("OpenCode continuation session_id is required")


@dataclass
class OpenCodeHandle:
    execution_id: str
    dispatch_id: str
    workspace: WorkspaceV1
    profile_ref: OpenCodeProfileRef
    projection: Any
    runtime_handle: Any
    session_id: str
    submitted: bool = False
    outcome: Outcome | None = None
    output: str = ""
    output_ref: Ref | None = None

    @property
    def provider_correlation_ref(self) -> str:
        return self.session_id


@dataclass(frozen=True)
class OpenCodeObservation:
    projection: ExecutionProjection
    native_refs: tuple[Ref, ...]
    output_refs: tuple[Ref, ...]
    projected_contracts: tuple[str, ...]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


def _now():
    return datetime.now(timezone.utc)


class OpenCodeExecutionProvider:
    """OpenCode direct execution provider; the coordinator owns composition."""

    provider_id = "opencode-direct"
    def get_handle(self, dispatch_id): return self._handles[dispatch_id]

    def __init__(self, root: Path, *, authority: OpenCodeProfileAuthority | None = None,
                 executable: str | Path = "opencode", coordinator: Any | None = None,
                 runtime_binding: RuntimeBinding | None = None):
        self.root = Path(root).resolve()
        self.authority = authority or OpenCodeProfileAuthority(self.root / "profiles")
        self.projector = OpenCodeProjector(self.root / "projections", self.authority)
        self.executable = str(executable)
        self.coordinator, self.runtime_binding = coordinator, runtime_binding
        self._handles: dict[str, OpenCodeHandle] = {}

    def descriptor(self):
        return ProviderDescriptor(self.provider_id, "OpenCode direct", "0.1.0")

    def capabilities(self):
        return {"start": "supported", "observe": "supported", "finish": "explicit", "direct": "supported", "continuation": "supported-as-new-execution", "output-capture": "supported"}

    def input_limits(self):
        return {WorkspaceV1.contract_id: (1, 1), AgentBoxProfileV1.contract_id: (1, 1), PromptFragmentV1.contract_id: (1, None), OpenCodeContinuationV1.contract_id: (0, 1), RuntimeHostV1.contract_id: (1, 1), SandboxV1.contract_id: (1, 1), TerminalSessionV1.contract_id: (1, 1)}

    @staticmethod
    def _one(request, contract):
        values = request.inputs.get(contract, ())
        if len(values) != 1:
            raise ValueError(f"expected one {contract}, got {len(values)}")
        return values[0]

    def _profile_ref(self, request) -> OpenCodeProfileRef:
        item = next(i for i in request.resolved_inputs if i.contract_id == OpenCodeProfileV1.contract_id)
        value = item.value
        if not isinstance(value, OpenCodeProfileV1) or item.ref.provider != "harness-profile" or item.ref.metadata.get("harness_type") != "opencode":
            raise TypeError("resolved input is not an exact OpenCode Profile")
        ref = OpenCodeProfileRef(value.profile_id, value.revision, value.digest)
        if item.ref.metadata.get("revision") != str(ref.revision) or item.ref.metadata.get("digest") != ref.digest:
            raise ValueError("OpenCode ProfileRef is not exact")
        self.authority.resolve(ref)
        return ref

    def _compose(self, request, command, workspace: WorkspaceV1):
        from pacthold_runtime_compat.runtime_composition import assemble_runtime_composition
        if self.coordinator is not None and self.runtime_binding is not None:
            return self.coordinator.start(self.runtime_binding, command, execution_id=request.execution_id, dispatch_id=request.dispatch_id)
        binding, coordinator = assemble_runtime_composition(request, command)
        return coordinator.start(binding, command, execution_id=request.execution_id, dispatch_id=request.dispatch_id)

    def start(self, request: ExecutionStartRequest) -> ExecutionStartReceipt:
        workspace = self._one(request, WorkspaceV1.contract_id)
        if not isinstance(workspace, WorkspaceV1): raise TypeError("workspace input mismatch")
        profile_ref = self._profile_ref(request)
        continuation = next(iter(request.inputs.get(OpenCodeContinuationV1.contract_id, ())), None)
        projection = self.projector.materialize(request.execution_id, profile_ref)
        fragments = request.inputs.get(PromptFragmentV1.contract_id, ())
        prompt = "\n\n".join(getattr(f, "content", "") for f in fragments).strip()
        if not prompt: raise ValueError("OpenCode requires prompt content")
        # The OpenCode projector owns the guest layout: workspace, native
        # config home, executable and helper file are declared as typed
        # sources; only their guest slots cross the sandbox boundary.
        argv = ("/runtime/bin/opencode", "run", "--format", "json")
        if continuation is not None: argv += ("--session", continuation.session_id)
        argv += (prompt,)
        helper = projection.directory / "helper-target-slot.json"
        helper.write_text(json.dumps({"kind": "opencode-helper", "execution_id": request.execution_id}), encoding="utf-8")
        sources = (
            declare_source("workspace", workspace.path, "/workspace", access="rw", provenance="workspace"),
            declare_source("profile", projection.directory, "/runtime/home", access="rw", provenance="profile"),
            declare_source("executable", self.executable, "/runtime/bin/opencode", access="ro", provenance="executable"),
            declare_source("helper", helper, "/runtime/helpers/helper-target-slot.json", access="ro", provenance="helper"),
        )
        command = HarnessCommandSpec(argv, "/workspace", {"OPENCODE_CONFIG_DIR": "/runtime/home", "AGENT_BOX_EXECUTION_ID": request.execution_id}, "pty" if continuation else "stdio", runtime_sources=sources, projector_id="opencode")
        runtime = self._compose(request, command, workspace)
        handle = OpenCodeHandle(request.execution_id, request.dispatch_id, workspace, profile_ref, projection, runtime, continuation.session_id if continuation else request.dispatch_id)
        self._handles[request.dispatch_id] = handle
        return ExecutionStartReceipt(request.execution_id, request.dispatch_id, request.inputs_digest, correlation_ref=Ref(RefType.SESSION, self.provider_id, request.dispatch_id, uri=f"opencode://session/{handle.session_id}"), runtime_handle=handle)

    def observe(self, native_ref) -> OpenCodeObservation:
        handle = native_ref.runtime_handle if isinstance(native_ref, ExecutionStartReceipt) else (self._handles[native_ref] if isinstance(native_ref, str) else native_ref)
        process = getattr(handle.runtime_handle.transport, "process", handle.runtime_handle.transport)
        alive = process.poll() is None if hasattr(process, "poll") else True
        outputs = (handle.output_ref,) if handle.output_ref else ()
        phase = Phase.TERMINAL if handle.submitted else (Phase.ACTIVE if alive else Phase.UNKNOWN)
        return OpenCodeObservation(ExecutionProjection(phase, handle.outcome, not handle.submitted, Freshness.OBSERVED, _now()), (Ref(RefType.SESSION, self.provider_id, handle.session_id, uri=f"opencode://session/{handle.session_id}"),), outputs, (OpenCodeProfileV1.contract_id,), {"profile_ref": handle.profile_ref.digest, "terminal_correlation": handle.runtime_handle.native_correlation, "credential_locator": handle.projection.credential_locator, "credential_values_materialized": False})

    def finish(self, handle, **kwargs):
        handle = handle.runtime_handle if isinstance(handle, ExecutionStartReceipt) else handle
        if not handle.submitted:
            process = getattr(handle.runtime_handle.transport, "process", handle.runtime_handle.transport)
            if hasattr(process, "wait"):
                try: handle.output, _ = process.communicate(timeout=float(kwargs.get("timeout", 10)))
                except Exception:
                    if process.poll() is None: process.terminate()
                    handle.output, _ = process.communicate()
            handle.outcome = Outcome.SUCCEEDED if getattr(process, "returncode", 0) == 0 else Outcome.FAILED
            handle.submitted = True
            for line in handle.output.splitlines():
                if line.startswith("OPENCODE_SESSION="):
                    handle.session_id = line.split("=", 1)[1].strip() or handle.session_id
                    break
            if handle.output:
                out = handle.projection.directory / "output.txt"; out.write_text(handle.output, encoding="utf-8")
                handle.output_ref = Ref(RefType.ARTIFACT, self.provider_id, "sha256:" + hashlib.sha256(handle.output.encode()).hexdigest(), uri=out.as_uri(), metadata={"kind": "execution-output"})
            if self.coordinator is not None: self.coordinator.cleanup(handle.runtime_handle.attempt_key)
        return self.observe(handle)
