"""Interactive Codex App Server ExecutionProvider for the Preview path."""
from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from pacthold_runtime_compat.resource_contracts import (
    AgentBoxProfileV1,
    CredentialRefV1,
    PromptFragmentV1,
    WorkspaceV1,
)
from pacthold.work_core import (
    ExecutionProjection,
    ExecutionStartReceipt,
    ExecutionStartRequest,
    Freshness,
    Outcome,
    Phase,
    ProviderDescriptor,
    Ref,
    RefType,
)

from ..contracts import CodexContinuationV1
from ..launch import CodexLaunchAdapter
from ..composition import command_from_plan, compose, composition_from_resolved_inputs
from pacthold_runtime_compat.runtime_composition import RuntimeBinding, TerminalRunHandle, RuntimeHostV1, SandboxV1, TerminalSessionV1, RuntimeCompositionCoordinator


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CodexAppServerClient:
    """Small JSON-RPC client over the App Server stdio transport."""

    def __init__(self, transport: Any, events_path: Path) -> None:
        self.events_path = events_path.resolve()
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.write_text("", encoding="utf-8")
        # The transport is supplied by the selected RuntimeComposition.  The
        # Harness never creates a process or opens a carrier.
        self.transport = transport
        self.process = getattr(transport, "process", transport)
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._condition = threading.Condition()
        self._next_id = 1
        self.events: list[dict[str, Any]] = []
        self.stderr: list[str] = []
        self.event_methods: list[str] = []
        self.error_codes: list[str] = []
        self.file_change_statuses: list[str] = []
        self.server_request_methods: list[str] = []
        self.approval_request_methods: list[str] = []
        self.process_exit: int | None = None
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _send(self, message: Mapping[str, Any]) -> None:
        encoded = json.dumps(message, separators=(",", ":")) + "\n"
        with self._write_lock:
            if not getattr(self.process, "stdin", None):
                raise RuntimeError("Codex App Server stdin is unavailable")
            self.process.stdin.write(encoded)
            self.process.stdin.flush()

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    def request(
        self, method: str, params: Mapping[str, Any], *, timeout: float = 60
    ) -> Any:
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            self._pending[request_id] = response_queue
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            }
        )
        try:
            response = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError(f"timed out waiting for {method}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if "error" in response:
            raise RuntimeError(f"{method} failed: {response['error']}")
        return response.get("result")

    def _read_stdout(self) -> None:
        assert self.process.stdout
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self.stderr.append(f"non-json stdout: {line.rstrip()}")
                continue
            safe_message = self._redact(message)
            with self.events_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(safe_message, separators=(",", ":")) + "\n")
            if isinstance(message.get("method"), str):
                self.event_methods.append(message["method"])
            if isinstance(message.get("error"), dict) and message["error"].get("code") is not None:
                self.error_codes.append(str(message["error"]["code"]))
            item = ((message.get("params") or {}).get("item") or {})
            if item.get("type") == "fileChange" and isinstance(item.get("status"), str):
                self.file_change_statuses.append(item["status"])
            request_id = message.get("id")
            if request_id is not None and "method" not in message:
                with self._pending_lock:
                    target = self._pending.get(request_id)
                if target is not None:
                    target.put(message)
                    continue
            if request_id is not None and "method" in message:
                self._answer_server_request(message)
                continue
            with self._condition:
                self.events.append(safe_message)
                self._condition.notify_all()

    @classmethod
    def _redact(cls, value: Any, key: str = "") -> Any:
        if key.lower() in {"text", "input", "output", "content", "diff", "developerinstructions"}:
            return "[redacted]"
        if isinstance(value, dict):
            return {str(k): cls._redact(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._redact(item, key) for item in value[:32]]
        if isinstance(value, str):
            return value[:256]
        return value

    def _read_stderr(self) -> None:
        assert self.process.stderr
        for line in self.process.stderr:
            self.stderr.append(line.rstrip())

    def _answer_server_request(self, message: Mapping[str, Any]) -> None:
        method = str(message.get("method") or "")
        self.server_request_methods.append(method)
        if "requestApproval" in method or "requestUserInput" in method:
            self.approval_request_methods.append(method)
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {"decision": "decline"},
                }
            )
            with self._condition:
                self._condition.notify_all()
        else:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {
                        "code": -32601,
                        "message": f"unsupported by Agent-Box Preview: {method}",
                    },
                }
            )

    def wait_turn_completed(self, turn_id: str, *, timeout: float = 300) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                for event in self.events:
                    if event.get("method") not in {"turn/completed", "turn/failed", "turn/aborted"}:
                        continue
                    params = event.get("params") or {}
                    turn = params.get("turn") or {}
                    if turn.get("id") == turn_id:
                        return params
                for event in self.events:
                    if event.get("method") == "error":
                        raise RuntimeError("Codex App Server reported a redacted error")
                if self.approval_request_methods:
                    raise RuntimeError("Codex App Server requested approval")
                if self.process.poll() is not None:
                    raise RuntimeError(
                        f"Codex App Server exited {self.process.returncode}: "
                        + " | ".join(self.stderr[-10:])
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"timed out waiting for turn {turn_id}")
                self._condition.wait(timeout=min(remaining, 1.0))

    def close(self) -> None:
        self.process_exit = self.process.poll()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except TimeoutError:
                self.process.kill()
                self.process.wait(timeout=10)
        self.process_exit = self.process.returncode

    def diagnostics(self, turn_ids: tuple[str, ...]) -> dict[str, Any]:
        statuses = []
        for event in self.events:
            if event.get("method") not in {"turn/completed", "turn/failed", "turn/aborted"}:
                continue
            turn = ((event.get("params") or {}).get("turn") or {})
            if turn.get("id") in turn_ids:
                statuses.append(str(turn.get("status") or "unknown"))
        limits = {
            "event_methods": tuple(self.event_methods[-64:]),
            "error_codes": tuple(self.error_codes[-16:]),
            "file_change_statuses": tuple(self.file_change_statuses[-16:]),
            "server_request_methods": tuple(self.server_request_methods[-16:]),
            "approval_request_methods": tuple(self.approval_request_methods[-16:]),
            "turn_terminal_statuses": tuple(statuses[-16:]),
            "process_exit": self.process_exit,
        }
        return limits


