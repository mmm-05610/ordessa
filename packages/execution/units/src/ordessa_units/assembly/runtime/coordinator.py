"""Unit-owned composition of already selected runtime providers.

This module has no provider-name branches.  A host supplies resolved provider
ports for the frozen binding; the coordinator only validates their declared
capabilities/affinity and retains process-local attempt details below Core durable dispatch.

The v1 composition binds one runtime host to one sandbox and has no terminal:
``Sandbox.wrap`` produces the frozen :class:`IsolatedProcessSpec` and
``Sandbox.launch`` performs the real spawn, returning the single managed
:class:`ProcessHandle`.  ``start`` returns a :class:`CompositionExecution`
carrying that handle together with the spec, the attempt key, the resolved
host/sandbox refs and the preflight/staging receipts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from ordessa_environments.composition import (
    CompositionAttemptRecord,
    CompositionErrorCode,
    CompositionPreflightReceipt,
    CompositionRejected,
    IsolatedProcessSpec,
    ProcessHandle,
    RuntimeBinding,
    RuntimeBundle,
    RuntimeBundleInput,
    RuntimeHostRef,
    RuntimePreparationRejected,
    SandboxRef,
    StartAmbiguous,
    attempt_key,
)
from ordessa_environments.definitions.runtime_resources import CapabilityStatus
from ordessa_execution_agents.harness.definitions.command_projection import HarnessCommandSpec
from ordessa_infrastructure.encoding.content_identity import digest


@dataclass(frozen=True)
class ResolvedComposition:
    """The already-resolved v1 provider ports for one frozen binding."""

    host: object
    sandbox: object


@dataclass(frozen=True)
class CompositionExecution:
    """One launched v1 composition attempt and its receipts.

    ``handle`` is the single managed process owner returned by
    ``Sandbox.launch``; ``spec`` is the frozen projection that was launched;
    ``attempt_key`` is the composition fuse identity; ``host_ref`` /
    ``sandbox_ref`` are the resolved provider identities; ``preflight`` is the
    accepted capability/affinity receipt; ``staged_bundle`` is the host's
    staging receipt (the bundle ``RuntimeHost.stage`` returned).  Holding this
    value is not an exit, completion or compensation claim.
    """

    handle: ProcessHandle
    spec: IsolatedProcessSpec
    attempt_key: str
    host_ref: RuntimeHostRef
    sandbox_ref: SandboxRef
    preflight: CompositionPreflightReceipt
    staged_bundle: RuntimeBundleInput


class RuntimeCompositionCoordinator:
    """Per-process no-resend fuse for an already admitted composition attempt."""

    def __init__(self, resolver: Callable[[RuntimeBinding], ResolvedComposition],
                 *, bundle_factory: Callable[[object, HarnessCommandSpec, str, str], RuntimeBundle]) -> None:
        self._resolver = resolver
        # The projector's declared plan is the only bundle source; there is no
        # empty/default plan fallback.
        self._bundle_factory = bundle_factory
        self.ledger: dict[str, CompositionAttemptRecord] = {}
        self._executions: dict[str, CompositionExecution] = {}
        #: attempt -> (host, sandbox, spec, execution_id, handle); the handle is
        #: filled in only after ``Sandbox.launch`` returned one.
        self._cleanup: dict[str, tuple[object, object, object, str, object]] = {}
        self._projections: dict[str, dict[str, object]] = {}

    def projection_receipt(self, attempt_key: str) -> dict[str, object]:
        """Bounded, honest PROJECTED-level view of one attempt's plan.

        Describes the verified projection (plan/bundle digests, declared
        sources with their content digests and guest targets, projector and
        sandbox identities).  It never claims LOADED or CONSUMED evidence.
        """
        try:
            return dict(self._projections[attempt_key])
        except KeyError as exc:
            raise KeyError(f"no projection receipt for attempt: {attempt_key}") from exc

    @staticmethod
    def _capability_value(component: object, name: str) -> object:
        caps = getattr(component, "capabilities", None)
        # A capability table is either a `CapabilitySet` (its `.values` is a
        # mapping) or a plain mapping. `getattr(caps, "values", caps)` was
        # wrong for the plain-mapping case: a dict's `.values` is a *method*,
        # so every dict-declaring component read as undeclared. The old
        # `None`-passes branch hid this; Order 47's explicit refusal exposed it.
        inner = getattr(caps, "values", None)
        values = inner if isinstance(inner, Mapping) else caps
        return values.get(name) if isinstance(values, Mapping) else None

    def preflight(self, binding: RuntimeBinding, resolved: ResolvedComposition | None = None) -> CompositionPreflightReceipt:
        resolved = resolved or self._resolver(binding)
        refs = (binding.runtime_host_ref, binding.sandbox_ref)
        if len({ref.affinity for ref in refs}) != 1:
            return CompositionPreflightReceipt(digest(binding), digest("affinity-rejected"), False, binding.runtime_host_ref.affinity, "AFFINITY_MISMATCH")
        # Capabilities are deliberately semantic, not provider IDs. An
        # undeclared capability is a refusal: "no answer" must never pass as
        # "supported" (Work Order 47 - the old `None` branch was exactly that).
        for component, capability in ((resolved.host, "process.spawn.typed@1"), (resolved.sandbox, "isolation.wrap@1")):
            value = self._capability_value(component, capability)
            if value is None:
                return CompositionPreflightReceipt(digest(binding), digest((capability, "undeclared")), False, binding.runtime_host_ref.affinity, "CAPABILITY_UNDECLARED", capability)
            if value not in (CapabilityStatus.SUPPORTED, "supported"):
                return CompositionPreflightReceipt(digest(binding), digest((capability, value)), False, binding.runtime_host_ref.affinity, "CAPABILITY_UNSUPPORTED", capability)
        return CompositionPreflightReceipt(digest(binding), digest((binding, "accepted")), True, binding.runtime_host_ref.affinity)

    def _check_preparation(self, binding: RuntimeBinding, command: HarnessCommandSpec, *, resolved: ResolvedComposition | None = None) -> tuple[ResolvedComposition, CompositionPreflightReceipt]:
        """Classify only this deterministic gate before any provider callback."""
        resolved = resolved if resolved is not None else self._resolver(binding)
        network_mode = getattr(binding.sandbox_ref, "network_mode", "none")
        if command.requires_control_plane_network and network_mode != "inherit":
            raise CompositionRejected(CompositionErrorCode.CAPABILITY_UNSUPPORTED, "CONTROL_PLANE_NETWORK_REQUIRED")
        preflight = self.preflight(binding, resolved)
        if not preflight.accepted:
            detail = preflight.rejection_code or ""
            if getattr(preflight, "rejection_capability", None):
                detail = f"{detail}:{preflight.rejection_capability}"
            raise CompositionRejected(CompositionErrorCode.AFFINITY_MISMATCH if preflight.rejection_code == "AFFINITY_MISMATCH" else CompositionErrorCode.CAPABILITY_UNSUPPORTED, detail)
        return resolved, preflight

    def prepare_start(self, binding: RuntimeBinding, command: HarnessCommandSpec) -> None:
        """Expose only the deterministic gate for the provider's error mapping."""
        resolved = self._resolver(binding)
        try:
            self._check_preparation(binding, command, resolved=resolved)
        except CompositionRejected as exc:
            raise RuntimePreparationRejected(str(exc), code=exc.code) from exc

    def start(self, binding: RuntimeBinding, command: HarnessCommandSpec, *, execution_id: str, dispatch_id: str) -> CompositionExecution:
        resolved, preflight = self._check_preparation(binding, command)
        bundle = self._bundle_factory(resolved.host, command, execution_id, dispatch_id)
        key = attempt_key(execution_id=execution_id, dispatch_id=dispatch_id,
                          ref_digests=(binding.runtime_host_ref.identity_digest, binding.sandbox_ref.policy_digest),
                          preflight_digest=preflight.capability_digest, bundle_digest=bundle.bundle_digest,
                          command_digest=command.digest, mount_plan_digest=bundle.mount_plan.digest)
        self._projections[key] = {
            "projector_id": command.projector_id,
            "sandbox_provider": binding.sandbox_ref.provider,
            "plan_digest": bundle.mount_plan.digest,
            "bundle_digest": bundle.bundle_digest,
            "secret_mounts": len(bundle.mount_plan.secret_mounts),
            "sources": tuple(
                {
                    "kind": source.kind,
                    "provenance": source.provenance,
                    "guest_target": source.guest_target,
                    "access": source.access,
                    "expected_digest": source.expected_digest,
                    "authorized_scope": source.authorized_scope,
                }
                for source in command.runtime_sources
            ),
            "status": "PROJECTED",
            "warnings": (),
        }
        prior = self.ledger.get(key)
        if prior:
            if prior.state == "AMBIGUOUS":
                raise StartAmbiguous("replay remains START_AMBIGUOUS")
            execution = self._executions.get(key)
            if execution is None:
                # Intent was recorded but no execution was ever retained: the
                # only honest answer is that the attempt may have taken effect.
                raise StartAmbiguous("replay of an attempt with no retained execution")
            return execution
        # RUN_INTENT is recorded immediately before the first provider callback
        # that may create a target (host staging, then the one public
        # Sandbox.launch call).  A provider may have accepted an opaque effect
        # before its response fails, so any failure after this point is
        # conservatively ambiguous and is never blindly replayed.
        self.ledger[key] = CompositionAttemptRecord(key, "RUN_INTENT_RECORDED")
        try:
            staged = resolved.host.stage(bundle)
            isolated = resolved.sandbox.wrap(staged.mount_plan, command, attempt_key=key)
            self._cleanup[key] = (resolved.host, resolved.sandbox, isolated, execution_id, None)
            handle = resolved.sandbox.launch(isolated, attempt_key=key)
        except StartAmbiguous:
            self.ledger[key] = CompositionAttemptRecord(key, "AMBIGUOUS", True, 1)
            raise
        except Exception:
            self.ledger[key] = CompositionAttemptRecord(key, "AMBIGUOUS", True, 1)
            raise
        self._cleanup[key] = (resolved.host, resolved.sandbox, isolated, execution_id, handle)
        self.ledger[key] = CompositionAttemptRecord(key, "RUNNING", True, 1, getattr(handle, "identity", None))
        execution = CompositionExecution(
            handle=handle,
            spec=isolated,
            attempt_key=key,
            host_ref=resolved.host.ref,
            sandbox_ref=resolved.sandbox.ref,
            preflight=preflight,
            staged_bundle=staged,
        )
        self._executions[key] = execution
        return execution

    def cleanup(self, attempt: str) -> dict[str, object]:
        """Idempotent inner-to-outer compensation; never changes completion."""
        parts = self._cleanup.get(attempt)
        if not parts:
            return {"status": "already_cleaned"}
        host, sandbox, isolated, execution_id, handle = parts
        results: dict[str, object] = {}
        # C-RUNTIME@v1 §1 (INC2-A): the compensation verbs are named here
        # statically - no string-verb duck dispatch. A port that never grew
        # the verb keeps the conservative skip every pre-capability provider
        # has always had (its missing attribute is not a failure); a verb
        # that raises keeps the error fact and the remaining components are
        # still compensated independently. Routing is byte-identical to the
        # retired duck dispatch for every existing provider shape.
        try:
            sandbox_cleanup = sandbox.cleanup
        except AttributeError:
            sandbox_cleanup = None
        if callable(sandbox_cleanup):
            try:
                results["sandbox"] = (sandbox_cleanup(isolated)
                                      if isolated is not None else sandbox_cleanup())
            except Exception as exc:  # independent cleanup continues
                results["sandbox"] = {"error": str(exc)[:240]}
        try:
            host_cleanup = host.cleanup
        except AttributeError:
            host_cleanup = None
        if callable(host_cleanup):
            try:
                results["host"] = host_cleanup(execution_id)
            except Exception as exc:
                results["host"] = {"error": str(exc)[:240]}
        try:
            process_release = handle.release
        except AttributeError:
            process_release = None
        if callable(process_release):
            try:
                # Release is not an exit claim: it hands back the process owner
                # receipt and never asserts that the process exited.
                results["process"] = process_release()
            except Exception as exc:
                results["process"] = {"error": str(exc)[:240]}
        self._cleanup.pop(attempt, None)
        return results or {"status": "cleaned"}
