"""Controlled C4 configuration service slice over public Harness/Server DTOs.

The carrier, authenticated principal, permit verifier and runtime observer are
injected. No business implementation or Server host internal is imported.
Only an operation-bound native owner receipt, verified readback and adapter
Match can produce Confirmed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, ApplicationTarget, Assessment, ConfigurationCapabilities,
    ConfigurationCapability, Confirmed, DesiredFragment, ErrorCode, Match,
    NotFound, OperationRecord, Plan, Refused, Unknown,
)
from ordessa_harness_api.intents import (
    BindSecret, IntentSet, IntentSource, InvokeAction, MountContent, RemoveOwnedContent,
    ResetField, SetField,
)

from ..contributions import CONFIGURATION_POINT, admitted_descriptor
from ..materialization import (
    AuthorizedIntents, IntentMergeError, MaterializationError, MergeAuthority, PublishedGeneration,
    materialize_generation, merge_intents, preflight_generation,
)
from .operation_journal import FenceObservation, NativeActivationReceipt, OperationJournal


@dataclass(frozen=True)
class RuntimeSnapshot:
    target: ApplicationTarget
    context: AdapterContext
    authority: MergeAuthority
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
    receipt: NativeActivationReceipt | None = None


class ControlledRuntime(Protocol):
    def capture(self, target: ApplicationTarget) -> RuntimeSnapshot: ...
    def activate_generation(self, operation_id: str, target: ApplicationTarget,
                            lease: PublishedGeneration, manifest_digest: str) -> NativeActivationReceipt: ...
    def observe(self, target: ApplicationTarget) -> NativeReadback: ...


class PermitVerifier(Protocol):
    def verify(self, principal: str, target: ApplicationTarget, plan: Plan,
               operation_key: str, permit: str) -> bool: ...


@dataclass(frozen=True)
class _Prepared:
    plan: Plan
    fragments: tuple[DesiredFragment, ...]
    selections: tuple[_Selection, ...]
    merged: object


@dataclass(frozen=True)
class _Selection:
    owner: str
    publication_token: str
    descriptor: object


class _CompileRefusal(ValueError):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code


def _digest(fragments: tuple[DesiredFragment, ...]) -> str:
    encoded = json.dumps([asdict(item) for item in fragments], sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _manifest_digest(files: tuple[tuple[tuple[str, ...], str], ...]) -> str:
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _refused(code: ErrorCode, message: str) -> Refused:
    return Refused(code, (message,), True)


def _has_claim(descriptor, intent) -> bool:
    claims = descriptor.claims
    if isinstance(intent, (SetField, ResetField)):
        return any(claim.target_kind == "file" and claim.target_id == intent.target.handle_id and
                   intent.field_path.segments[:len(claim.field_path)] == claim.field_path for claim in claims)
    if isinstance(intent, (MountContent, RemoveOwnedContent)):
        return any(claim.target_kind == "directory" and claim.target_id == intent.target.handle_id and
                   tuple(intent.relative_name.split("/"))[:len(claim.field_path)] == claim.field_path for claim in claims)
    if isinstance(intent, BindSecret):
        return any(claim.target_kind == "environment" and claim.target_id == intent.target.handle_id and
                   (intent.slot,)[:len(claim.field_path)] == claim.field_path for claim in claims)
    return isinstance(intent, InvokeAction) and False  # action claims need a separate explicit grant


def _bind_fragment_source(compiled: IntentSet, fragment: DesiredFragment,
                          batch_item_ids: frozenset[str]) -> IntentSet:
    """Replace the adapter's untrusted item label with the C4 fragment identity.

    The public C2 compile call has no fragment item argument. The service
    owns that identity and binds it before merge admission; an adapter cannot
    nominate a different item in this batch or change facet/schema identity.
    """
    rebound = []
    for intent in compiled.intents:
        source = intent.source
        if (source.facet_id != fragment.facet_id or
                source.contribution_version != fragment.schema_version):
            raise ValueError("adapter source facet or version differs from authorized fragment")
        if source.item_id != fragment.item_id and source.item_id in batch_item_ids:
            raise ValueError("adapter source aliases another authorized item")
        trusted_source = IntentSource(fragment.facet_id, fragment.item_id,
                                      fragment.schema_version)
        rebound.append(replace(intent, source=trusted_source))
    return IntentSet(tuple(rebound))


class ConfigurationApplicationService:
    """C4 facade for one authenticated principal and one controlled runtime.

    The host supplies ``carrier.use_contribution``. This first slice supports
    one unambiguous configuration contribution, JSON/content materialization,
    and a runtime whose readback can report exact generation file digests.
    There is no default permit or native executor.
    """

    def __init__(self, *, principal: str, target: ApplicationTarget, carrier: object, runtime: ControlledRuntime,
                 permits: PermitVerifier, journal: OperationJournal,
                 clock: Callable[[], datetime] | None = None):
        if not principal or not isinstance(target, ApplicationTarget) or carrier is None or runtime is None or permits is None:
            raise ValueError("authenticated composition dependencies required")
        self.principal = principal
        self.target = target
        self.carrier = carrier
        self.runtime = runtime
        self.permits = permits
        self.journal = journal
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._prepared: dict[str, _Prepared] = {}
        self._apply_lock = RLock()

    def _snapshot(self, target: ApplicationTarget) -> RuntimeSnapshot:
        if target != self.target:
            raise ValueError("service target identity changed")
        snapshot = self.runtime.capture(target)
        if snapshot.target != target:
            raise ValueError("runtime snapshot target identity changed")
        return snapshot

    def _adapter_support_error(self, adapter, descriptor, snapshot: RuntimeSnapshot,
                               request: object) -> ErrorCode | None:
        installation = snapshot.context.installation
        if installation.native_version is None:
            return ErrorCode.VERSION_UNVERIFIED
        if (snapshot.context.entry not in descriptor.entries or
                descriptor.harness_id != installation.harness_id or
                descriptor.native_versions.contains(installation.native_version) is not True or
                descriptor.adapter_versions.contains(installation.adapter_version) is not True):
            return ErrorCode.CAPABILITY_UNSUPPORTED
        assessment = adapter.assess(snapshot.context, request)
        if not isinstance(assessment, Assessment):
            return ErrorCode.CAPABILITY_UNSUPPORTED
        return None if assessment.status == "supported" else ErrorCode.CAPABILITY_UNSUPPORTED

    def _published_selections(self) -> tuple[_Selection, ...]:
        """Enumeration is only a hint; every use below acquires an exact hold."""
        enumerate_views = getattr(self.carrier, "contributions", None)
        if not callable(enumerate_views):
            return ()
        selections = []
        for view in enumerate_views(CONFIGURATION_POINT):
            try:
                descriptor = admitted_descriptor(view.payload, view.owner, CONFIGURATION_POINT)
            except (AttributeError, ValueError):
                continue
            token = getattr(view, "publication_token", None)
            if isinstance(token, str) and token and isinstance(view.owner, str) and view.owner:
                selections.append(_Selection(view.owner, token, descriptor))
        return tuple(selections)

    @staticmethod
    def _matches(selection: _Selection, snapshot: RuntimeSnapshot,
                 fragment: DesiredFragment | None = None) -> bool:
        descriptor = selection.descriptor
        installation = snapshot.context.installation
        if (installation.native_version is None or
                descriptor.harness_id != installation.harness_id or
                snapshot.context.entry not in descriptor.entries or
                descriptor.native_versions.contains(installation.native_version) is not True or
                descriptor.adapter_versions.contains(installation.adapter_version) is not True):
            return False
        return fragment is None or (descriptor.facet_id == fragment.facet_id and
                                    descriptor.facet_schema_version == fragment.schema_version)

    def _select_fragments(self, snapshot: RuntimeSnapshot,
                          fragments: tuple[DesiredFragment, ...]) -> tuple[_Selection, ...]:
        if snapshot.context.installation.native_version is None:
            raise _CompileRefusal(ErrorCode.VERSION_UNVERIFIED, "native version is unobserved")
        published = self._published_selections()
        if not published:
            raise _CompileRefusal(ErrorCode.ADAPTER_MISSING, "configuration adapter absent")
        chosen = []
        for fragment in fragments:
            matches = [item for item in published if self._matches(item, snapshot, fragment)]
            if not matches:
                raise _CompileRefusal(ErrorCode.CAPABILITY_UNSUPPORTED,
                                      "no configuration adapter matches fragment and runtime")
            if len(matches) != 1:
                raise _CompileRefusal(ErrorCode.TARGET_CONFLICT,
                                      "configuration adapter selection is ambiguous")
            chosen.append(matches[0])
        return tuple(chosen)

    def _lease_selections(self, stack: ExitStack, selections: tuple[_Selection, ...],
                          snapshot: RuntimeSnapshot,
                          fragments: tuple[DesiredFragment | None, ...]) -> tuple[object, ...]:
        exact = getattr(self.carrier, "use_contribution_exact", None)
        if not callable(exact):
            raise _CompileRefusal(ErrorCode.ADAPTER_MISSING, "exact contribution lease unavailable")
        held: dict[tuple[str, str], object] = {}
        for selection in selections:
            key = (selection.owner, selection.publication_token)
            if key in held:
                continue
            view = stack.enter_context(exact(CONFIGURATION_POINT, owner=selection.owner,
                                             publication_token=selection.publication_token,
                                             consumer=None))
            if (not hasattr(view, "payload") or view.owner != selection.owner or
                    getattr(view, "publication_token", None) != selection.publication_token):
                raise _CompileRefusal(ErrorCode.ADAPTER_MISSING,
                                      "configuration publication changed before lease")
            try:
                current = admitted_descriptor(view.payload, view.owner, CONFIGURATION_POINT)
            except ValueError as exc:
                raise _CompileRefusal(ErrorCode.ADAPTER_MISSING,
                                      "configuration admission changed") from exc
            if current != selection.descriptor:
                raise _CompileRefusal(ErrorCode.ADAPTER_MISSING,
                                      "configuration descriptor changed before lease")
            held[key] = view
        for selection, fragment in zip(selections, fragments):
            if not self._matches(selection, snapshot, fragment):
                raise _CompileRefusal(ErrorCode.CAPABILITY_UNSUPPORTED,
                                      "leased adapter does not match fragment and runtime")
        return tuple(held[(item.owner, item.publication_token)] for item in selections)

    def inspect(self, target: ApplicationTarget) -> ConfigurationCapabilities:
        snapshot = self._snapshot(target)
        matches = tuple(item for item in self._published_selections()
                        if self._matches(item, snapshot))
        counts: dict[tuple[str, str], int] = {}
        for item in matches:
            key = (item.descriptor.facet_id, item.descriptor.facet_schema_version)
            counts[key] = counts.get(key, 0) + 1
        capabilities = []
        for item in matches:
            descriptor = item.descriptor
            key = (descriptor.facet_id, descriptor.facet_schema_version)
            if counts[key] != 1:
                supported = False
                reason = "configuration adapter selection is ambiguous"
            else:
                try:
                    with ExitStack() as stack:
                        view = self._lease_selections(stack, (item,), snapshot, (None,))[0]
                        supported = self._adapter_support_error(
                            view.payload, descriptor, snapshot, {}) is None
                    reason = "operation lacks explicit adapter proof"
                except _CompileRefusal:
                    supported = False
                    reason = "configuration publication unavailable"
            capabilities.extend(ConfigurationCapability(
                descriptor.facet_id, descriptor.harness_id,
                snapshot.context.installation.native_version,
                snapshot.context.installation.adapter_version,
                snapshot.context.entry, snapshot.context.scope, operation,
                "supported" if supported and operation == "set" else "unknown",
                snapshot.context.capability_evidence_ref if supported and operation == "set" else None,
                None if supported and operation == "set" else reason)
                for operation in ("set", "reset"))
        return ConfigurationCapabilities(target, tuple(capabilities))

    def _compile(self, snapshot: RuntimeSnapshot, fragments: tuple[DesiredFragment, ...],
                 adapter, owner: str):
        descriptor = admitted_descriptor(adapter, owner, CONFIGURATION_POINT)
        return self._compile_bound(snapshot, fragments,
                                   tuple((adapter, owner, descriptor) for _ in fragments))

    def _compile_bound(self, snapshot: RuntimeSnapshot,
                       fragments: tuple[DesiredFragment, ...],
                       bindings: tuple[tuple[object, str, object], ...]):
        if len(bindings) != len(fragments):
            raise ValueError("every fragment needs one exact adapter binding")
        submissions: list[AuthorizedIntents] = []
        batch_item_ids = frozenset(fragment.item_id for fragment in fragments)
        for fragment, (adapter, owner, descriptor) in zip(fragments, bindings):
            if fragment.facet_id != descriptor.facet_id or fragment.schema_version != descriptor.facet_schema_version:
                raise ValueError("fragment facet/schema not covered by adapter")
            request = fragment.value if fragment.operation == "set" else None
            if fragment.operation == "set":
                descriptor.payload_schema.validate(request)
            support_error = self._adapter_support_error(adapter, descriptor, snapshot, request)
            if support_error is not None:
                raise _CompileRefusal(support_error, "adapter assessment or native version unsupported")
            compiled = adapter.compile(snapshot.context, snapshot.before_value, request)
            if isinstance(compiled, AdapterRefusal):
                raise _CompileRefusal(compiled.code, compiled.reason)
            if not isinstance(compiled, IntentSet):
                raise ValueError("adapter returned no typed IntentSet")
            compiled = _bind_fragment_source(compiled, fragment, batch_item_ids)
            if any(not _has_claim(descriptor, intent) for intent in compiled.intents):
                raise ValueError("intent exceeds registered claims")
            submissions.append(AuthorizedIntents(owner, fragment.facet_id, fragment.item_id,
                                                 fragment.schema_version, compiled))
        return tuple(submissions), merge_intents(snapshot.authority, tuple(submissions))

    def plan(self, target: ApplicationTarget, desired_fragments: tuple[DesiredFragment, ...],
             expected_revision: str) -> Plan | Refused:
        try:
            if not isinstance(desired_fragments, tuple) or not desired_fragments or any(
                not isinstance(item, DesiredFragment) for item in desired_fragments):
                return _refused(ErrorCode.INVALID_FRAGMENT, "nonempty typed fragments required")
            snapshot = self._snapshot(target)
            if snapshot.before_revision != expected_revision:
                return _refused(ErrorCode.STALE_PLAN, "expected revision changed")
            selections = self._select_fragments(snapshot, desired_fragments)
            with ExitStack() as stack:
                views = self._lease_selections(stack, selections, snapshot, desired_fragments)
                if self._select_fragments(snapshot, desired_fragments) != selections:
                    return _refused(ErrorCode.ADAPTER_MISSING, "configuration selection changed")
                bindings = tuple((view.payload, view.owner, item.descriptor)
                                 for view, item in zip(views, selections))
                submissions, merged = self._compile_bound(snapshot, desired_fragments, bindings)
                preflight_generation(snapshot.private_root, snapshot.authority, submissions,
                                     snapshot=snapshot.files, content=snapshot.content)
                now = self.clock()
                planned = Plan(f"plan-{uuid4().hex}", target, _digest(desired_fragments),
                               snapshot.before_revision, snapshot.native_version_ref,
                               snapshot.provider_generation, snapshot.authorization_revision,
                               snapshot.secret_ref_revision,
                               (now + timedelta(minutes=5)).astimezone(timezone.utc).isoformat())
                self.journal.register_plan(self.principal, planned)
                self._prepared[planned.plan_id] = _Prepared(planned, desired_fragments,
                                                            selections, merged)
                return planned
        except _CompileRefusal as exc:
            return _refused(exc.code, str(exc))
        except MaterializationError as exc:
            return _refused(ErrorCode.INVALID_FRAGMENT, str(exc))
        except (ValueError, IntentMergeError) as exc:
            return _refused(ErrorCode.INVALID_FRAGMENT, str(exc))
        except OSError as exc:
            return _refused(ErrorCode.VERSION_UNVERIFIED, f"runtime capture unavailable: {exc}")

    def apply(self, plan_id: str, operation_key: str, submission_permit: str) -> Confirmed | Refused | Unknown:
        # A concurrent retry through this service must observe the first durable
        # result before asking a one-use verifier to spend the same grant again.
        with self._apply_lock:
            return self._apply_locked(plan_id, operation_key, submission_permit)

    def _apply_locked(self, plan_id: str, operation_key: str,
                      submission_permit: str) -> Confirmed | Refused | Unknown:
        prepared = self._prepared.get(plan_id)
        if prepared is None:
            return _refused(ErrorCode.STALE_PLAN, "plan unavailable after service restart")
        planned = prepared.plan
        replay = self.journal.existing_for_plan(self.principal, planned, operation_key)
        if isinstance(replay, Refused):
            return replay
        if isinstance(replay, OperationRecord):
            return replay.result
        try:
            snapshot = self._snapshot(planned.target)
            with ExitStack() as stack:
                selections = self._select_fragments(snapshot, prepared.fragments)
                if selections != prepared.selections:
                    return _refused(ErrorCode.ADAPTER_MISSING, "adapter selection changed")
                views = self._lease_selections(stack, selections, snapshot, prepared.fragments)
                if self._select_fragments(snapshot, prepared.fragments) != prepared.selections:
                    return _refused(ErrorCode.ADAPTER_MISSING, "adapter selection changed under lease")
                bindings = tuple((view.payload, view.owner, item.descriptor)
                                 for view, item in zip(views, selections))
                submissions, merged = self._compile_bound(snapshot, prepared.fragments, bindings)
                if merged != prepared.merged:
                    return _refused(ErrorCode.STALE_PLAN, "compiled intent plan changed")
                preflight_generation(snapshot.private_root, snapshot.authority, submissions,
                                     snapshot=snapshot.files, content=snapshot.content)
                # Deterministic failures do not spend an otherwise usable one-use
                # permit. The durable reservation still precedes every effect.
                try:
                    permitted = bool(submission_permit and self.permits.verify(
                        self.principal, planned.target, planned, operation_key, submission_permit))
                except Exception:
                    permitted = False
                if not permitted:
                    # A second service may have reserved the same key while this
                    # one preflighted; matching durable state is safe to replay.
                    replay = self.journal.existing_for_plan(self.principal, planned, operation_key)
                    if isinstance(replay, OperationRecord):
                        return replay.result
                    if isinstance(replay, Refused):
                        return replay
                    return _refused(ErrorCode.AUTHORIZATION_REFUSED, "submission permit refused")
                observed = FenceObservation(planned.target, planned.desired_digest,
                    snapshot.before_revision, snapshot.native_version_ref,
                    snapshot.provider_generation, snapshot.authorization_revision,
                    snapshot.secret_ref_revision)
                reservation, created = self.journal.reserve_new(self.principal, plan_id, operation_key,
                                                                observed, now=self.clock())
                if isinstance(reservation, Refused):
                    return reservation
                if not created:
                    return reservation.result  # never repeat an effect
                receipt: NativeActivationReceipt | None = None
                receipt_persisted = False
                try:
                    with materialize_generation(snapshot.private_root, snapshot.authority,
                                                submissions, snapshot=snapshot.files,
                                                content=snapshot.content) as lease:
                        manifest_digest = _manifest_digest(lease.files)
                        self.journal.bind_native_manifest(self.principal, planned.target,
                                                          reservation.operation_id, manifest_digest)
                        receipt = self.runtime.activate_generation(reservation.operation_id,
                            planned.target, lease, manifest_digest)
                        if (not isinstance(receipt, NativeActivationReceipt) or
                                receipt.operation_id != reservation.operation_id or
                                receipt.target != planned.target or
                                receipt.manifest_digest != manifest_digest):
                            raise ValueError("native owner receipt does not bind this operation/generation")
                        self.journal.record_native_receipt(self.principal, planned.target, receipt)
                        receipt_persisted = True
                        readback = self.runtime.observe(planned.target)
                        if (readback.target != planned.target or readback.files != lease.files or
                                not readback.native_session_identity or readback.receipt != receipt or
                                readback.native_session_identity != receipt.native_session_identity or
                                readback.applied_revision != receipt.applied_revision or not readback.evidence_ref):
                            raise ValueError("native readback identity or generation files mismatch")
                        for view in views:
                            verification = view.payload.verify(snapshot.context, readback.observed_value)
                            if not isinstance(verification, Match):
                                raise ValueError("adapter did not confirm native readback")
                        self.journal.record_native_verification(self.principal, planned.target,
                                                                reservation.operation_id, readback.evidence_ref)
                        confirmed = Confirmed(reservation.operation_id, readback.applied_revision,
                            readback.native_session_identity, planned.target.runtime_generation,
                            readback.evidence_ref, readback.resource_changes)
                        self.journal.record_result(self.principal, planned.target,
                                                   reservation.operation_id, confirmed)
                        return confirmed
                except Exception:
                    observed_effects = ((f"native-receipt:{receipt.evidence_ref}",)
                                        if receipt_persisted and receipt is not None else ())
                    unknown = Unknown(reservation.operation_id, "verifying", observed_effects,
                                      ("native effects require independent readback",), "reconcile")
                    try:
                        self.journal.record_result(self.principal, planned.target,
                                                   reservation.operation_id, unknown)
                    except Exception:
                        pass  # durable applying row remains Unknown
                    return unknown
        except _CompileRefusal as exc:
            return _refused(exc.code, str(exc))
        except MaterializationError as exc:
            return _refused(ErrorCode.INVALID_FRAGMENT, str(exc))
        except (ValueError, IntentMergeError) as exc:
            return _refused(ErrorCode.STALE_PLAN, str(exc))
        except OSError as exc:
            return _refused(ErrorCode.VERSION_UNVERIFIED, f"runtime capture unavailable: {exc}")

    def query(self, operation_key: str) -> OperationRecord | NotFound:
        return self.journal.query(self.principal, self.target, operation_key)

    def reconcile(self, operation_key: str) -> Confirmed | Refused | Unknown:
        record = self.query(operation_key)
        if isinstance(record, NotFound):
            return _refused(ErrorCode.OPERATION_UNKNOWN, "operation not found")
        return record.result  # read only; never replay effects
