"""Work-scoped generation transport for the declared `draft` step.

The declared generation step *produces* a package; it does not implement one, so
it never goes through the implementation dispatch line (which forbids
`generate_package`). This adapter mirrors that line's own sequence on the same
composition transport:

    freeze_input -> prompt blob -> reserve -> possibly_written ->
    guard_effect_handoff -> send -> capture -> result recorded

with two deliberate differences: the identity is the Work's (`work_dispatch_key`),
and the authority is the one that actually applies to a declared generation step
on the new source-change model — the *already reviewed change* (its registered
change, the live review on it, the pinned method and the frozen input digest),
read back from the owners, plus the host's own execution permission. The
implementation authorization of the old mutation line
(`ImplementationAuthorizationIntent` / `resolve_implementation_intent`) is
deliberately not used here: a generation step has no implementation intent, and
stuffing an unrelated approval into the binding would fabricate authority.
Whether the review passed is the declared business admission's own question
(`check_package_admission`, evaluated before this step).

The step is reserved in the declared-Work dispatch relation
(`SQLiteWorkDispatchRepository`, schema 17) — a declared Work has no `runs` row
and none is invented — whose phases, CAS transition and conflict codes are the
run line's own, reused rather than re-implemented.
"""

from dataclasses import asdict
import asyncio
from collections.abc import Mapping
from contextlib import ExitStack, asynccontextmanager
import hashlib
import math
import re
from uuid import uuid4

from ordessa_engineering.application.contracts.dispatch_identity import (
    UNIT_BOOTSTRAP_OPERATION,
    historical_identity_agrees,
    unit_bootstrap_digest,
    unit_bootstrap_operation_id,
    unit_bootstrap_request_key,
    work_dispatch_key,
    work_dispatch_key_candidates,
)
from ordessa_engineering.application.contracts.commands import Reservation
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch, encode_dispatch
from ordessa_engineering.domain.common.models.values import Digest, validate_id
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.mechanisms.codec import decode_blob_ref
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.orchestration.declared_prepare_packages import verify_reviewed_change
from ordessa_engineering.domain.artifacts.provenance_codec import decode_source
from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
from ordessa_engineering.domain.artifacts.method_codec import decode_method_ref

_GENERATE = "generate_package"
_ID_FIELDS = ("proposal_id", "change_id", "review_id", "package_id", "submission_id",
              "artifact_id", "source_id", "approval_id", "observation_id")


def _target_key(ref):
    """One target's identity as the domain model states it.

    Kind, scope, the identifiers the reference itself carries, and its content
    digest / captured version all take part: a granted target of another kind,
    another scope, or another version is never the same target.
    """
    if isinstance(ref, str):
        # A bare id states no kind, scope or version, so it can only ever equal
        # another bare id - never a reference the Work actually pinned.
        return ("literal", ref)
    kind = getattr(ref, "kind", None) or type(ref).__name__
    scope = (getattr(ref, "realm_id", None), getattr(ref, "project_id", None))
    ids = tuple(sorted(value for name in _ID_FIELDS
                       if isinstance(value := getattr(ref, name, None), str) and value))
    digest = getattr(ref, "digest", None)
    capture = getattr(ref, "capture", None)
    if digest is None and capture is not None:
        digest = getattr(capture, "content_digest", None)
    version = getattr(capture, "upstream_version", None)
    return (kind, scope, ids, (getattr(digest, "algorithm", None), getattr(digest, "hex", None)),
            version)
_UNIT_KEYS = {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}


def _digest(raw):
    return Digest("sha256", hashlib.sha256(raw).hexdigest())