@dataclass
class CodexInteractiveHandle:
    execution_id: str
    dispatch_id: str
    inputs_digest: str
    workspace: WorkspaceV1
    guest_cwd: str
    profile: AgentBoxProfileV1
    client: CodexAppServerClient
    thread_id: str
    turn_ids: list[str]
    projected_contracts: tuple[str, ...]
    composition_handle: TerminalRunHandle | None = None
    submitted: bool = False
    turn_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Honest PROJECTED-level receipt captured from the composition attempt.
    projection: Mapping[str, Any] | None = None

    @property
    def provider_correlation_ref(self) -> str:
        return self.thread_id


@dataclass(frozen=True)
class CodexInteractiveObservation:
    projection: ExecutionProjection
    native_refs: tuple[Ref, ...]
    output_refs: tuple[Ref, ...]
    projected_contracts: tuple[str, ...]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class CodexInteractiveExecutionProvider:
    """One accountable interactive responsibility window over Codex App Server.

    Turn completion and process idleness do not terminate the Core Execution.
    Only :meth:`finish` changes the provider-owned submitted signal.
    """

    provider_id = "codex-app-server"

    def __init__(
        self,
        evidence_root: Path,
        *,
        launch_adapter: CodexLaunchAdapter,
        credential_materializer=None,
        coordinator: Any | None = None,
        runtime_binding: RuntimeBinding | None = None,
        client_factory: Any | None = None,
    ) -> None:
        self.evidence_root = evidence_root.resolve()
        self._launch_adapter = launch_adapter
        self._coordinator = coordinator
        self._runtime_binding = runtime_binding
        self._client_factory = client_factory or CodexAppServerClient
        self._handles: dict[str, CodexInteractiveHandle] = {}
        self._credential_materializer = credential_materializer

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(self.provider_id, "Codex App Server", "v2")

    def capabilities(self) -> Mapping[str, str]:
        return {
            "start": "supported",
            "observe": "supported",
            "continuation-input": "supported",
            "steer": "supported",
            "finish": "supported",
            "stream": "supported",
        }

    def input_limits(self) -> Mapping[str, tuple[int, int | None]]:
        limits = {
            WorkspaceV1.contract_id: (1, 1),
            PromptFragmentV1.contract_id: (1, None),
            AgentBoxProfileV1.contract_id: (1, 1),
            CodexContinuationV1.contract_id: (0, 1),
            CredentialRefV1.contract_id: (0, 1),
        }
        if self._coordinator is None:
            limits.update({RuntimeHostV1.contract_id: (1, 1), SandboxV1.contract_id: (1, 1), TerminalSessionV1.contract_id: (1, 1)})
        return limits

    @staticmethod
    def _one(request: ExecutionStartRequest, contract_id: str) -> object:
        values = request.inputs.get(contract_id, ())
        if len(values) != 1:
            raise ValueError(f"expected one {contract_id}, got {len(values)}")
        return values[0]

    def start(self, request: ExecutionStartRequest) -> ExecutionStartReceipt:
        if not isinstance(request, ExecutionStartRequest):
            raise TypeError("Codex interactive provider requires ExecutionStartRequest")
        workspace = self._one(request, WorkspaceV1.contract_id)
        profile = self._one(request, AgentBoxProfileV1.contract_id)
        if not isinstance(workspace, WorkspaceV1) or not isinstance(profile, AgentBoxProfileV1):
            raise TypeError("resolved workspace/profile contract type mismatch")
        if profile.agent_type != "codex":
            raise ValueError("Codex App Server requires an Agent-Box Codex profile")
        fragments = request.inputs.get(PromptFragmentV1.contract_id, ())
        prompt = "\n\n".join(
            f"# {fragment.title}\n\n{fragment.content}"
            for fragment in fragments
            if isinstance(fragment, PromptFragmentV1)
        )
        if not prompt:
            raise ValueError("Codex interactive provider requires prompt content")

        profile_ref = next(item.ref for item in request.resolved_inputs if item.contract_id == AgentBoxProfileV1.contract_id)
        plan = self._launch_adapter.plan_app_server(
            execution_id=request.execution_id,
            profile_ref=profile_ref,
            profile=profile,
            workspace=workspace,
        )
        command = command_from_plan(
            plan, execution_id=request.execution_id,
            io_mode="stdio",
            requires_control_plane_network=True,
        )
        # This is the only Harness-to-runtime launch edge.  In particular,
        # constructing the command above has no process or terminal effect.
        binding, coordinator = ((self._runtime_binding, self._coordinator)
                                if self._coordinator is not None else composition_from_resolved_inputs(request, command, credential_materializer=self._credential_materializer))
        run_handle = compose(
            coordinator, binding, command,
            execution_id=request.execution_id, dispatch_id=request.dispatch_id,
        )
        transport = getattr(run_handle, "transport", run_handle)
        client = self._client_factory(
            transport, self.evidence_root / f"{request.dispatch_id}.jsonl"
        )
        try:
            client.request(
                "initialize",
                {
                    "clientInfo": {"name": "agent-box", "version": "preview"},
                    "capabilities": {},
                },
            )
            client.notify("initialized", {})
            continuation_values = request.inputs.get(CodexContinuationV1.contract_id, ())
            if continuation_values:
                continuation = continuation_values[0]
                if not isinstance(continuation, CodexContinuationV1):
                    raise TypeError("continuation contract type mismatch")
                started = client.request(
                    "thread/resume",
                    {
                        "threadId": continuation.thread_id,
                        "cwd": command.cwd_token,
                        # Agent-Box already owns the filesystem sandbox via
                        # the exact frozen SandboxRef.  This legacy thread
                        # field must permit the turn-level externalSandbox
                        # override below; it does not weaken the outer bwrap
                        # policy.
                        "sandbox": "danger-full-access",
                        "approvalPolicy": "never",
                    },
                )
            else:
                started = client.request(
                    "thread/start",
                    {
                        # The App Server runs inside the selected Sandbox.
                        # Never pass the host worktree path across that
                        # boundary: the RuntimeBundle mounts it at this
                        # command's canonical guest path.
                        "cwd": command.cwd_token,
                        # Codex's legacy sandbox must not create a second,
                        # unaware bwrap around the guest workspace.  The
                        # actual restriction comes from Agent-Box's selected
                        # external Sandbox provider at process creation.
                        "sandbox": "danger-full-access",
                        "approvalPolicy": "never",
                        "ephemeral": False,
                        "developerInstructions": (
                            "You are operating inside one Agent-Box Execution. "
                            "Treat the supplied context as the fixed responsibility "
                            "for this Execution and work only in the supplied workspace."
                        ),
                    },
                )
            thread_id = started["thread"]["id"]
            turn = client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": prompt}],
                    "cwd": command.cwd_token,
                    "effort": "low",
                    "approvalPolicy": "never",
                    "sandboxPolicy": {
                        "type": "externalSandbox",
                        # The selected bwrap cloud template inherits network
                        # for Codex control-plane traffic.  Agent-Box does
                        # not claim separate workload-network enforcement.
                        "networkAccess": "enabled",
                    },
                },
            )
            projection = (coordinator.projection_receipt(run_handle.attempt_key)
                          if isinstance(coordinator, RuntimeCompositionCoordinator) else None)
            handle = CodexInteractiveHandle(
                request.execution_id,
                request.dispatch_id,
                request.inputs_digest,
                workspace,
                command.cwd_token,
                profile,
                client,
                thread_id,
                [turn["turn"]["id"]],
                tuple(sorted(request.inputs)),
                composition_handle=run_handle,
                projection=projection,
            )
            self._handles[request.dispatch_id] = handle
            return ExecutionStartReceipt(
                request.execution_id,
                request.dispatch_id,
                request.inputs_digest,
                correlation_ref=Ref(
                    RefType.SESSION,
                    self.descriptor().id,
                    thread_id,
                    uri=f"codex://thread/{thread_id}",
                ),
                runtime_handle=handle,
            )
        except Exception:
            client.close()
            raise

    def get_handle(self, dispatch_id: str) -> CodexInteractiveHandle:
        try:
            return self._handles[dispatch_id]
        except KeyError as exc:
            raise KeyError(f"unknown Codex Dispatch: {dispatch_id}") from exc

    def wait_current_turn(
        self, handle: CodexInteractiveHandle, *, timeout: float = 300
    ) -> dict[str, Any]:
        turn_id = handle.turn_ids[-1]
        result = handle.client.wait_turn_completed(turn_id, timeout=timeout)
        handle.turn_results[turn_id] = result
        return result

    def send_turn(
        self, handle: CodexInteractiveHandle, text: str, *, wait_timeout: float = 300
    ) -> str:
        if handle.submitted:
            raise RuntimeError("Execution has already been submitted")
        self.wait_current_turn(handle, timeout=wait_timeout)
        started = handle.client.request(
            "turn/start",
            {
                "threadId": handle.thread_id,
                "input": [{"type": "text", "text": text}],
                "cwd": handle.guest_cwd,
                "approvalPolicy": "never",
                "sandboxPolicy": {
                    "type": "externalSandbox",
                    "networkAccess": "enabled",
                },
            },
        )
        turn_id = started["turn"]["id"]
        handle.turn_ids.append(turn_id)
        return turn_id

    def steer(self, handle: CodexInteractiveHandle, text: str) -> None:
        if handle.submitted:
            raise RuntimeError("Execution has already been submitted")
        handle.client.request(
            "turn/steer",
            {
                "threadId": handle.thread_id,
                "expectedTurnId": handle.turn_ids[-1],
                "input": [{"type": "text", "text": text}],
            },
        )

    def finish(
        self, handle: CodexInteractiveHandle, *, timeout: float = 300
    ) -> CodexInteractiveObservation:
        """Provider-owned explicit responsibility completion signal."""
        if isinstance(handle, ExecutionStartReceipt):
            handle = handle.runtime_handle
        self.wait_current_turn(handle, timeout=timeout)
        handle.submitted = True
        handle.client.close()
        observation=self.observe(handle)
        if self._launch_adapter is not None:
            self._launch_adapter.cleanup(handle.execution_id)
        return observation

    @staticmethod
    def _turn_succeeded(handle: CodexInteractiveHandle) -> bool:
        if not handle.turn_ids:
            return False
        params = handle.turn_results.get(handle.turn_ids[-1]) or {}
        status = str((params.get("turn") or {}).get("status") or "").lower()
        if status not in {"completed", "complete", "succeeded", "success"}:
            return False
        return "failed" not in getattr(handle.client, "file_change_statuses", ())

    def observe(self, native_ref: Any) -> CodexInteractiveObservation:
        if isinstance(native_ref, ExecutionStartReceipt):
            native_ref = native_ref.runtime_handle
        handle = (
            self.get_handle(native_ref)
            if isinstance(native_ref, str)
            else native_ref
        )
        if not isinstance(handle, CodexInteractiveHandle):
            raise TypeError("observe requires dispatch id or CodexInteractiveHandle")
        session_ref = Ref(RefType.SESSION, self.provider_id, handle.thread_id)
        run_refs = tuple(
            Ref(
                RefType.RUN,
                self.provider_id,
                turn_id,
                metadata={"thread_id": handle.thread_id},
            )
            for turn_id in handle.turn_ids
        )
        output_refs: tuple[Ref, ...] = ()
        if handle.submitted:
            event_bytes = handle.client.events_path.read_bytes()
            digest = "sha256:" + hashlib.sha256(event_bytes).hexdigest()
            output_refs = (
                Ref(
                    RefType.ARTIFACT,
                    self.provider_id,
                    digest,
                    uri=handle.client.events_path.as_uri(),
                    metadata={"kind": "app-server-events"},
                ),
            )
            outcome = Outcome.SUCCEEDED if self._turn_succeeded(handle) else Outcome.FAILED
            # The thread was started (and confirmed by the app server) with
            # ``ephemeral: False``, so its native identity remains available
            # as a continuation source for a NEW Execution via thread/resume.
            projection = ExecutionProjection(
                # SessionRef is a continuation input for a new Execution;
                # this terminal Core projection is sealed.
                Phase.TERMINAL, outcome, False, Freshness.OBSERVED, _now()
            )
        elif handle.client.process.poll() is None:
            projection = ExecutionProjection(
                Phase.ACTIVE, None, True, Freshness.OBSERVED, _now()
            )
        else:
            projection = ExecutionProjection(
                Phase.UNKNOWN, None, None, Freshness.UNREACHABLE, _now()
            )
        return CodexInteractiveObservation(
            projection,
            (session_ref, *run_refs),
            output_refs,
            handle.projected_contracts,
            {
                "thread_id_present": bool(handle.thread_id),
                "turn_ids_present": bool(handle.turn_ids),
                "cwd_token": handle.guest_cwd,
                "turn_completed_before_finish": bool(handle.turn_results),
                "projection": handle.projection,
                "lifecycle": (
                    handle.client.diagnostics(tuple(handle.turn_ids))
                    if hasattr(handle.client, "diagnostics")
                    else {"available": False}
                ),
            },
        )


__all__ = [
    "CodexAppServerClient",
    "CodexInteractiveExecutionProvider",
    "CodexInteractiveHandle",
    "CodexInteractiveObservation",
]
