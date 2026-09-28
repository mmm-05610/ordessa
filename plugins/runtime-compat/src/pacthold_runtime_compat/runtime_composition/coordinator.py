"""Host-owned composition of already selected runtime providers.

This module has no provider-name branches.  A host supplies resolved provider
ports for the frozen binding; the coordinator only validates their declared
capabilities/affinity and owns the durable attempt ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .protocol import (
    AttachDescriptor, CapabilityStatus, CompositionAttemptRecord,
    CompositionErrorCode, CompositionPreflightReceipt, CompositionRejected,
    HarnessCommandSpec, RuntimeBinding, RuntimeBundle, StartAmbiguous,
    TerminalRunHandle, attempt_key, digest,
)


@dataclass(frozen=True)
class ResolvedComposition:
    host: object
    sandbox: object
    terminal: object


class RuntimeCompositionCoordinator:
    """The sole authorization and replay boundary for one composition attempt."""

    def __init__(self, resolver: Callable[[RuntimeBinding], ResolvedComposition],
                 *, bundle_factory: Callable[[object, HarnessCommandSpec, str, str], RuntimeBundle]) -> None:
        self._resolver = resolver
        # The projector's declared plan is the only bundle source; there is no
        # empty/default plan fallback.
        self._bundle_factory = bundle_factory
        self.ledger: dict[str, CompositionAttemptRecord] = {}
        self._handles: dict[str, TerminalRunHandle] = {}
        self._cleanup: dict[str, tuple[object, object, object, object]] = {}
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
        refs = (binding.runtime_host_ref, binding.sandbox_ref, binding.terminal_session_ref)
        if len({ref.affinity for ref in refs}) != 1:
            return CompositionPreflightReceipt(digest(binding), digest("affinity-rejected"), False, binding.runtime_host_ref.affinity, "AFFINITY_MISMATCH")
        # Capabilities are deliberately semantic, not provider IDs. An
        # undeclared capability is a refusal: "no answer" must never pass as
        # "supported" (Work Order 47 - the old `None` branch was exactly that).
        for component, capability in ((resolved.host, "process.spawn.typed@1"), (resolved.sandbox, "isolation.wrap@1"), (resolved.terminal, "terminal.run@1")):
            value = self._capability_value(component, capability)
            if value is None:
                return CompositionPreflightReceipt(digest(binding), digest((capability, "undeclared")), False, binding.runtime_host_ref.affinity, "CAPABILITY_UNDECLARED", capability)
            if value not in (CapabilityStatus.SUPPORTED, "supported"):
                return CompositionPreflightReceipt(digest(binding), digest((capability, value)), False, binding.runtime_host_ref.affinity, "CAPABILITY_UNSUPPORTED", capability)
        return CompositionPreflightReceipt(digest(binding), digest((binding, "accepted")), True, binding.runtime_host_ref.affinity)

    def start(self, binding: RuntimeBinding, command: HarnessCommandSpec, *, execution_id: str, dispatch_id: str) -> TerminalRunHandle:
        resolved = self._resolver(binding)
        network_mode = getattr(binding.sandbox_ref, "network_mode", "none")
        if command.requires_control_plane_network and network_mode != "inherit":
            raise CompositionRejected(CompositionErrorCode.CAPABILITY_UNSUPPORTED, "CONTROL_PLANE_NETWORK_REQUIRED")
        preflight = self.preflight(binding, resolved)
        if not preflight.accepted:
            detail = preflight.rejection_code or ""
            if getattr(preflight, "rejection_capability", None):
                detail = f"{detail}:{preflight.rejection_capability}"
            raise CompositionRejected(CompositionErrorCode.AFFINITY_MISMATCH if preflight.rejection_code == "AFFINITY_MISMATCH" else CompositionErrorCode.CAPABILITY_UNSUPPORTED, detail)
        bundle = self._bundle_factory(resolved.host, command, execution_id, dispatch_id)
        stage = getattr(resolved.host, "stage", None)
        if callable(stage):
            bundle = stage(bundle)
        key = attempt_key(execution_id=execution_id, dispatch_id=dispatch_id,
                          ref_digests=(binding.runtime_host_ref.identity_digest, binding.sandbox_ref.policy_digest, binding.terminal_session_ref.session_digest),
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
            return self._handles[key]
        # wrap and allocation have no target side effect.  RUN_INTENT is
        # recorded immediately before the one public TerminalSession.run call.
        isolated = resolved.sandbox.wrap(bundle.mount_plan, command, attempt_key=key)
        allocation = resolved.terminal.allocate()
        self._cleanup[key] = (resolved.host, resolved.sandbox, resolved.terminal, isolated)
        self.ledger[key] = CompositionAttemptRecord(key, "RUN_INTENT_RECORDED")
        try:
            handle = resolved.terminal.run(resolved.host.transport, isolated, key)
        except StartAmbiguous:
            self.ledger[key] = CompositionAttemptRecord(key, "AMBIGUOUS", True, 1)
            raise
        except Exception:
            # A provider may have accepted an opaque submit before its response
            # fails.  Treat it as ambiguous; do not blindly replay.
            self.ledger[key] = CompositionAttemptRecord(key, "AMBIGUOUS", True, 1)
            raise
        self.ledger[key] = CompositionAttemptRecord(key, "RUNNING", True, 1, handle.native_correlation)
        self._handles[key] = handle
        return handle

    def present(self, handle: TerminalRunHandle, presenter: object) -> bool:
        """Best-effort presentation; a Presenter gets only AttachDescriptor."""
        descriptor = handle.attach_descriptor
        if descriptor is None:
            return False
        try:
            presenter.open(descriptor)
        except Exception:
            return False
        return True

    def cleanup(self, attempt: str) -> dict[str, object]:
        """Idempotent inner-to-outer compensation; never changes completion."""
        parts = self._cleanup.get(attempt)
        if not parts:
            return {"status": "already_cleaned"}
        host, sandbox, terminal, isolated = parts
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
            terminal_release = terminal.release
        except AttributeError:
            terminal_release = None
        if callable(terminal_release):
            try:
                results["terminal"] = terminal_release()
            except Exception as exc:
                results["terminal"] = {"error": str(exc)[:240]}
        try:
            host_cleanup = host.cleanup
        except AttributeError:
            host_cleanup = None
        if callable(host_cleanup):
            try:
                results["host"] = host_cleanup()
            except Exception as exc:
                results["host"] = {"error": str(exc)[:240]}
        self._cleanup.pop(attempt, None)
        return results or {"status": "cleaned"}