def _plain_identity(value, depth=0):
    if depth > 32:
        raise ApplicationError("WORK_ACTION_GENERATION_EFFECT_BINDING_MISMATCH")
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ApplicationError("WORK_ACTION_GENERATION_EFFECT_BINDING_MISMATCH")
        return {key: _plain_identity(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_identity(item, depth + 1) for item in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ApplicationError("WORK_ACTION_GENERATION_EFFECT_BINDING_MISMATCH")


class DeclaredGenerationDispatch:
    """Dispatch one declared generation step with its own authorization route."""

    def __init__(self, factory, access, *, blobs, execution, review_admission,
                 method_guard, subject_kind="reviewed_change"):
        self.factory = factory
        self.access = access
        self.blobs = blobs
        self.execution = execution
        self.subject_kind = subject_kind
        self.review_admission = review_admission
        self.method_guard = method_guard

    def _access(self, context, operation):
        if self.access is None or not callable(getattr(self.access, "require", None)):
            raise ApplicationError("WORK_ACTION_GENERATION_ACCESS_UNAVAILABLE")
        return self.access.require(context, operation)

    def reserve_unit_bootstrap(self, context, work_binding, profile_ref, owner_identity):
        """Commit the Work's one Unit-start fence before any Unit side effect."""
        self._access(context, "engineering.executions.dispatch")
        work_id = getattr(work_binding, "work_id", None)
        if (not isinstance(work_id, str) or getattr(work_binding, "scope", None) != context.scope):
            raise ApplicationError("WORK_ACTION_GENERATION_UNIT_BINDING_INVALID")
        try:
            operation_id = unit_bootstrap_operation_id(context.scope, work_id)
            key = unit_bootstrap_request_key(context)
            digest = unit_bootstrap_digest(work_binding, profile_ref, owner_identity)
        except ApplicationError:
            raise
        with self.factory.begin(context.scope) as uow:
            # The identity here is the stable operation id, never the caller
            # request key: an already recorded bootstrap is found whatever key
            # form the caller now presents, so a current-key miss can never
            # re-send. The original entry — its own key and its own bytes — is
            # what is returned; a record that names another operation, or one
            # whose pinned fields disagree, is a named reconciliation refusal.
            try:
                existing = uow.commands.find_operation(
                    context.scope, operation_id, operation=UNIT_BOOTSTRAP_OPERATION)
            except ApplicationError as exc:
                if exc.code == "OPERATION_IDENTITY_CONFLICT":
                    raise ApplicationError(
                        "WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED") from None
                raise
            if existing is not None:
                if (existing.operation != UNIT_BOOTSTRAP_OPERATION
                        or existing.operation_id != operation_id
                        or existing.project_id != context.scope.project_id
                        or existing.state != "completed"
                        or existing.key != key
                        or existing.request_digest != digest):
                    raise ApplicationError(
                        "WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED")
                self._bootstrap_result(existing.result_bytes)
                return Reservation(existing, False)
            try:
                reserved = uow.commands.reserve(
                    key, project_id=context.scope.project_id,
                    operation=UNIT_BOOTSTRAP_OPERATION, operation_id=operation_id,
                    request_digest=digest)
            except ApplicationError as exc:
                if exc.code in {"OPERATION_ID_CONFLICT", "OPERATION_IDENTITY_CONFLICT"}:
                    raise ApplicationError(
                        "WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED") from None
                raise
            if not reserved.created:
                raise ApplicationError("WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED")
            uow.commit()
            return reserved

    def complete_unit_bootstrap(self, context, reservation, unit_ref):
        """Record the actual Unit ref on the exact still-pending reservation."""
        self._access(context, "engineering.executions.dispatch")
        if (type(reservation) is not Reservation or not reservation.created
                or type(unit_ref) is not dict or set(unit_ref) != _UNIT_KEYS):
            raise ApplicationError("WORK_ACTION_GENERATION_UNIT_BINDING_MISMATCH")
        entry = reservation.entry
        key = unit_bootstrap_request_key(context)
        if (entry.key != key or entry.operation != UNIT_BOOTSTRAP_OPERATION
                or type(entry.operation_id) is not str or entry.state != "pending"):
            raise ApplicationError("WORK_ACTION_GENERATION_UNIT_BINDING_MISMATCH")
        result_bytes = canonical_bytes({"unit_ref": unit_ref})
        with self.factory.begin(context.scope) as uow:
            current = uow.commands.get(key)
            if (current is None or current != entry
                    or current.operation != UNIT_BOOTSTRAP_OPERATION
                    or current.operation_id != entry.operation_id
                    or current.request_digest != entry.request_digest
                    or current.version != entry.version or current.state != "pending"):
                raise ApplicationError("WORK_ACTION_GENERATION_UNIT_BINDING_MISMATCH")
            uow.commands.complete(key, expected_version=entry.version,
                                  result_bytes=result_bytes, state="completed")
            uow.commit()

    @staticmethod
    def _bootstrap_result(result_bytes):
        try:
            result = decode_json(result_bytes)
        except Exception:
            raise ApplicationError(
                "WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED") from None
        unit_ref = result.get("unit_ref") if type(result) is dict else None
        if (type(result) is not dict or set(result) != {"unit_ref"}
                or type(unit_ref) is not dict or set(unit_ref) != _UNIT_KEYS):
            raise ApplicationError("WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED")
        return unit_ref

    # -- the authority that applies: the reviewed change, read from the owners --
    def verified_reviewed_change(self, uow, context, *, change_ref, review_ref,
                                 method_ref, inputs_digest, baseline=None, candidate=None):
        """The change, the live review on it and the method pin must be real.

        Nothing here is a comparison of caller-supplied fields alone: every value
        is read back from its owner and must agree with what the caller declared.
        """
        if baseline is None or candidate is None:
            try:
                proposal_snapshot = uow.proposals.get_proposal(
                    change_ref, budget=uow.proposals.validated_budget())
                baseline = proposal_snapshot.source_change.baseline
                candidate = proposal_snapshot.source_change.candidate
            except Exception:
                raise ApplicationError("WORK_ACTION_GENERATION_CHANGE_NOT_FOUND") from None
        proposal, controlled, record = verify_reviewed_change(
            uow, context, proposal_ref=change_ref, review_ref=review_ref,
            method_ref=method_ref, baseline=baseline, candidate=candidate)
        if type(inputs_digest) is not Digest:
            raise ApplicationError("WORK_ACTION_GENERATION_INPUT_MISSING")
        return {"change_ref": asdict(change_ref), "review_ref": asdict(review_ref),
                "method_ref": asdict(method_ref), "inputs_digest": asdict(inputs_digest)}

    def input_snapshot(self, unit_ref, params):
        """The exact input identity a granted attempt is bound to.

        It is the digest the transport freezes the prompt from, so a re-entry can
        be checked against what was actually recorded. Freezing is a local
        computation: it never sends anything.
        """
        if self.execution is None:
            return _digest(canonical_bytes({"unit_ref": unit_ref, "params": params}))
        _raw, frozen = self.execution.freeze_input(unit_ref, params)
        return frozen

    # -- the transport sequence ----------------------------------------------
    def read_completed_generation(self, operation_ref, context, *, current_work_id,
                                  change_ref, review_ref, method_ref, baseline, candidate):
        """Read an explicitly selected prior result without re-entering its Work.

        The same original relation, review admission and blob authority are
        used. A completed native turn is required even when its outer package
        operation was rejected; unknown native attempts cannot be selected.
        """
        # This is an admission prerequisite of the exact dispatch child, not
        # a second Work query. Production leases admit one operation at a time.
        self._access(context, "engineering.executions.dispatch")
        validate_id(operation_ref)
        with self.factory.begin(context.scope, "read") as uow:
            row = uow.work_dispatch.by_operation(operation_ref, context.scope)
            binding = decode_dispatch(row["binding_bytes"])
            work = binding.work or {}
            if (binding.binding_version != 2
                    or row["dispatch_phase"] != "completed"
                    or row["execution_operation_ref"] != operation_ref
                    or binding.execution_operation_ref != operation_ref
                    or row["dispatch_fence"] != binding.fence
                    or row["binding_digest"] != _digest(row["binding_bytes"])
                    or row["result_blob_json"] is None
                    or work.get("action_id") != "incremental.prepare-packages"
                    or binding.step_id != "draft" or binding.attempt != 1
                    or work.get("work_id") == current_work_id
                    or len(binding.action_instances) != 1
                    or binding.action_instances[0][0] != _GENERATE):
                raise ApplicationError("WORK_ACTION_GENERATION_REWORK_INVALID")
            self._require_work_proposal(uow, current_work_id, change_ref, method_ref)
            self._require_work_proposal(uow, work["work_id"], change_ref, method_ref)
            evidence = self.verified_reviewed_change(
                uow, context, change_ref=change_ref, review_ref=review_ref,
                method_ref=method_ref, inputs_digest=binding.prompt_input_digest,
                baseline=baseline, candidate=candidate)
            self._reentry_matches(row, work["work_id"], work["action_id"],
                binding.step_id, binding.attempt, context, binding.prompt_input_digest,
                evidence=evidence)
            existing = self._existing(uow, work["work_id"], work["action_id"],
                                      binding.step_id, binding.attempt)
            if existing is None or existing["binding_bytes"] != row["binding_bytes"]:
                raise ApplicationError("WORK_ACTION_GENERATION_REWORK_INVALID")
        self._guard_admission(context, evidence, review_ref, method_ref, baseline, candidate)
        # Neither freeze_input nor send is used: either could resolve an old
        # live Unit. Content-addressed prior prompt/result bytes are read only.
        self.blobs.read_verified(binding.prompt_ref)
        outcome = self._view(row, already_dispatched=True)
        self.blobs.read_verified(decode_blob_ref(outcome["result_blob_ref"]))
        return outcome, binding

    def dispatch_generation(self, work_id, action_id, step_id, attempt, unit_ref, params,
                            context, *, change_ref, review_ref, method_ref,
                            input_snapshot=None, timeout=60):
        self._access(context, "engineering.executions.dispatch")
        if self.execution is None or self.blobs is None:
            raise ApplicationError("WORK_ACTION_GENERATION_TRANSPORT_UNAVAILABLE")
        for value in (work_id, action_id, step_id):
            validate_id(value)
        if type(attempt) is not int or not 1 <= attempt <= 4096:
            raise ApplicationError("INVALID_ARGUMENT")
        if type(unit_ref) is not dict or set(unit_ref) != _UNIT_KEYS:
            raise ApplicationError("WORK_ACTION_GENERATION_UNIT_REF_INVALID")
        unit_bytes = canonical_bytes(unit_ref)
        identity = work_dispatch_key(work_id, action_id, step_id)
        snapshot = self.input_snapshot(unit_ref, params)
        if input_snapshot is not None and input_snapshot != snapshot:
            raise ApplicationError("WORK_ACTION_GENERATION_INPUT_MISMATCH")

        with self.factory.begin(context.scope, "read") as uow:
            self._require_work_proposal(uow, work_id, change_ref, method_ref)
            evidence = self.verified_reviewed_change(
                uow, context, change_ref=change_ref, review_ref=review_ref,
                method_ref=method_ref, inputs_digest=snapshot)
            proposal = uow.proposals.get_proposal(change_ref)
            baseline, candidate = proposal.source_change.baseline, proposal.source_change.candidate
            existing = self._existing(uow, work_id, action_id, step_id, attempt)
        self._guard_admission(context, evidence, review_ref, method_ref, baseline, candidate)
        if existing is not None:
            # This attempt already ran (under the current key or the historical
            # folded form). Reusing it is only legitimate when the recorded
            # attempt is this same identity, scope and exact input; the original
            # key and bytes are returned, never re-minted, and never re-sent.
            self._reentry_matches(existing, work_id, action_id, step_id, attempt,
                                  context, snapshot, evidence=evidence)
            return self._view(existing, already_dispatched=True)

        raw, prompt_digest = self.execution.freeze_input(unit_ref, params)
        prompt = self.blobs.put_verified(raw, _digest(raw), "application/json")
        operation = str(uuid4())
        instance = str(uuid4())
        # A generation binding carries no approval, intent digest or control
        # version: its subject is the reviewed change itself.
        binding = DispatchBinding(
            context.scope, identity, step_id, attempt, 1, None, None, None, None,
            ((_GENERATE, instance),), unit_bytes, operation, prompt, prompt_digest,
            self.execution.query_digest(unit_ref, operation, prompt_digest),
            ("submission",), binding_version=2,
            work={"work_id": work_id, "action_id": action_id, "step_id": step_id,
                  "dispatch_key": identity},
            subject={"subject_kind": self.subject_kind, "subject_ref": evidence})
        encoded = encode_dispatch(binding)
        with self.factory.begin(context.scope) as uow:
            self.verified_reviewed_change(uow, context, change_ref=change_ref,
                                          review_ref=review_ref, method_ref=method_ref,
                                          inputs_digest=snapshot,
                                          baseline=baseline, candidate=candidate)
            self._require_work_proposal(uow, work_id, change_ref, method_ref)
            # The declared-Work relation is the only active write path for a
            # Work step: no run row exists and none is invented.
            uow.work_dispatch.reserve(identity, step_id, attempt, context.scope, encoded,
                                 _digest(encoded), operation)
            uow.commit()
        with self.factory.begin(context.scope) as uow:
            uow.work_dispatch.transition(identity, step_id, attempt, context.scope,
                                    expected_version=0, fence=1, phase="possibly_written")
            uow.commit()
        handoff = getattr(self.execution, "guard_effect_handoff", None)
        if not callable(handoff):
            raise ApplicationError("WORK_ACTION_GENERATION_EFFECT_HANDOFF_UNAVAILABLE")
        try:
            with handoff(context, binding, access=self.access, timeout=timeout):
                self.execution.send(binding, timeout=timeout)
        except Exception:
            # Never record a fabricated outcome: the attempt stays visible as
            # unknown for reconciliation, and no second send is attempted.
            with self.factory.begin(context.scope) as uow:
                row = uow.work_dispatch.get(identity, step_id, attempt, context.scope)
                uow.work_dispatch.transition(identity, step_id, attempt, context.scope,
                                        expected_version=row["dispatch_version"], fence=1,
                                        phase="unknown")
                uow.commit()
            raise
        try:
            captured = self.execution.capture(binding)
        except Exception:
            with self.factory.begin(context.scope) as uow:
                row = uow.work_dispatch.get(identity, step_id, attempt, context.scope)
                uow.work_dispatch.transition(identity, step_id, attempt, context.scope,
                    expected_version=row["dispatch_version"], fence=1, phase="unknown")
                uow.commit()
            raise
        blob_ref = getattr(captured, "blob_ref", None)
        captured_state = getattr(captured, "state", None)
        phase = {"completed": "completed", "failed": "failed", "unknown": "unknown"}.get(
            captured_state, "unknown")
        if type(blob_ref) is not BlobRef:
            phase = "unknown"
        with self.factory.begin(context.scope) as uow:
            row = uow.work_dispatch.get(identity, step_id, attempt, context.scope)
            final = uow.work_dispatch.transition(identity, step_id, attempt, context.scope,
                                           expected_version=row["dispatch_version"], fence=1,
                                           phase=phase, result_blob_ref=blob_ref)
            uow.commit()
        # A sealed native failure is an outcome for the owning Work step to
        # verify, rather than an exception that strands its parent journal.
        # Unconfirmed capture/send/commit paths still cannot finish the Work.
        if phase not in {"completed", "failed"}:
            raise ApplicationError("WORK_ACTION_GENERATION_RESULT_UNCONFIRMED")
        return {"identity": identity, "attempt": attempt, "phase": final["dispatch_phase"],
                "binding_digest": asdict(binding.digest), "result_blob_ref": blob_ref,
                "already_dispatched": False}

    @staticmethod
    def _reentry_matches(existing, work_id, action_id, step_id, attempt,
                         context, snapshot, *, evidence):
        """A stored row is reused only when it is this very attempt.

        The row may be stored under the current key or under the historical
        folded form; either way its own key must agree with the original work
        fields, and the whole binding, scope, step, attempt and frozen input must
        be this exact attempt. A key that names another identity is a named
        refusal, never a re-send.
        """
        binding = decode_dispatch(existing["binding_bytes"])
        work = binding.work or {}
        stored = existing["run_id"]
        if (existing["step_id"] != step_id or existing["attempt"] != attempt
                or binding.scope != context.scope
                or binding.run_id != stored or binding.step_id != step_id
                or binding.attempt != attempt
                or work.get("dispatch_key") != stored
                or work.get("step_id") != step_id
                or work.get("work_id") != work_id
                or work.get("action_id") != action_id
                or not historical_identity_agrees(stored, work_id, action_id, step_id)):
            raise ApplicationError("DISPATCH_ATTEMPT_IDENTITY_MISMATCH")
        if binding.prompt_input_digest != snapshot:
            raise ApplicationError("DISPATCH_ATTEMPT_INPUT_MISMATCH")
        if (binding.subject is None
                or binding.subject.get("subject_kind") != "reviewed_change"
                or binding.subject.get("subject_ref") != evidence):
            raise ApplicationError("DISPATCH_ATTEMPT_IDENTITY_MISMATCH")

    @staticmethod
    def _existing(uow, work_id, action_id, step_id, attempt):
        """The stored attempt under the current key or the explicit historical form.

        A current-key miss must never authorise a re-send: the historical folded
        form is searched too, so a row written before the key fix is found. Two
        candidates both carrying a row is an ambiguity that must be reconciled by
        name, never guessed.
        """
        candidates = work_dispatch_key_candidates(work_id, action_id, step_id)
        found = []
        for key in candidates:
            try:
                found.append(uow.work_dispatch.get(key, step_id, attempt, uow.scope))
            except ApplicationError as exc:
                if exc.code == "NOT_FOUND":
                    continue
                raise
        if not found:
            return None
        if len(found) > 1:
            raise ApplicationError("WORK_ACTION_GENERATION_RECONCILIATION_REQUIRED")
        return found[0]

    @staticmethod
    def _view(row, *, already_dispatched):
        binding = decode_dispatch(row["binding_bytes"])
        return {"identity": row["run_id"], "step_id": row["step_id"],
                "attempt": row["attempt"], "phase": row["dispatch_phase"],
                "binding_digest": asdict(binding.digest),
                "binding_bytes": row["binding_bytes"],
                "result_blob_ref": (None if row["result_blob_json"] is None
                                    else decode_json(row["result_blob_json"])),
                "already_dispatched": already_dispatched}

    def _guard_admission(self, context, evidence, review_ref, method_ref, baseline, candidate):
        if (self.review_admission is None or self.method_guard is None
                or not callable(getattr(self.review_admission, "guard_plan", None))
                or not callable(getattr(self.review_admission, "guard_trust", None))
                or not callable(getattr(self.method_guard, "guard", None))):
            raise ApplicationError("WORK_ACTION_GENERATION_ADMISSION_UNAVAILABLE")
        with self.factory.begin(context.scope, "read") as uow:
            _, _, record = verify_reviewed_change(
                uow, context, proposal_ref=decode_proposal_ref(evidence["change_ref"]),
                review_ref=review_ref, method_ref=method_ref,
                baseline=baseline, candidate=candidate)
        with self.method_guard.guard(context, method_ref), \
                self.review_admission.guard_plan(context, record.plan), \
                self.review_admission.guard_trust(context, (record,)):
            return record

    @staticmethod
    def _require_work_proposal(uow, work_id, change_ref, method_ref):
        from ordessa_engineering.application.contracts.work_context import (
            WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, decode_work_binding)
        head = uow.workflow.head_ref(WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX + work_id)
        if head is None:
            raise ApplicationError("WORK_ACTION_GENERATION_WORK_NOT_FOUND")
        work = decode_work_binding(uow.workflow.read(head))
        proposals = [item.ref for item in work.associations if item.kind == "proposal"]
        if (len(proposals) != 1 or proposals[0] != change_ref
                or work.scope != uow.scope or work.method_ref != method_ref):
            raise ApplicationError("WORK_ACTION_GENERATION_CHANGE_MISMATCH")

    @asynccontextmanager
    async def acquire_effect_write(self, context, binding, identity, deadline, *, handoff):
        """Consume the original host handoff and hold schema17's effect cut."""
        try:
            loop = asyncio.get_running_loop()
            unit_ref = _plain_identity(identity["unitRef"])
            request_id = identity["requestId"]
            frame_digest = identity["frameDigest"]
        except (KeyError, TypeError):
            raise ApplicationError("WORK_ACTION_GENERATION_EFFECT_BINDING_MISMATCH") from None
        if (type(binding) is not DispatchBinding or binding.scope != context.scope
                or binding.subject is None
                or binding.subject.get("subject_kind") != "reviewed_change"
                or binding.work is None or binding.run_id != binding.work.get("dispatch_key")
                or len(binding.action_instances) != 1
                or binding.action_instances[0][0] != _GENERATE
                or not isinstance(identity, Mapping)
                or set(identity) != {"unitRef", "operationRef", "inputDigest", "requestId", "frameDigest"}
                or canonical_bytes(unit_ref) != binding.unit_ref_bytes
                or identity["operationRef"] != binding.execution_operation_ref
                or identity["inputDigest"] != "sha256:" + binding.prompt_input_digest.hex
                or type(request_id) not in (str, int) or request_id == ""
                or type(frame_digest) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", frame_digest) is None
                or type(deadline) not in (int, float) or not math.isfinite(deadline)
                or not loop.time() < deadline <= loop.time() + 10):
            raise ApplicationError("WORK_ACTION_GENERATION_EFFECT_BINDING_MISMATCH")
        consume = getattr(self.access, "consume_effect_write", None)
        begin = getattr(self.factory, "begin_effect_cut", None)
        if not callable(consume) or not callable(begin):
            raise ApplicationError("WORK_ACTION_GENERATION_EFFECT_AUTHORITY_UNAVAILABLE")
        subject = binding.subject["subject_ref"]
        change_ref = decode_proposal_ref(subject["change_ref"])
        review_ref = decode_review_ref(subject["review_ref"])
        method_ref = decode_method_ref(subject["method_ref"])
        if self.review_admission is None or self.method_guard is None:
            raise ApplicationError("WORK_ACTION_GENERATION_ADMISSION_UNAVAILABLE")
        with self.factory.begin(context.scope, "read") as read:
            proposal, _, record = verify_reviewed_change(
                read, context, proposal_ref=change_ref, review_ref=review_ref,
                method_ref=method_ref, baseline=None, candidate=None)
            baseline, candidate = proposal.source_change.baseline, proposal.source_change.candidate
        # Hold current method, plan and reviewer-trust guards across consume and
        # the fail-fast same-owner write transaction. Re-read all Engineering
        # facts in that effect cut before yielding to the actual Unit write.
        from ordessa_engineering.domain.reviews.models import CurrentReviewTrust
        with self.method_guard.guard(context, method_ref), \
                self.review_admission.guard_plan(context, record.plan), \
                self.review_admission.guard_trust(context, (record,)) as trusted:
            if (type(trusted) is not tuple or len(trusted) != 1
                    or type(trusted[0]) is not CurrentReviewTrust
                    or trusted[0].review_ref != review_ref
                    or trusted[0].verifier_id != record.reviewer_evidence.verifier_id
                    or trusted[0].trust_version != record.reviewer_evidence.trust_version):
                raise ApplicationError("UNTRUSTED_REVIEWER")
            with consume(handoff, context, invocation_key=bytes.fromhex(binding.digest.hex),
                         action_instances=binding.action_instances), ExitStack() as stack:
                while True:
                    if loop.time() >= deadline:
                        raise ApplicationError("WORK_ACTION_GENERATION_EFFECT_TIMEOUT")
                    try:
                        uow = stack.enter_context(begin(context.scope))
                        break
                    except ApplicationError as exc:
                        if exc.code != "EFFECT_WRITE_BUSY":
                            raise
                        await asyncio.sleep(min(.005, max(0, deadline - loop.time())))
                self._access(context, "engineering.executions.dispatch")
                row = uow.work_dispatch.get(binding.run_id, binding.step_id,
                                            binding.attempt, binding.scope)
                if (row["binding_bytes"] != encode_dispatch(binding)
                        or row["dispatch_phase"] != "possibly_written"
                        or row["dispatch_fence"] != binding.fence):
                    raise ApplicationError("WORK_ACTION_GENERATION_EFFECT_BINDING_MISMATCH")
                self._require_work_proposal(uow, binding.work["work_id"], change_ref, method_ref)
                verify_reviewed_change(uow, context, proposal_ref=change_ref,
                    review_ref=review_ref, method_ref=method_ref,
                    baseline=baseline, candidate=candidate)
                if not uow.methods.control(method_ref).enabled:
                    raise ApplicationError("WORK_ACTION_GENERATION_METHOD_DISABLED")
                yield


__all__ = ["DeclaredGenerationDispatch"]
