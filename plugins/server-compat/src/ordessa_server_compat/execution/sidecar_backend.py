"""Provider-neutral Server/Core orchestration for the Harness sidecar port."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import base64
import json
import logging
import re
import threading
import time
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping

from pacthold.execution.contracts import (
    CancelOutcome, EvidenceClass, ExecutionObservation, ExecutionReceipt,
    ExecutionRequest, ObservationState,
)
from pacthold.execution.first_run_lock import first_run_gate
from pacthold.execution.lifecycle import NeutralRun, NeutralRunTracker
from pacthold.extensions import capability
from pacthold.extensions.runtime_composition.sandbox_port import SandboxPortUnavailable
from pacthold.resource_contracts import AgentBoxProfileV1, PromptFragmentV1, WorkspaceV1
from ordessa_server.errors import ServerError
from ordessa_server_compat.execution.placement import PlacementUnsupported
from ordessa_server_compat.execution.sidecar import (
    NativeHarnessPort, NativeProcessLauncher, SidecarError, SidecarHarnessPort,
)
from pacthold.work_core import (
    ExecutionFinalizationRequest, ExecutionProjection, ExecutionStartReceipt,
    Freshness, Outcome, Phase, ProviderDescriptor, Ref, RefType,
)
from pacthold.work_core.errors import DispatchAmbiguous, ExecutionStartRejected
from pacthold.work_core.registry import ExtensionRegistry
from pacthold.work_core.repository import CoreRepository
from pacthold.work_core.services import ExecutionService, WorkService


@dataclass
class _Run:
    turn_id: str
    work_id: str
    core_execution_id: str
    dispatch_id: str
    port: SidecarHarnessPort
    native_id: str
    done: threading.Event
    cancel_lock: threading.Lock = field(default_factory=threading.Lock)
    cancel_confirmed: bool = False
    result: Mapping[str, Any] | None = None
    error: BaseException | None = None
    #: Order 51: the neutral usage fact, read while the channel lived; None
    #: means unknown (and the ledger must keep it unknown, never estimate).
    usage_fact: dict[str, int] | None = None
    usage_source: str | None = None
    #: Order 80: the exclusive hold on this library's *first* run (only the run
    #: that opened a whole-db store while it was still fresh carries one);
    #: released when this run reaches its terminal.
    first_run_hold: Any = None
    #: The worker that persists the durable turn result. It outlives the prompt
    #: worker by design, so a runtime is only really stopped once it is done:
    #: the Work Core connection is shared and is not safe to use after shutdown.
    completion_thread: threading.Thread | None = None


#: MB-E2b equal-move: the neutral run type is defined once in
#: ``pacthold.execution.lifecycle`` (``NeutralRun``); this historical name
#: keeps pointing at the same class object - identity-pinned by
#: ``tests/server/test_e_modular_execution_lifecycle.py``.
_NeutralRun = NeutralRun


class _BoundResources:
    provider_id = "server-sidecar-input"
    supported_contract_ids = frozenset({
        WorkspaceV1.contract_id, PromptFragmentV1.contract_id, AgentBoxProfileV1.contract_id,
    })

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], object] = {}
        self._lock = threading.Lock()

    def descriptor(self):
        return ProviderDescriptor(self.provider_id, "Server frozen sidecar inputs", "1")

    def bind(self, contract_id: str, native_id: str, value: object) -> Ref:
        with self._lock:
            self._values[(contract_id, native_id)] = value
        ref_type = RefType.WORKSPACE if contract_id == WorkspaceV1.contract_id else RefType.ARTIFACT
        return Ref(ref_type, self.provider_id, native_id)

    def resolve(self, contract_id: str, ref: Ref, *, context=None) -> object:
        del context
        with self._lock:
            return self._values[(contract_id, ref.native_id)]

    def release(self, turn_id: str) -> None:
        with self._lock:
            self._values = {
                key: value for key, value in self._values.items() if not key[1].endswith(turn_id)
            }


class _CoreSidecarProvider:
    provider_id = "harness-sidecar"

    def __init__(self, backend: "SidecarExecutionBackend") -> None:
        self.backend = backend
        self._handles: dict[str, _Run] = {}

    def descriptor(self):
        return ProviderDescriptor(self.provider_id, "Harness sidecar execution", "1")

    def capabilities(self):
        """Work Core execution-provider operation contract (NOT Harness abilities).

        This mapping belongs to the Work Core SPI: `ExtensionRegistry.require_capability`
        reads it to decide whether a provider may be asked for an operation, and its
        keys are Work Core operation names (`streaming`, `cancel`, `approvals`).

        The Harness capability contract is a *different* namespace with a different
        question ("what can this harness do, as declared and observed?"), and the
        two must never be projected into one another: these keys are not canonical
        abilities, they must not reach a Profile view, a Session/execution effective
        capability view, `server.hello` or a deployment's `capabilityClaims`, and a
        canonical ability must not be invented here. `test_capability_namespace_boundary.py`
        fails if that separation is broken.
        """
        return {"streaming": "supported", "cancel": "supported", "approvals": "supported"}

    def input_limits(self):
        return {
            WorkspaceV1.contract_id: (1, 1),
            PromptFragmentV1.contract_id: (1, 1),
            AgentBoxProfileV1.contract_id: (1, 1),
        }

    def start(self, request):
        values = {item.contract_id: item.value for item in request.resolved_inputs}
        try:
            run = self.backend._start_run(
                request.execution_id, request.dispatch_id,
                values[WorkspaceV1.contract_id], values[PromptFragmentV1.contract_id],
                values[AgentBoxProfileV1.contract_id],
            )
        except CapabilityGateRefusal as refusal:
            # 能力门紧邻 open_execution 之前拒绝（专用类型，来源隔离）：已证明原生
            # 启动未发生，按 Core 既有 ExecutionStartRejected 语义记录为 failed
            # （而非 ambiguous），并把原因码挂在异常上供 Server 映射还原。
            # post-open 的任何 SidecarError（即使同名错误码）不经此转换，保持
            # 既有歧义语义。
            rejection = ExecutionStartRejected(str(refusal))
            rejection.code = refusal.code
            raise rejection from refusal
        except (PlacementUnsupported, SandboxPortUnavailable) as refusal:
            # Order 090: placement/sandbox resolution happens inside port_factory,
            # strictly before any native side effect (open_execution/spawn). A turn
            # that cannot resolve its placement is therefore a deterministic
            # "start never happened" refusal - it must be recorded as a typed
            # failure with its own code, never as an ambiguous dispatch. This is
            # the same ExecutionStartRejected seam the capability gate uses.
            rejection = ExecutionStartRejected(str(refusal))
            rejection.code = refusal.code
            raise rejection from refusal
        self._handles[request.dispatch_id] = run
        return ExecutionStartReceipt(
            request.execution_id, request.dispatch_id, request.inputs_digest,
            correlation_ref=Ref(RefType.SESSION, self.provider_id, run.native_id),
            runtime_handle=run,
        )

    def get_handle(self, dispatch_id: str) -> _Run:
        return self._handles[dispatch_id]

    def release_handle(self, dispatch_id: str) -> None:
        self._handles.pop(dispatch_id, None)

    def observe(self, native_ref):
        del native_ref
        return None


class SidecarExecutionBackend:
    """TurnExecutionPort using Core dispatch and a sidecar factory.

    The factory is the deployment composition seam. It receives a stored,
    provider-neutral Turn context and an event callback, and returns a port
    whose Node sidecar owns all native Harness semantics.
    """

    def __init__(
        self, records, objects, approvals, *,
        port_factory: Callable[[Mapping[str, Any], Callable[..., None]], SidecarHarnessPort],
        on_event: Callable[[], None] | None = None,
    ) -> None:
        self.records = records
        self.objects = objects
        self.approvals = approvals
        self.port_factory = port_factory
        self.on_event = on_event or (lambda: None)
        self.core_repository = CoreRepository()
        self.work_service = WorkService(self.core_repository)
        self.execution_service = ExecutionService(self.core_repository)
        self.resources = _BoundResources()
        self.provider = _CoreSidecarProvider(self)
        self.registry = ExtensionRegistry()
        self.registry.register_resource_provider(self.resources.provider_id, self.resources)
        self.registry.register_execution_provider(self.provider)
        self._turn_by_core: dict[str, str] = {}
        self._contexts: dict[str, Mapping[str, Any]] = {}
        #: Completion workers still running. A run is retired from `_active` when
        #: its durable result is written, but the worker itself may still be
        #: finishing; stopping must wait for every live one, so they are tracked
        #: here rather than only on the run.
        self._completion_threads: set[threading.Thread] = set()
        self._approval_ports: dict[str, SidecarHarnessPort] = {}
        self._message_parts: dict[str, list[str]] = {}
        # Native ACP sessions are session-scoped, not turn-scoped.  Only native
        # ports enter this table; isolated execution sidecars keep their old
        # one-process-per-turn lifecycle.
        self._native_ports: dict[str, NativeHarnessPort] = {}
        #: Neutral-verb state (C-EXEC@v1 block1, E-INC1a) lives once in the
        #: tracker (MB-E2b equal-move); the attributes below are aliases onto
        #: the SAME ledger objects and lock - never copies - so business runs
        #: (registered into ``_active``) and neutral runs answer through the
        #: one cancel state machine. Identity-pinned by
        #: ``tests/server/test_e_modular_execution_lifecycle.py``.
        self._lifecycle = NeutralRunTracker()
        self._active: dict[str, _Run] = self._lifecycle.active_runs
        self._neutral_runs = self._lifecycle.runs
        self._cancel_receipts = self._lifecycle.cancel_receipts
        self._lock = self._lifecycle.lock
        self.queue = None

    def bind_queue(self, queue) -> None:
        self.queue = queue

    def accept(self, turn_id: str) -> None:
        # E-INC1b b-4: the effective configuration is frozen at turn-creation
        # time by the Session side and consumed here as the turn row's raw key
        # (never the COALESCE'd live-row fallback). INC1c c-5 (joint signature
        # note, C-notice-E-041-ruled 裁③): the retired `overrides` parameter
        # is deleted here, in the Protocol, and in sidecar.
        context = self.records.get_turn_context(turn_id)
        stored = json.loads(self.objects.read(context["input_object_digest"]))
        message = stored.get("message") or stored
        effective_digest = context["effective_config_object_digest"]
        # a-3 K2-E (读法甲, approvals/a-3-release.md K2 + C-notice-E-047-051-ruled
        # §3): the Core bookkeeping of an accepted Session Turn - work and
        # execution - is created by the Session acceptance path *before* this
        # consumer runs (提交后紧随步＋幂等先行＝重放零再建档), and its identity
        # travels on the turn row. This consumer reads that identity and never
        # mints a second producer; a row that carries none is refused typed
        # instead of silently re-creating a second work/execution pair.
        execution_key = context.get("execution_key")
        work_id = context.get("work_id")
        execution_id = context.get("execution_id")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (execution_key, work_id, execution_id)
        ):
            raise ServerError(
                "IDEMPOTENCY_CONFLICT",
                "the accepted Turn carries no pre-created execution identity",
                status=409,
            )
        inputs = (
            (WorkspaceV1.contract_id, self.resources.bind(
                WorkspaceV1.contract_id, f"workspace-{turn_id}",
                WorkspaceV1(PurePosixPath(context["remote_path"]), "remote-live"),
            )),
            (PromptFragmentV1.contract_id, self.resources.bind(
                PromptFragmentV1.contract_id, f"prompt-{turn_id}",
                PromptFragmentV1("User Turn", str(message["text"]), context["input_object_digest"]),
            )),
            (AgentBoxProfileV1.contract_id, self.resources.bind(
                AgentBoxProfileV1.contract_id, f"profile-{turn_id}",
                AgentBoxProfileV1(
                    context["profile_id"], context["harness_type"], effective_digest,
                    int(context["profile_revision"]),
                ),
            )),
        )
        with self._lock:
            self._turn_by_core[execution_id] = turn_id
            self._contexts[turn_id] = context
            self._message_parts[turn_id] = []
        try:
            receipt = self.execution_service.dispatch_execution(
                execution_id, inputs, self.registry, execution_key,
            )
            run = self.provider.get_handle(receipt.dispatch_id)
            run.work_id = work_id
            self.records.set_turn_dispatch(
                turn_id, work_id=work_id, execution_id=execution_id,
                dispatch_id=receipt.dispatch_id, state="running",
            )
            with self._lock:
                self._active[turn_id] = run
                self._cancel_receipts.pop(turn_id, None)
            self.on_event()
            run.completion_thread = threading.Thread(
                target=self._complete_then_retire, args=(run,), daemon=True,
            )
            with self._lock:
                self._completion_threads.add(run.completion_thread)
            run.completion_thread.start()
        except BaseException as exc:
            self.records.fail_turn(turn_id, _safe_code(exc), queue_records=self.queue)
            self.resources.release(turn_id)
            self.on_event()
            raise

    def _start_run(self, core_execution_id, dispatch_id, workspace, prompt, profile) -> _Run:
        del workspace, profile
        with self._lock:
            turn_id = self._turn_by_core[core_execution_id]
            context = self._contexts[turn_id]
        # Legacy unit providers may supply a turn-only context; real Session
        # acceptance always supplies session_id, which is the reuse key.
        session_id = str(context.get("session_id") or f"execution:{turn_id}")
        with self._lock:
            port = self._native_ports.get(session_id)
        reusing_native_port = port is not None
        if port is None:
            port = self.port_factory(context, lambda execution_id, kind, data: self._native_event(
                execution_id, kind, data, port,
            ))
            # A native session that has a checkpoint but no live channel may
            # only be reopened when it really promises durable continuation.
            if (isinstance(port, NativeHarnessPort)
                    and context.get("checkpoint_object_digest")
                    and context.get("checkpoint_native_id")):
                try:
                    checkpoint = json.loads(self.objects.read(context["checkpoint_object_digest"]))
                except (ValueError, KeyError, TypeError):
                    checkpoint = None
                if not isinstance(checkpoint, dict) or checkpoint.get("resumable") is not True:
                    raise NativeSessionUnavailable()
        elif (isinstance(port, NativeHarnessPort)
              and context.get("normalized_path") != port.directory):
            # A session's project can be edited while idle.  The live native
            # process cannot silently keep working in the previous cwd.
            raise NativeProjectRefusal("NATIVE_PROJECT_CHANGED")
        # 附件先投影出来（有界对象读取），再打开执行：有效 attach=false 时必须在派发前
        # 类型化拒绝，而不是打开一个原生会话再静默丢弃附件。
        stored = json.loads(self.objects.read(context["input_object_digest"]))
        attachments, file_refs = _sidecar_attachments(self.objects, stored)
        # 实际副作用（client.start()/spawn）前的唯一强制门：需求来自 launcher 当前
        # 计划，授权/声明/绑定来自装配边界注入；不满足即类型化拒绝，零 launcher/spawn。
        _capability_gate(port, turn_id)
        # Order 80: the first run on a fresh whole-db library is exclusive; a
        # concurrent first run waits for it (bounded, typed on timeout) and
        # every later run passes straight through. The gate is taken before the
        # room exists, because the race is in the harness's own initialisation.
        hold = None
        if getattr(port, "whole_db_store", False):
            hold = first_run_gate().acquire(
                f"{port.native_platform or 'local'}:{port.profile}")
        try:
            native_id = port.open_execution(turn_id)
            if isinstance(port, NativeHarnessPort):
                with self._lock:
                    self._native_ports[session_id] = port
            if attachments and not _effective_attachment_support(port, turn_id):
                # 拒绝时不留一个没有归属的原生会话（否则 _complete 永远不会回收它）。
                try:
                    if isinstance(port, NativeHarnessPort) and not reusing_native_port:
                        with self._lock:
                            if self._native_ports.get(session_id) is port:
                                self._native_ports.pop(session_id, None)
                        port.stop()
                    else:
                        port.close_execution(turn_id)
                except BaseException:
                    pass
                raise SidecarError(
                    "ATTACHMENT_UNSUPPORTED",
                    "this execution has no effective 'attach' capability",
                )
        except BaseException:
            # An acquisition that never produced a run must not hold the
            # library hostage (the attachment refusal above is one such path).
            if hold is not None:
                hold.release()
            raise
        run = _Run(turn_id, "", core_execution_id, dispatch_id, port, native_id, threading.Event())
        run.first_run_hold = hold
        prompt_content = prompt.content
        if file_refs:
            prompt_content += "\n\nWorkspace attachments (validated):\n" + "\n".join(
                f"- {path}" for path in file_refs
            )

        def prompt_worker() -> None:
            try:
                run.result = self._prompt_with_rebuild(port, turn_id, prompt_content, attachments)
            except BaseException as exc:  # surfaced by the completion owner
                run.error = exc
            finally:
                run.done.set()

        threading.Thread(target=prompt_worker, daemon=True).start()
        return run

    #: How many times a freshly-opened sidecar may be rebuilt when a prompt
    #: finds it already closed (the drain the same second a prior sidecar exits,
    #: ACC-R2-1). Bounded on purpose: recovery is not an infinite retry.
    PROMPT_REBUILD_LIMIT = 2
    #: Upper bound on the total backoff spent waiting out an in-flight teardown
    #: across those rebuilds; the wait is bounded, never open-ended.
    PROMPT_REBUILD_BACKOFF_SECONDS = 0.2

    def _prompt_with_rebuild(self, port, turn_id, prompt_content, attachments):
        """Prompt the execution's sidecar, rebuilding it if it is already closed.

        Order 106: the queue drain starts in the same second the previous turn
        reaches *completed*, and that previous sidecar is mid-teardown. The
        successor turn gets its own fresh sidecar, but the overlap still surfaces
        as ``SIDECAR_CLOSED`` at the prompt boundary - a queued message the user
        sees die in a second. Here the drained (and any) turn ensures a live
        sidecar before it gives up: on ``SIDECAR_CLOSED`` it drops the dead
        envelope, reopens a fresh sidecar on the SAME execution, and re-prompts -
        bounded by ``PROMPT_REBUILD_LIMIT`` and a bounded backoff. If every
        rebuild still finds a closed sidecar, the failure is typed
        (``SIDECAR_REBUILD_FAILED``) rather than left as an ambiguous close.

        It reuses the new-turn open path (``open_execution``) rather than a second
        dispatch path, so it never re-dispatches the turn and touches no queue,
        idempotency or wire semantics.
        """
        deadline = time.monotonic() + self.PROMPT_REBUILD_BACKOFF_SECONDS
        last: SidecarError | None = None
        for attempt in range(self.PROMPT_REBUILD_LIMIT + 1):
            try:
                return port.prompt(turn_id, prompt_content, attachments)
            except SidecarError as exc:
                if exc.code != "SIDECAR_CLOSED":
                    raise
                last = exc
                if attempt == self.PROMPT_REBUILD_LIMIT:
                    break
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(self.PROMPT_REBUILD_BACKOFF_SECONDS / (attempt + 1), remaining))
                # Rebuild this execution on a fresh sidecar, then retry.
                port.close_execution(turn_id)
                port.open_execution(turn_id)
        raise SidecarRunRecoveryFailure(
            "sidecar stayed closed after "
            f"{self.PROMPT_REBUILD_LIMIT} rebuild attempt(s); last: {last}",
        )

    def _native_event(self, turn_id: str, kind: str, data: Mapping[str, Any], port) -> None:
        if kind == "message.delta":
            text = str(data.get("text", ""))
            if text:
                self.records.append_turn_event(turn_id, kind, {"text": text})
                with self._lock:
                    self._message_parts.setdefault(turn_id, []).append(text)
        elif kind == "approval.requested":
            context = self.records.get_turn_context(turn_id)
            raw = dict(data.get("request") or {})
            approval = self.approvals.request(
                session_id=context["session_id"], execution_id=turn_id, request=raw,
            )
            # Order 65: a subagent's `ask` rises into the parent turn as the
            # same kind of interruption the parent already handles - the
            # approval id is what the existing decide round-trip takes, so no
            # second mechanism exists to bypass.
            parent_turn = context.get("parent_turn_id")
            if parent_turn:
                self.records.append_turn_event(
                    str(parent_turn), "approval.requested",
                    {"approval_id": approval["approvalId"], "version": 1,
                     "request": raw,
                     "from_subagent": {"turnId": turn_id,
                                       "sessionId": context["session_id"]}},
                )
            request_id = str(raw.get("requestId") or "")
            if request_id:
                port.register_approval(approval["approvalId"], turn_id, request_id)
                with self._lock:
                    self._approval_ports[approval["approvalId"]] = port
        elif kind == "failed":
            self.records.append_turn_event(turn_id, "tool.update", {
                "state": "failed", "tool_call_id": "harness", "tool": None,
                "summary": str(data.get("code") or "HARNESS_FAILED"),
            })
        elif kind == "thought.delta":
            text = str(data.get("text") or "")
            if text:
                self.records.append_turn_event(turn_id, "thought.delta", {"text": text})
        elif kind == "tool.update":
            # Keep the existing wire/1 tool fact and a bounded native output
            # excerpt. This is not a lossless ACP event stream: raw arguments,
            # images, and custom updates require a separate reviewed contract.
            self.records.append_turn_event(turn_id, "tool.update", {
                "tool_call_id": str(data.get("tool_call_id") or "tool"),
                "tool": data.get("tool"),
                "state": str(data.get("state") or "requested"),
                **({"summary": str(data["summary"])[:512]} if data.get("summary") else {}),
                **({"result_excerpt": str(data["result_excerpt"])[:4096]}
                   if data.get("result_excerpt") else {}),
            })
        elif kind == "plan.updated":
            self.records.append_turn_event(turn_id, "plan.updated", {
                "entries": data.get("entries") if isinstance(data.get("entries"), list) else [],
            })
        elif kind == "mode.updated":
            self.records.append_turn_event(turn_id, "mode.updated", {
                "currentModeId": str(data.get("currentModeId") or ""),
            })
        self.on_event()

    def decide_approval(self, approval_id: str, decision: str, scope: Mapping[str, Any]) -> None:
        with self._lock:
            port = self._approval_ports.get(approval_id)
        if port is not None:
            port.decide_approval(approval_id, decision, scope)
        self.on_event()

    def _complete(self, run: _Run) -> None:
        run.done.wait()
        next_execution_id = None
        try:
            # The prompt can become idle before the abort envelope response is
            # delivered.  Serialize that race so a confirmed stop can never be
            # persisted as a successful completion.
            with run.cancel_lock:
                cancelled = run.cancel_confirmed
            # A native ACP terminal cancellation is confirmation even when
            # Server did not initiate it; route it through the same Core and
            # Session finalization as an acknowledged stop request.
            if run.error is None and _terminal_reason_from_result(run.result) == "cancelled":
                cancelled = True
            if cancelled:
                self.execution_service.apply_finalization(ExecutionFinalizationRequest(
                    run.core_execution_id, f"turn-terminal:{run.turn_id}",
                    ExecutionProjection(
                        Phase.TERMINAL, Outcome.CANCELLED, False, Freshness.OBSERVED,
                        datetime.now(timezone.utc),
                    ),
                ))
                # A cancel is not an erasure. The Harness kept writing its own
                # home up to the moment it stopped; audit what is there now and
                # keep the reference, so the next turn reopens the same native
                # session and sees the input that was already on disk. If the
                # audit itself cannot run, the record honestly stays as it was.
                try:
                    audit, native_resume_supported = _audited_home(run)
                    manifest = {
                        "schema_version": 3,
                        "nativeSessionId": run.native_id,
                        "harnessType": self._contexts[run.turn_id]["harness_type"],
                        "nativePlatform": audit["nativePlatform"],
                        "homeLocator": audit["homeLocator"],
                        "resumable": _resumable(run.port, native_resume_supported, audit),
                        "sourceExecutionId": run.core_execution_id,
                        "audited": audit["audited"],
                        "truncated": audit["truncated"],
                        "files": audit["files"],
                    }
                    checkpoint = self.objects.publish(
                        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
                    )
                except BaseException:
                    checkpoint = None
                self.records.finish_cancelled(
                    run.turn_id, queue_records=self.queue,
                    **({"checkpoint_object_digest": checkpoint.digest,
                        "checkpoint_native_id": run.native_id,
                        "native_platform": audit["nativePlatform"],
                        "home_locator": audit["homeLocator"]} if checkpoint is not None else {}),
                )
                self.work_service.complete_work(run.work_id, "Turn cancelled through Harness sidecar")
                return
            if run.error is not None:
                raise run.error
            # ACP session/prompt can return successfully at the transport layer
            # while the agent itself reports an error.  That is not a completed
            # turn; in particular an empty answer must not look successful.
            stop_reason = _terminal_reason_from_result(run.result)
            if stop_reason == "error":
                raise SidecarError("HARNESS_RUN_FAILED", "native agent reported an error")
            with self._lock:
                text = "".join(self._message_parts.get(run.turn_id, ()))
            audit, native_resume_supported = _audited_home(run)
            resumable = _resumable(run.port, native_resume_supported, audit)
            # The manifest is a *record*: it references the home on the machine
            # that ran the turn (platform + locator, never a host path) and
            # fixes what that home looked like when the turn ended. The native
            # bytes themselves are never published.
            checkpoint = self.objects.publish(json.dumps({
                "schema_version": 3, "nativeSessionId": run.native_id,
                "harnessType": self._contexts[run.turn_id]["harness_type"],
                "nativePlatform": audit["nativePlatform"],
                "homeLocator": audit["homeLocator"],
                "resumable": resumable,
                "sourceExecutionId": run.core_execution_id,
                "audited": audit["audited"],
                "truncated": audit["truncated"],
                "files": audit["files"],
            }, sort_keys=True, separators=(",", ":")).encode())
            result = self.objects.publish(json.dumps({
                "schema_version": 1, "text": text, "nativeResult": run.result or {},
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
            self.records.append_turn_event(run.turn_id, "message.final", {"text": text})
            self.execution_service.apply_finalization(ExecutionFinalizationRequest(
                run.core_execution_id, f"turn-finalize:{run.turn_id}",
                ExecutionProjection(
                    Phase.TERMINAL, Outcome.SUCCEEDED, resumable, Freshness.OBSERVED,
                    datetime.now(timezone.utc),
                ),
                native_refs=(Ref(RefType.SESSION, self.provider.provider_id, run.native_id),),
            ))
            # Order 51: the usage fact was read while the channel lived
            # (see _audited_home); absent stays absent in the ledger.
            usage = getattr(run, "usage_fact", None)
            usage_source = getattr(run, "usage_source", None)
            # Order 54: the workspace change set, published as a record
            # object (a fact document, never harness tool load).
            change_set_digest = None
            try:
                change_set = run.port.workspace_change_set(run.turn_id)
            except BaseException as read_error:
                logging.getLogger(__name__).warning(
                    "turn %s: change set read failed (%s); the turn's change set "
                    "stays unknown", run.turn_id, read_error,
                )
                change_set = None
            if change_set is not None:
                change_set_checkpoint = self.objects.publish(json.dumps(
                    {"schema_version": 1, "changeSet": change_set},
                    sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                ).encode())
                change_set_digest = change_set_checkpoint.digest
            completed, _event = self.records.complete_turn(
                run.turn_id, checkpoint_object_digest=checkpoint.digest,
                checkpoint_native_id=run.native_id, result_object_digest=result.digest,
                queue_records=self.queue,
                native_platform=audit["nativePlatform"], home_locator=audit["homeLocator"],
                usage=usage, usage_source=usage_source,
                change_set_object_digest=change_set_digest,
                terminal_reason=_terminal_reason_from_result(run.result),
            )
            next_execution_id = completed.get("next_execution_id")
            self.work_service.complete_work(run.work_id, "Turn completed through Harness sidecar")
        except BaseException as exc:
            code = _safe_code(exc)
            if code != "TURN_CANCELLED":
                logging.getLogger(__name__).exception("turn %s failed as %s", run.turn_id, code)
            if code == "TURN_CANCELLED":
                self.records.finish_cancelled(run.turn_id, queue_records=self.queue)
            else:
                self.records.fail_turn(run.turn_id, code, queue_records=self.queue)
        finally:
            approval_cleanup_failed = False
            try:
                self.approvals.invalidate_for_execution(run.turn_id, "execution_terminal")
            except BaseException:
                # The execution terminal fact is already durable; retain a
                # visible failed-cleanup fact and never turn it into a grant.
                approval_cleanup_failed = True
            try:
                try:
                    run.port.close_execution(run.turn_id)
                except BaseException:
                    # Teardown of the native channel failed; that is a cleanup
                    # failure to record, never a reason to skip the release below.
                    approval_cleanup_failed = True
                self.records.mark_turn_cleanup(
                    run.turn_id, "failed" if approval_cleanup_failed else "cleaned",
                )
            except BaseException:
                # Order 109: the *fallback* record could itself fail (the shared
                # SQLite is contended exactly when a second failure follows a
                # first), and a bare raise here would escape the `finally` and
                # strand the run's bookkeeping forever. Record it and fall
                # through - the release must run no matter what.
                logging.getLogger(__name__).exception(
                    "turn %s: cleanup record failed", run.turn_id)
                try:
                    self.records.mark_turn_cleanup(run.turn_id, "failed")
                except BaseException:
                    logging.getLogger(__name__).exception(
                        "turn %s: cleanup failed-record also could not be written",
                        run.turn_id)
            # Guaranteed release of every shared handle, independent of each
            # other, so no failure above can leak the run or wedge the loop.
            self._retire_run(run)
            self.on_event()
        if next_execution_id is not None:
            try:
                self.accept(next_execution_id)
            except BaseException:
                # accept() already persisted this dispatch failure and paused
                # any still-pending items; the completed predecessor stays final.
                pass

    def _retire_run(self, run: "_Run") -> None:
        """Release every shared handle a run holds, so a failed turn cannot leak
        the active maps, the bound resources, or the provider dispatch handle.

        Each step is independent: one raising must not strand the others (that
        leak is what accumulated across failures into the order-109 HTTP hang).
        """
        with self._lock:
            self._active.pop(run.turn_id, None)
            self._contexts.pop(run.turn_id, None)
            self._message_parts.pop(run.turn_id, None)
            self._turn_by_core.pop(run.core_execution_id, None)
            self._approval_ports = {
                key: value for key, value in self._approval_ports.items() if value is not run.port
            }
        try:
            self.resources.release(run.turn_id)
        except BaseException:
            logging.getLogger(__name__).exception(
                "turn %s: bound-resource release failed", run.turn_id)
        try:
            self.provider.release_handle(run.dispatch_id)
        except BaseException:
            logging.getLogger(__name__).exception(
                "turn %s: provider handle release failed", run.turn_id)

    def _complete_then_retire(self, run: "_Run") -> None:
        """Run the durable completion and stop being a live worker afterwards."""
        try:
            self._complete(run)
        finally:
            # Order 80: this run's terminal is what makes the library "ready" —
            # every later run (and anyone waiting) passes through from here.
            if run.first_run_hold is not None:
                run.first_run_hold.release()
            with self._lock:
                self._completion_threads.discard(threading.current_thread())

    def pid_for(self, turn_id: str) -> int | None:
        """The execution-side pid for one in-flight turn, if this side has it.

        A local run's process object is the only source; a Worker-hosted run
        has none here, and an unknown turn is simply "not reported" - the
        inventory shows null rather than a guess.
        """
        with self._lock:
            run = self._active.get(turn_id)
        if run is None:
            return None
        pid = getattr(run.port, "pid", None)
        if not callable(pid):
            return None
        try:
            return pid(turn_id)
        except BaseException:  # noqa: BLE001 - unknown is the honest answer
            return None

    def cancel_execution(self, execution_key: str) -> CancelOutcome:
        """Block-1 tristate cancel. A lost answer is captured and classified
        ``unknown`` here - it is never re-dispatched blindly and never allowed
        to leak as an exception, because both would erase the distinction the
        contract promises the consumer.
        """
        return self._lifecycle.cancel_execution(execution_key)

    def observe_execution(self, execution_key: str) -> ExecutionObservation:
        """Pure read of what this process currently knows (E-D2 supplement A).

        Dispatches nothing, writes nothing, and never invents a transition:
        ``NOT_KNOWN_TO_E`` is bounded knowledge, not a proof that nothing ever
        started - only a typed provider-side zero-creation fact may lift an
        ambiguous dispatch, and that proof arrives through the consumer's
        channel, never from this method.
        """
        return self._lifecycle.observe_execution(execution_key)

    def submit(self, request: ExecutionRequest) -> ExecutionReceipt:
        """Neutral start path - no business record is created, read, or
        inferred here (the caller issues ``execution_key`` after its own
        bookkeeping; persistence of ``correlation`` is the caller's).

        A replay of a key already tracked returns the original receipt and
        never re-dispatches the start. A typed refusal raised before the port
        exists left no dispatch behind, so it registers nothing and leaves the
        key clean for a fresh attempt.
        """
        return self._lifecycle.submit(
            request, port_factory=self.port_factory, on_event=self.on_event,
        )

    def _neutral_event(self, execution_id: str, kind: str, data: Mapping[str, Any]) -> None:
        self._lifecycle.note_native_event(
            execution_id, kind, data, on_event=self.on_event,
        )

    #: How long `stop()` waits for prompts and durable completions to settle.
    STOP_DEADLINE_SECONDS = 15.0

    def stop(self) -> bool:
        with self._lock:
            runs = list(self._active.values())
        for run in runs:
            # Answer deliberately discarded, same as the deleted bool shell:
            # stop() waits on run.done below, it does not project cancel facts.
            self.cancel_execution(run.turn_id)
        deadline = time.monotonic() + self.STOP_DEADLINE_SECONDS
        for run in runs:
            run.done.wait(max(0, deadline - time.monotonic()))
        # The prompt worker finishing is not the end of the turn: the completion
        # worker still writes the durable result through the shared Work Core
        # connection. Returning before it finishes let a later shutdown (or the
        # next test) reset that connection underneath it, which crashed the
        # interpreter inside SQLite. Wait for it, bounded, and report honestly.
        for thread in list(self._completion_threads):
            thread.join(max(0, deadline - time.monotonic()))
        with self._lock:
            native_ports = tuple(self._native_ports.values())
            self._native_ports.clear()
        for port in native_ports:
            port.stop()
        prompts_done = all(run.done.is_set() for run in runs)
        # Order 80: a run that never reached its terminal must not keep its
        # library's first-run lock (a later runtime in this process, or a
        # restart of the same data root, would wait on a dead owner).
        with self._lock:
            leftovers = [run for run in self._active.values()
                         if run.first_run_hold is not None]
        for run in leftovers:
            run.first_run_hold.release()
        with self._lock:
            # Keep the set meaning "workers still running": a finished worker is
            # retired here even if it was not started through the wrapper.
            self._completion_threads = {
                thread for thread in self._completion_threads if thread.is_alive()
            }
            completions_done = not self._completion_threads
        return prompts_done and completions_done


def _sidecar_attachments(
    objects, stored: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Project stored attachments into (native image attachments, file refs).

    Image bytes are read from the bounded object store only when the attachment
    carries a content digest; every other attachment stays a workspace file
    reference that the prompt text may name.
    """
    attachments: list[dict[str, Any]] = []
    file_refs: list[str] = []
    for item in (stored.get("message") or stored).get("attachments", ()):
        digest_value = item.get("_contentDigest")
        if not digest_value:
            continue
        if item.get("mediaKind") == "image":
            attachments.append({
                "mime": item.get("_mime") or "application/octet-stream",
                "filename": item.get("displayName") or item.get("ref"),
                "data": base64.b64encode(objects.read(digest_value)).decode(),
            })
        else:
            file_refs.append(str(item.get("ref")))
    return attachments, file_refs


def _effective_attachment_support(port, execution_id: str) -> bool:
    """Read the effective `attach` capability from the port's canonical view.

    The answer comes from the intersection of the deployment's static
    declaration and what this execution actually observed, never from a stored
    snapshot or from the mere presence of an attachment.
    """
    view = port.effective_capabilities(execution_id)
    for entry in view.get("capabilities", ()):
        if entry.get("id") == "attach":
            return bool(entry.get("supported"))
    return False


def _reclaim_subscription(run: "_Run") -> None:
    """Copy the declared working files back into the account asset.

    Every failure here is typed and recorded; none of them replace the stored
    asset (order 56 §1: never a half-way overwrite), and none of them fail the
    turn after the fact - the turn's own result is already durable.
    """
    subscription = getattr(run.port, "subscription", None)
    plumbing = getattr(run.port, "account_plumbing", None)
    if not subscription or not plumbing:
        return
    records, asset_store = plumbing
    account_id = subscription["account_id"]
    declared = subscription["files"]

    def stored_digest_of():
        _locator, digest = records.asset_reference(account_id)
        return digest

    try:
        read = getattr(run.port, "read_subscription", None)
        working = read(run.turn_id) if callable(read) else {}
        if not working:
            return
        locator, digest = asset_store.reclaim(
            account_id=account_id,
            stored_digest_of=stored_digest_of,
            materialized_digest=subscription.get("materialized_digest"),
            files=working,
            kind="subscription",
        )
        records.record_asset(account_id, locator=locator, digest=digest, state="valid")
    except BaseException as error:  # noqa: BLE001 - recorded, never silent
        logging.getLogger(__name__).warning(
            "turn %s: subscription reclaim for %s refused (%s); the stored "
            "asset is unchanged", run.turn_id, account_id,
            getattr(error, "code", type(error).__name__),
        )


def _audited_home(run: "_Run") -> tuple[dict[str, Any], bool]:
    """Audit the home of a finished attempt, applying the credential rule.

    An injected value found in the home means the one-shot projection leaked:
    the file that carries it is deleted (the home stays usable for the next
    turn), and the typed failure records the fact - the turn does not pass
    with a secret sitting in a durable directory.
    """
    try:
        audit, resumable = run.port.capture_execution(run.turn_id)
        # Order 51: read the declared usage journal while the execution's own
        # channel is still alive (after the final state, the sidecar is gone
        # and a read would arrive too late). The result rides on the run.
        usage_probe = getattr(run.port, "usage_probe", None)
        if usage_probe:
            try:
                run.usage_fact = run.port.read_usage(run.turn_id, usage_probe)
                run.usage_source = usage_probe.get("format")
            except BaseException as read_error:
                # A failed usage read must not fail the turn: the fact simply
                # stays unknown, and the reason is logged for the report.
                logging.getLogger(__name__).warning(
                    "turn %s: usage read failed (%s); usage stays unknown",
                    run.turn_id, read_error,
                )
                run.usage_fact = None
                run.usage_source = None
        # Order 56: reclaim the subscription working copy while the channel is
        # still alive. A reclaim that cannot take the account's lock, or that
        # finds the stored asset moved, is recorded and never overwrites the
        # asset - the working copy simply stays unclaimed.
        _reclaim_subscription(run)
        return audit, resumable
    except BaseException as exc:
        if getattr(exc, "code", None) == "SIDECAR_STATE_CONTAINS_SECRET":
            relative = getattr(exc, "path", None)
            disposition = _credential_hit_disposition(exc, run.port)
            if disposition == "keep-shared":
                logging.getLogger(__name__).warning(
                    "turn %s: credential material found in the shared session "
                    "library at %s; the shared file is left in place (order 66)",
                    run.turn_id, relative,
                )
            elif disposition == "delete" and relative:
                try:
                    run.port.delete_home_file(run.turn_id, relative)
                except BaseException:  # noqa: BLE001 - the leak failure stands
                    pass
        raise


def _resumable(port: SidecarHarnessPort, supported: bool, audit: Mapping[str, Any]) -> bool:
    # A native Agent owns its own session store; Server records only the opaque
    # session id. There is deliberately no file inventory of the user's home.
    return bool(supported and (isinstance(port, NativeHarnessPort) or audit["files"]))


def _credential_hit_disposition(exc: BaseException, port: Any) -> str:
    """What to do with one credential-hit audit failure (order 66 §2.5).

    ``keep-shared`` - the audited tree is the shared family library: the hit
    stays a typed failure, but the file must not be deleted (it may hold other
    Profiles' sessions). ``delete`` - a profile-scoped tree: the old rule, the
    leaked file is removed. ``none`` - not a credential hit at all.
    """
    if getattr(exc, "code", None) != "SIDECAR_STATE_CONTAINS_SECRET":
        return "none"
    return "keep-shared" if getattr(port, "shared_store", False) else "delete"


class CapabilityGateRefusal(SidecarError):
    """Raised only by :func:`_capability_gate`, before any native contact.

    单独的类型是来源隔离：只有这个类能携带“启动前拒绝”语义进入
    ``_CoreSidecarProvider.start`` 的转换分支；post-open 阶段的 sidecar 响应错误
    即使返回同名错误码（SidecarError 基类），也绝不会被误标为启动前拒绝。
    """

    def __init__(self, reason: str) -> None:
        super().__init__("CAPABILITY_REQUIREMENT_UNSATISFIED", reason)


class NativeProjectRefusal(CapabilityGateRefusal):
    """A typed project refusal proven before any native child can start."""

    def __init__(self, code: str) -> None:
        super().__init__("selected project is unavailable for native execution")
        self.code = code


class NativeSessionUnavailable(CapabilityGateRefusal):
    """A previous native conversation cannot be reopened without its channel."""

    def __init__(self) -> None:
        super().__init__("native session is no longer available; start a new session")
        self.code = "NATIVE_SESSION_UNAVAILABLE"


class SidecarRunRecoveryFailure(SidecarError):
    """Raised by the run-recovery path when a fresh sidecar cannot be obtained.

    Typed on purpose, like :class:`CapabilityGateRefusal`, and for the same
    reason: it is a statement about *this* stage — the sidecar was open and the
    prompt boundary failed — so ``_safe_code`` may publish its code. A bare
    ``SidecarError`` may not; see LNX-002 ruling decision 1.
    """

    def __init__(self, reason: str) -> None:
        super().__init__("SIDECAR_REBUILD_FAILED", reason)


def _capability_gate(port: SidecarHarnessPort, turn_id: str) -> None:
    """Refuse an execution whose slice capabilities are not provably satisfied.

    demand 取 launcher 本次将实际执行的挂载面（executable/projection/artifact
    的 target 与 state target）；grant/声明/授权集/环境绑定由装配边界注入。
    选择为确定性单候选（authorized_providers 限定）；任何缺失或不满足都在
    ``open_execution`` 之前抛出，调用方沿既有 fail_turn 路径持久化，零 spawn。
    """
    launcher = getattr(port, "launcher", None)
    if isinstance(port, NativeHarnessPort):
        # Native mode is a distinct, explicit composition. It has no room
        # mounts, projected credentials, or capability declarations to select.
        if not isinstance(launcher, NativeProcessLauncher):
            raise CapabilityGateRefusal("native mode requires the native launcher")
        if (port.credential_environment is not None or port.subscription is not None
                or port.capability_documents or port.capability_grants
                or port.capability_authorized_providers or port.capability_binding):
            raise CapabilityGateRefusal("native mode received isolated material")
        from ordessa_workspace.local_environment import LocalEnvironmentProvider
        try:
            normalized = LocalEnvironmentProvider().validate(port.directory)
        except ServerError as exc:
            raise NativeProjectRefusal(exc.code) from exc
        if normalized != port.directory or normalized != launcher.cwd:
            raise NativeProjectRefusal("NATIVE_PROJECT_CHANGED")
        return
    documents = getattr(port, "capability_documents", ())
    grants = getattr(port, "capability_grants", ())
    authorized = getattr(port, "capability_authorized_providers", ())
    binding = getattr(port, "capability_binding", None)
    if binding is None or not documents or not authorized:
        # 绑定、候选声明与授权提供者集是“装配边界已为本次执行注入材料”的最低
        # 标志；任一缺失即 fail-closed 拒绝（空面部署的合法空 grant 集不是缺失，
        # 但空的授权集不是“不限制”，而是未注入——不得改写为放行）。
        raise CapabilityGateRefusal(
            "capability material incomplete for this execution: "
            "binding/documents/authorized required",
        )
    executable_targets = tuple(
        target for _source, target in getattr(launcher, "executable_mounts", ())
    )
    projection_targets = tuple(
        target for _source, target in getattr(launcher, "projection_mounts", ())
    )
    artifact_targets = tuple(
        target for _source, target in getattr(launcher, "runtime_artifact_mounts", ())
    )
    state_target = getattr(launcher, "state_target", None)
    requirements = capability.sidecar_requirements(
        executable_targets=executable_targets,
        projection_targets=projection_targets,
        artifact_targets=artifact_targets,
        state_target=state_target,
    )
    context = capability.MatchContext(environment_binding=binding, now=int(time.time()))
    record = capability.select_declaration(
        requirements, grants, (), tuple(documents),
        context=context, binding=f"turn:{turn_id}",
        authorized_providers=tuple(authorized),
    )
    if record.selected is not None and record.outcome is not None and record.outcome.satisfied:
        return
    if record.rejected:
        _provider, _revision, reason = record.rejected[0]
    elif record.outcome is not None and record.outcome.refusals:
        reason = record.outcome.refusals[0].reason
    else:
        reason = "no authorized candidate satisfied the requirements"
    raise CapabilityGateRefusal(
        f"capability requirements unsatisfied for this execution: {reason}",
    )


#: The codes a **pre-start refusal** owns. They are claims about a stage - "the
#: start was refused before any native contact" - and only
#: :class:`CapabilityGateRefusal` may make that claim. A post-open failure that
#: merely reuses one of these strings is not making that claim, so the ambiguous
#: stage must not publish it (LNX-002 ruling, decision 1).
#:
#: This is the mirror of a global allow-list, not a copy of one: the vocabulary is
#: owned by the type that raises it, and the same string published from a genuine
#: pre-start refusal stays correct - that path is an ``ExecutionStartRejected`` and
#: never reaches the check in ``_safe_code``.
PRE_START_REFUSAL_CODES = frozenset({
    "CAPABILITY_REQUIREMENT_UNSATISFIED", "NATIVE_PROJECT_CHANGED",
    "LOCAL_PATH_INVALID", "LOCAL_PATH_MISSING", "LOCAL_PATH_NOT_READABLE",
    "LOCAL_PATH_NOT_DIRECTORY", "LOCAL_PATH_UNAVAILABLE", "LOCAL_PATH_FORBIDDEN",
})



def _safe_code(exc: BaseException) -> str:
    # 先沿异常链寻找由 provider 显式标注的「启动未发生」拒绝码（gate 在
    # open_execution 前抛出的 ExecutionStartRejected 会带上原因码）；只有这一类
    # 带码的 ExecutionStartRejected 参与还原，其他包装/运行期异常保持既有归一化。
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ExecutionStartRejected):
            explicit = getattr(current, "code", None)
            if isinstance(explicit, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", explicit):
                return explicit
        current = current.__cause__ or current.__context__
    if isinstance(exc, DispatchAmbiguous) and getattr(exc, "code", None) in PRE_START_REFUSAL_CODES:
        # LNX-002 ruling, decision 1. The ambiguous stage asserts one thing only:
        # we cannot tell whether the start and its side effects happened. A code
        # that belongs to the pre-start refusal vocabulary is a claim about a
        # stage this stage cannot make, so the *published* reason stays generic and
        # the original cause stays on the chain (and on this log).
        #
        # A genuine pre-start refusal never reaches here: it is an
        # `ExecutionStartRejected` and the walk above already returned its code.
        # Every other post-open code is still published - order 150's
        # HARNESS_LAUNCH_FAILED / HARNESS_SESSION_UNAVAILABLE are exactly the
        # diagnoses the client needs, and they are not stage claims.
        logging.getLogger(__name__).error(
            "ambiguous dispatch keeps the generic reason: it carried a pre-start "
            "refusal code, which says nothing about whether the start happened",
            exc_info=exc)
        return "EXECUTION_FAILED"
    explicit = getattr(exc, "code", None)
    value = str(explicit or exc).strip().upper()
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", value):
        return value
    # The typed event can only carry a code; keep the underlying cause visible
    # on the server log or a generic EXECUTION_FAILED hides it entirely.
    logging.getLogger(__name__).error(
        "execution failed without a typed code", exc_info=exc)
    return "EXECUTION_FAILED"


#: ACP's official clean stop reasons only (C-HARNESS@v1 D1 官方5值中的干净集；
#: "stop"/"complete" 系历史自造，随 R1 移出——非干净值一律透传落库)。
_CLEAN_STOP_REASONS = frozenset({"end_turn", ""})


def _terminal_reason_from_result(result) -> str | None:
    """Order 134 (122 consumer side): a harness completion may report *why* it
    stopped. Return a persisted terminal_reason only when the result actually
    says the turn stopped for a non-clean reason (e.g. ``max_tokens``); a
    missing field or a clean end returns ``None`` so behavior is byte-identical
    to before. We never invent a reason the Worker did not send.
    """
    if not isinstance(result, dict):
        return None
    stop = result.get("stopReason") or result.get("stop_reason")
    if not isinstance(stop, str) or stop.strip().lower() in _CLEAN_STOP_REASONS:
        return None
    return stop
