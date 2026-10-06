"""Named-step mixin over SqliteStorePort's existing connection and ledger.

No provider callbacks, native evidence manufacture, worker or retry loop.
Every write owns one SQLite transaction; uncertain claims remain spent.
"""
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import re
from typing import Mapping

from ordessa_environment_api.domain import DomainRevisionConflict, DomainWrite
from ordessa_environment_api.errors import GuaranteeUnavailableError, IdentityMismatchError, UnknownResultError
from ordessa_environment_api.operations import (
    OperationIntent, OperationRecord, OperationRevisionConflict, StepIntent,
    StepRecord, StepClaimResult, UsageMutation, operation_holder, node_holder,
    safe_json,
)
from ordessa_environment_api.staged_operations import (
    STAGED_OPERATION_STORE_VERSION, OperationRecipePhase, StagedOperationRecord,
    _combine as _combine_root_phase, _intent_dict, _phase_dict,
)

_IDENTITIES = "core.operation-identities"


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


def _identity(request):
    return request.environment_namespace, request.principal_scope, request.request_id


def _load(value):
    decoded = json.loads(value)
    safe_json(decoded)
    return decoded


def _domain_encoding(writes):
    identities, encoded = set(), []
    for write in writes:
        if not isinstance(write, DomainWrite):
            raise ValueError("domain writes require DomainWrite")
        pair = write.namespace, write.record_id
        if pair in identities:
            raise ValueError("duplicate domain write")
        if write.namespace == _IDENTITIES:
            raise ValueError("operation identity records are core-owned")
        identities.add(pair)
        encoded.append((write, safe_json(write.value)))
    return encoded


def _usage_encoding(usages):
    identities, encoded = set(), []
    for usage in usages:
        if not isinstance(usage, UsageMutation) or usage.usage_id in identities:
            raise ValueError("Usage mutations require unique Usage ids")
        identities.add(usage.usage_id)
        encoded.append((usage, safe_json(usage.expected_holder_ref) if usage.expected_holder_ref is not None else None,
                        safe_json(usage.holder_ref), safe_json(usage.target_ref),
                        json.dumps(usage.rights), safe_json(usage.payload)))
    return encoded


def _change_digest(outcome, evidence, domains, usages):
    value = {"outcome": outcome, "evidence": evidence,
             "writes": [{"namespace": item.namespace, "id": item.record_id,
                          "expectedRevision": item.expected_revision, "payload": payload}
                         for item, payload in domains],
             "usages": [{"id": item.usage_id, "revision": item.expected_revision,
                         "state": item.state, "expectedHolder": expected, "holder": holder,
                         "target": target, "rights": rights, "payload": payload}
                        for item, expected, holder, target, rights, payload in usages]}
    return hashlib.sha256(safe_json(value).encode()).hexdigest()


def _evidence_digest(outcome, evidence):
    return hashlib.sha256(safe_json({"outcome": outcome, "evidence": evidence}).encode()).hexdigest()


class OperationRecordsMixin:
    @contextmanager
    def _operation_transaction(self):
        if self._conn.in_transaction:
            raise GuaranteeUnavailableError("operation commit cannot nest inside another transaction")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            yield
            self._conn.commit()
        except BaseException:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise

    def _operation_row(self, request):
        return self._conn.execute(
            "SELECT * FROM env_requests WHERE environment=? AND principal=? AND request_id=?",
            _identity(request),
        ).fetchone()

    def _staged_metadata(self, operation, staged_json):
        if staged_json is None:
            raise GuaranteeUnavailableError("operation is not a staged record")
        try:
            value = _load(staged_json)
            if (type(value) is not dict or set(value) != {"contractVersion", "rootIntent", "phase"}
                    or value["contractVersion"] != STAGED_OPERATION_STORE_VERSION
                    or type(value["rootIntent"]) is not dict
                    or (value["phase"] is not None and type(value["phase"]) is not dict)
                    or safe_json(value) != staged_json):
                raise ValueError("staged operation metadata is invalid")
            root_json = safe_json(value["rootIntent"])
            phase_json = None if value["phase"] is None else safe_json(value["phase"])
            staged = StagedOperationRecord(operation, root_json, phase_json)
            recipe_ids = {step.step_id for step in operation.intent.steps}
            step_rows = self._conn.execute(
                "SELECT step_id FROM env_request_steps WHERE environment=? AND principal=? AND request_id=?",
                _identity(operation.request),
            ).fetchall()
            stored_step_ids = {item["step_id"] for item in step_rows}
            if not stored_step_ids <= recipe_ids:
                raise ValueError("stored step is outside the staged recipe")
            if operation.current_step is None:
                if stored_step_ids:
                    raise ValueError("staged operation has claims without a current step")
            else:
                intent_steps = operation.intent.steps
                current_index = next((i for i, step in enumerate(intent_steps)
                                      if step.step_id == operation.current_step), None)
                if current_index is None:
                    raise ValueError("staged current step is outside the recipe")
                for index, step in enumerate(intent_steps):
                    row = self._step_row(operation.request, step.step_id)
                    if index > current_index:
                        if row is not None:
                            raise ValueError("staged recipe has a claim after its current step")
                        continue
                    if row is None:
                        raise ValueError("staged operation lost a durable step claim")
                    record = self._step_record(operation.request, row, operation)
                    if index < current_index and record.outcome != "concluded":
                        raise ValueError("staged operation advanced past an unresolved step")
            if staged.sealed:
                for root_step in staged.root_intent.steps:
                    row = self._step_row(operation.request, root_step.step_id)
                    if row is None or self._step_record(operation.request, row, operation).outcome != "concluded":
                        raise ValueError("sealed recipe lost a concluded root step")
            return staged
        except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
            raise GuaranteeUnavailableError("stored staged operation is inconsistent") from None

    def _operation_record(self, request, row):
        if row is None:
            raise GuaranteeUnavailableError("operation is not reserved")
        if row["operation_json"] is None:
            if row["staged_operation_json"] is not None:
                raise GuaranteeUnavailableError("staged operation metadata has no operation intent")
            raise UnknownResultError("spent legacy or non-operation request is not a new operation")
        try:
            stored_intent = _load(row["operation_json"])
            if hashlib.sha256(safe_json(stored_intent).encode()).hexdigest() != row["operation_intent_digest"]:
                raise ValueError("operation intent content changed")
            intent = OperationIntent.from_dict(stored_intent)
            self._check_refs(request, intent)
            receipt, current = _load(row["receipt"]), _load(row["current"])
            revision = row["operation_revision"]
            status = receipt["operation_status"]
            if (type(revision) is not int or revision < 1 or current["revision"] != revision
                    or row["spent"] != 1
                    or row["dispatch_state"] != "operation-" + status
                    or status not in {"reserved", "running", "unknown", "published", "refused", "cancelled"}
                    or current["outcome"] not in {"unknown", "concluded"}):
                raise ValueError("operation state is inconsistent")
            if (status in {"published", "refused", "cancelled"}) != (current["outcome"] == "concluded"):
                raise ValueError("operation knowledge differs from lifecycle status")
            if status == "published" and ("operation_result" not in receipt or "publication_digest" not in receipt):
                raise ValueError("publication result is missing")
            if status == "published":
                result_json = safe_json(receipt["operation_result"])
                if hashlib.sha256(result_json.encode()).hexdigest() != receipt.get("operation_result_digest"):
                    raise ValueError("publication result content changed")
                if intent.node_ref is not None and receipt["operation_result"].get("nodeRef") != intent.node_ref:
                    raise ValueError("publication node differs from fixed intent")
            current_step = receipt.get("current_step")
            evidence = receipt.get("operation_evidence", {})
            if hashlib.sha256(safe_json(evidence).encode()).hexdigest() != receipt.get("operation_evidence_digest"):
                raise ValueError("operation evidence content changed")
            if status in {"refused", "cancelled"} and not evidence:
                raise ValueError("known operation outcome lacks evidence")
            if current_step is not None and current_step not in {step.step_id for step in intent.steps}:
                raise ValueError("current step is outside the fixed recipe")
            if status == "reserved" and (revision != 1 or current_step is not None):
                raise ValueError("reservation state is inconsistent")
            if status == "running" and current_step is None:
                raise ValueError("running operation lacks a current step")
            holder = operation_holder(request, intent.operation_ref)
            identity_row = self._conn.execute(
                "SELECT payload FROM env_domain_records WHERE environment=? AND namespace=? AND record_id=?",
                (request.environment_namespace, _IDENTITIES, intent.operation_ref),
            ).fetchone()
            if identity_row is None or _load(identity_row["payload"])["holder"] != dict(holder):
                raise ValueError("operation identity index is inconsistent")
            operation = OperationRecord(request, row["digest"], revision, current["outcome"], status,
                                   row["operation_json"], receipt.get("current_step"),
                                   safe_json(receipt["operation_result"]) if "operation_result" in receipt else None,
                                   safe_json(receipt.get("operation_evidence", {})))
            if row["staged_operation_json"] is not None:
                staged = self._staged_metadata(operation, row["staged_operation_json"])
                if not staged.sealed and status == "published":
                    raise ValueError("unsealed staged operation is published")
            else:
                step_rows = self._conn.execute(
                    "SELECT step_id FROM env_request_steps WHERE environment=? AND principal=? AND request_id=? LIMIT 1",
                    _identity(request),
                ).fetchone()
                if operation.current_step is None:
                    if step_rows is not None:
                        raise ValueError("ordinary operation has step claims without a current step")
                else:
                    current_row = self._step_row(request, operation.current_step)
                    if current_row is None:
                        raise ValueError("ordinary operation current step claim is missing")
                    self._step_record(request, current_row, operation)
            if status == "published":
                for step in intent.steps:
                    step_row = self._step_row(request, step.step_id)
                    if step_row is None or self._step_record(request, step_row, operation).outcome != "concluded":
                        raise ValueError("publication lacks its fixed step evidence")
            return operation
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, IdentityMismatchError):
            raise GuaranteeUnavailableError("stored operation is inconsistent") from None

    def _check_operation(self, request, digest):
        row = self._operation_row(request)
        if row is not None and row["digest"] != digest:
            from .store import KeyConflictError
            raise KeyConflictError("request key is spent with another operation input")
        return row, self._operation_record(request, row)

    def _check_refs(self, request, intent):
        for ref in (intent.profile_snapshot_ref, intent.context_ref, intent.node_ref,
                    *(step.pinned_provider_ref for step in intent.steps)):
            if ref is not None and ref.get("environmentNamespace") != request.environment_namespace:
                raise IdentityMismatchError("operation reference belongs to another environment")

    def _write_domains(self, environment, encoded):
        for write, payload in encoded:
            row = self._conn.execute(
                "SELECT revision FROM env_domain_records WHERE environment=? AND namespace=? AND record_id=?",
                (environment, write.namespace, write.record_id),
            ).fetchone()
            revision = row["revision"] if row is not None else 0
            if revision != write.expected_revision:
                raise DomainRevisionConflict("domain publication revision conflict")
            if row is None:
                self._conn.execute(
                    "INSERT INTO env_domain_records(environment,namespace,record_id,revision,payload) VALUES(?,?,?,1,?)",
                    (environment, write.namespace, write.record_id, payload),
                )
            else:
                self._conn.execute(
                    "UPDATE env_domain_records SET revision=?,payload=? WHERE environment=? AND namespace=? AND record_id=?",
                    (revision + 1, payload, environment, write.namespace, write.record_id),
                )

    def _write_usages(self, request, intent, encoded, *, publication=False, uncertain=False, concluded=False,
                      release_holder=None):
        owner = operation_holder(request, intent.operation_ref)
        for mutation, expected, holder, target, rights, payload in encoded:
            for ref in (mutation.expected_holder_ref, mutation.holder_ref, mutation.target_ref):
                if ref is not None and ref.get("environmentNamespace") != request.environment_namespace:
                    raise IdentityMismatchError("Usage identity belongs to another environment")
            if uncertain and mutation.state == "released":
                raise UnknownResultError("unknown evidence cannot release Usage")
            if publication:
                if mutation.expected_holder_ref != owner or mutation.holder_ref.get("kind") != "node":
                    raise IdentityMismatchError("publication must transfer this operation's Usage to a node")
                destination = node_holder(request.environment_namespace, mutation.holder_ref.get("instanceId"),
                                          mutation.holder_ref.get("generation"))
                participant = {key: value for key, value in destination.items() if key != "kind"}
                # ParticipantInstanceRef is three fields; the Usage holder is
                # its tagged view. Retain the older tagged intent codec too.
                if (mutation.holder_ref != destination or intent.node_ref not in (destination, participant)
                        or mutation.state != "active"):
                    raise IdentityMismatchError("publication node holder differs from fixed node identity")
            elif release_holder is not None:
                # Controlled release seam: the step may only release Usages
                # held exactly by this holder (typically the node holder).
                if mutation.state != "released":
                    raise IdentityMismatchError("release step can only release Usages")
                if mutation.holder_ref != release_holder or mutation.expected_holder_ref != release_holder:
                    raise IdentityMismatchError("release Usage must belong to the exact release holder")
            elif mutation.holder_ref != owner or (mutation.expected_holder_ref is not None and mutation.expected_holder_ref != owner):
                raise IdentityMismatchError("step Usage must belong to this exact operation")
            row = self._conn.execute("SELECT * FROM env_usages WHERE usage_id=?", (mutation.usage_id,)).fetchone()
            if row is None:
                if mutation.expected_revision != 0 or mutation.expected_holder_ref is not None:
                    raise OperationRevisionConflict("Usage was not absent as expected")
                self._conn.execute(
                    "INSERT INTO env_usages(usage_id,environment,state,rights,holder_ref,target_ref,revision,payload) "
                    "VALUES(?,?,?,?,?,?,1,?)",
                    (mutation.usage_id, request.environment_namespace, mutation.state, rights, holder, target, payload),
                )
            else:
                if row["environment"] != request.environment_namespace:
                    raise IdentityMismatchError("Usage id is already owned by another environment")
                if row["holder_ref"] is None or row["revision"] == 0:
                    raise GuaranteeUnavailableError("legacy Usage lacks a comparable full holder identity")
                if row["revision"] != mutation.expected_revision or row["holder_ref"] != expected:
                    raise OperationRevisionConflict("Usage holder or revision changed")
                if row["state"] == "released" and (mutation.state != "released" or row["holder_ref"] != holder):
                    raise IdentityMismatchError("released Usage is terminal; new occupation requires a new Usage id")
                if row["state"] == "unknown" and mutation.state == "active" and not concluded:
                    raise UnknownResultError("unknown Usage requires concluded evidence before becoming active")
                # Only an active Usage can be released; unknown and other
                # non-active rows keep their hold (A14: never release unknown).
                if mutation.state == "released" and row["state"] not in ("active", "released"):
                    raise UnknownResultError("only an active Usage can be released")
                if row["target_ref"] != target:
                    raise IdentityMismatchError("Usage cannot silently change its fixed target")
                try:
                    existing_rights = json.loads(row["rights"])
                except (TypeError, ValueError):
                    raise GuaranteeUnavailableError("stored Usage rights are unreadable") from None
                if existing_rights != list(mutation.rights):
                    raise IdentityMismatchError("Usage rights cannot change without an authority contract")
                if row["state"] == "released":
                    if row["payload"] != payload:
                        raise IdentityMismatchError("released Usage history cannot be rewritten")
                    continue  # release of the same terminal Usage is idempotent
                self._conn.execute(
                    "UPDATE env_usages SET state=?,rights=?,holder_ref=?,revision=?,payload=? WHERE usage_id=? AND environment=?",
                    (mutation.state, rights, holder, row["revision"] + 1, payload,
                     mutation.usage_id, request.environment_namespace),
                )

    def read_usages(self, environment, holder_ref):
        """Read one holder's Usage rows for controlled release CAS construction."""
        if not isinstance(holder_ref, Mapping):
            raise ValueError("usage holder reference is required")
        rows = self._conn.execute(
            "SELECT usage_id,state,rights,holder_ref,target_ref,revision,payload FROM env_usages "
            "WHERE environment=? AND holder_ref=? ORDER BY usage_id",
            (environment, safe_json(holder_ref)),
        ).fetchall()
        result = []
        for row in rows:
            try:
                rights = json.loads(row["rights"])
                holder = json.loads(row["holder_ref"])
                target = json.loads(row["target_ref"])
                payload = json.loads(row["payload"]) if row["payload"] is not None else None
            except (TypeError, ValueError):
                raise GuaranteeUnavailableError("stored Usage row is unreadable") from None
            result.append({"usageId": row["usage_id"], "state": row["state"], "rights": rights,
                           "holderRef": holder, "targetRef": target, "revision": row["revision"],
                           "payload": payload})
        return tuple(result)

    def _set_operation(self, request, row, status, *, step=None, evidence=None, result=None, publication_digest=None):
        revision = row["operation_revision"] + 1
        receipt = _load(row["receipt"])
        receipt.update(operation_status=status, current_step=step,
                       issued_revision=f"rev-{revision}")
        if evidence is not None:
            receipt["operation_evidence"] = evidence
            receipt["operation_evidence_digest"] = hashlib.sha256(safe_json(evidence).encode()).hexdigest()
        if result is not None:
            receipt["operation_result"] = result
            receipt["operation_result_digest"] = hashlib.sha256(safe_json(result).encode()).hexdigest()
        if publication_digest is not None:
            receipt["publication_digest"] = publication_digest
        outcome = "concluded" if status in {"published", "refused", "cancelled"} else "unknown"
        current = {"outcome": outcome, "revision": revision, "conflicts": [], "obligations": []}
        self._conn.execute(
            "UPDATE env_requests SET operation_revision=?,dispatch_state=?,receipt=?,current=? "
            "WHERE environment=? AND principal=? AND request_id=?",
            (revision, "operation-" + status, safe_json(receipt), safe_json(current), *_identity(request)),
        )

    def _step_row(self, request, step_id):
        return self._conn.execute(
            "SELECT * FROM env_request_steps WHERE environment=? AND principal=? AND request_id=? AND step_id=?",
            (*_identity(request), step_id),
        ).fetchone()

    def _step_record(self, request, row, operation=None):
        try:
            intent = StepIntent.from_dict(_load(row["intent_json"]))
            operation = operation or self._operation_record(request, self._operation_row(request))
            frozen = next((item for item in operation.intent.steps if item.step_id == intent.step_id), None)
            if frozen is None or safe_json(frozen.to_dict()) != row["intent_json"]:
                raise ValueError("stored step differs from frozen recipe")
            if intent.step_id != row["step_id"] or row["revision"] < 1 or row["outcome"] not in {"possibly-dispatched", "concluded", "refused", "unknown"}:
                raise ValueError("step identity or outcome is inconsistent")
            evidence = _load(row["evidence_json"])
            if row["outcome"] == "possibly-dispatched":
                if row["revision"] != 1 or row["result_digest"] is not None or evidence:
                    raise ValueError("unresolved claim state is inconsistent")
            elif (row["revision"] < 2 or not isinstance(row["result_digest"], str)
                  or len(row["result_digest"]) != 64
                  or any(char not in "0123456789abcdef" for char in row["result_digest"])
                  or (row["outcome"] in {"concluded", "refused"} and not evidence)):
                raise ValueError("step result evidence or revision is incomplete")
            elif row["evidence_digest"] != _evidence_digest(row["outcome"], evidence):
                raise ValueError("step evidence content changed")
            return StepRecord(request, row["intent_json"], row["revision"], row["outcome"], row["evidence_json"])
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise GuaranteeUnavailableError("stored step is inconsistent") from None

    @_serialized
    def reserve_operation(self, request, digest, intent, writes=(), usages=()):
        prior = self._operation_row(request)
        if prior is not None and prior["staged_operation_json"] is not None:
            raise IdentityMismatchError("staged operation cannot use the original reservation API")
        if not isinstance(intent, OperationIntent) or not isinstance(digest, str) or not digest:
            raise ValueError("operation requires fixed intent and digest")
        intent_json = safe_json(intent.to_dict())
        self._check_refs(request, intent)
        domains, usage_rows = _domain_encoding(writes), _usage_encoding(usages)
        with self._operation_transaction():
            existing = self._operation_row(request)
            if existing is not None:
                if existing["staged_operation_json"] is not None:
                    raise IdentityMismatchError("staged operation cannot use the original reservation API")
                operation = self._check_operation(request, digest)[1]
                if operation.intent_json != intent_json:
                    raise IdentityMismatchError("reservation replay changed its fixed intent")
                return operation
            holder = operation_holder(request, intent.operation_ref)
            identity_write = DomainWrite(_IDENTITIES, intent.operation_ref, 0, {"holder": dict(holder)})
            self._write_domains(request.environment_namespace, [(identity_write, safe_json(identity_write.value)), *domains])
            self._write_usages(request, intent, usage_rows)
            receipt = {"delivery": "acknowledged", "issued_revision": "rev-1", "operation_status": "reserved",
                       "current_step": None, "operation_evidence": {},
                       "operation_evidence_digest": hashlib.sha256(safe_json({}).encode()).hexdigest()}
            current = {"outcome": "unknown", "revision": 1, "conflicts": [], "obligations": []}
            self._conn.execute(
                "INSERT INTO env_requests(environment,principal,request_id,digest,spent,receipt,current,dispatch_state,operation_json,operation_revision,operation_intent_digest) "
                "VALUES(?,?,?,?,1,?,?,'operation-reserved',?,1,?)",
                (*_identity(request), digest, safe_json(receipt), safe_json(current), intent_json,
                 hashlib.sha256(intent_json.encode()).hexdigest()),
            )
            return self._operation_record(request, self._operation_row(request))

    @_serialized
    def reserve_staged_operation(self, request, digest, root_intent, writes=(), usages=()):
        if type(root_intent) is not OperationIntent or not isinstance(digest, str) or not digest:
            raise ValueError("staged operation requires a fixed root intent and digest")
        root_intent_json = safe_json(_intent_dict(root_intent))
        canonical_root = json.loads(root_intent_json)
        root_intent = OperationIntent.from_dict(canonical_root)
        self._check_refs(request, root_intent)
        domains, usage_rows = _domain_encoding(writes), _usage_encoding(usages)
        stage_json = safe_json({"contractVersion": STAGED_OPERATION_STORE_VERSION,
                                "rootIntent": canonical_root, "phase": None})
        with self._operation_transaction():
            existing = self._operation_row(request)
            if existing is not None:
                if existing["digest"] != digest:
                    raise IdentityMismatchError("staged request input changed")
                if existing["operation_json"] is None or existing["staged_operation_json"] is None:
                    raise IdentityMismatchError("existing request is not a staged operation")
                operation = self._operation_record(request, existing)
                staged = self._staged_metadata(operation, existing["staged_operation_json"])
                if staged.root_intent_json != root_intent_json:
                    raise IdentityMismatchError("staged root intent changed")
                return staged

            holder = operation_holder(request, root_intent.operation_ref)
            identity_write = DomainWrite(_IDENTITIES, root_intent.operation_ref, 0, {"holder": dict(holder)})
            self._write_domains(request.environment_namespace,
                                [(identity_write, safe_json(identity_write.value)), *domains])
            self._write_usages(request, root_intent, usage_rows)
            receipt = {"delivery": "acknowledged", "issued_revision": "rev-1",
                       "operation_status": "reserved", "current_step": None,
                       "operation_evidence": {},
                       "operation_evidence_digest": hashlib.sha256(safe_json({}).encode()).hexdigest()}
            current = {"outcome": "unknown", "revision": 1, "conflicts": [], "obligations": []}
            self._conn.execute(
                "INSERT INTO env_requests(environment,principal,request_id,digest,spent,receipt,current,dispatch_state,"
                "operation_json,operation_revision,operation_intent_digest,staged_operation_json) "
                "VALUES(?,?,?,?,1,?,?,'operation-reserved',?,1,?,?)",
                (*_identity(request), digest, safe_json(receipt), safe_json(current), root_intent_json,
                 hashlib.sha256(root_intent_json.encode()).hexdigest(), stage_json),
            )
            row = self._operation_row(request)
            operation = self._operation_record(request, row)
            return self._staged_metadata(operation, row["staged_operation_json"])

    @_serialized
    def read_staged_operation(self, request):
        row = self._operation_row(request)
        if row is None:
            return None
        if row["staged_operation_json"] is None:
            raise GuaranteeUnavailableError("request is not a staged operation")
        operation = self._operation_record(request, row)
        return self._staged_metadata(operation, row["staged_operation_json"])

    @_serialized
    def append_staged_operation_phase(self, request, digest, expected_revision,
                                      expected_intent_digest, phase):
        if type(phase) is not OperationRecipePhase:
            raise ValueError("a complete OperationRecipePhase is required")
        if type(digest) is not str or not digest:
            raise ValueError("staged request digest is required")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected operation revision must be a positive integer")
        phase_json = safe_json(_phase_dict(phase))
        phase_value = json.loads(phase_json)
        # Reparse canonical values so no caller-owned DTO/mapping alias or
        # instance method override reaches the operation constructor.
        phase_copy = OperationRecipePhase.from_dict(phase_value)
        if (type(expected_intent_digest) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", expected_intent_digest)):
            raise ValueError("expected operation intent digest must be lowercase SHA-256")

        with self._operation_transaction():
            row = self._operation_row(request)
            if row is None:
                raise GuaranteeUnavailableError("staged operation is not reserved")
            if row["digest"] != digest:
                raise IdentityMismatchError("staged request input changed")
            if row["operation_json"] is None or row["staged_operation_json"] is None:
                raise IdentityMismatchError("request is not a staged operation")
            operation = self._operation_record(request, row)
            staged = self._staged_metadata(operation, row["staged_operation_json"])
            if staged.sealed:
                existing_phase = staged.phase
                if existing_phase.phase_id == phase_copy.phase_id:
                    if staged.phase_json != phase_json:
                        raise IdentityMismatchError("sealed phase replay changed its recipe")
                    return staged
                raise UnknownResultError("staged operation is already sealed")
            if (operation.revision != expected_revision
                    or row["operation_intent_digest"] != expected_intent_digest):
                raise OperationRevisionConflict("staged operation revision or intent digest changed")
            if operation.status != "running":
                raise UnknownResultError("root operation is not conclusively running")

            root = staged.root_intent
            root_step_ids = {step.step_id for step in root.steps}
            step_rows = self._conn.execute(
                "SELECT step_id FROM env_request_steps WHERE environment=? AND principal=? AND request_id=?",
                _identity(request),
            ).fetchall()
            if {item["step_id"] for item in step_rows} != root_step_ids:
                raise UnknownResultError("root operation step evidence is incomplete or inconsistent")
            for step in root.steps:
                step_row = self._step_row(request, step.step_id)
                if step_row is None:
                    raise UnknownResultError("root operation step has no durable conclusion")
                record = self._step_record(request, step_row, operation)
                if record.outcome != "concluded":
                    raise UnknownResultError("root operation contains an unresolved step")

            try:
                combined = _combine_root_phase(root, phase_copy, request.environment_namespace)
                self._check_refs(request, combined)
            except (TypeError, ValueError, IdentityMismatchError):
                raise IdentityMismatchError("recipe phase changes fixed operation identity") from None
            intent_json = safe_json(_intent_dict(combined))
            new_intent_digest = hashlib.sha256(intent_json.encode()).hexdigest()
            stage_json = safe_json({"contractVersion": STAGED_OPERATION_STORE_VERSION,
                                    "rootIntent": json.loads(staged.root_intent_json),
                                    "phase": json.loads(phase_json)})

            # One appended phase is immediately sealed. Preserve the original
            # operation receipt/evidence/current step while advancing its CAS.
            self._set_operation(request, row, "running", step=operation.current_step)
            self._conn.execute(
                "UPDATE env_requests SET operation_json=?,operation_intent_digest=?,staged_operation_json=? "
                "WHERE environment=? AND principal=? AND request_id=?",
                (intent_json, new_intent_digest, stage_json, *_identity(request)),
            )
            updated = self._operation_record(request, self._operation_row(request))
            return self._staged_metadata(updated, stage_json)

    @_serialized
    def read_operation(self, request):
        row = self._operation_row(request)
        return self._operation_record(request, row) if row is not None else None

    @_serialized
    def claim_operation_step(self, request, operation_digest, step_intent, usages=()):
        if not isinstance(step_intent, StepIntent):
            raise ValueError("step requires StepIntent")
        encoded = safe_json(step_intent.to_dict())
        usage_rows = _usage_encoding(usages)
        with self._operation_transaction():
            row, operation = self._check_operation(request, operation_digest)
            intent = operation.intent
            frozen = next((item for item in intent.steps if item.step_id == step_intent.step_id), None)
            if frozen is None or safe_json(frozen.to_dict()) != encoded:
                raise IdentityMismatchError("step differs from fixed operation recipe")
            existing = self._step_row(request, step_intent.step_id)
            if existing is not None:
                return StepClaimResult(False, self._step_record(request, existing))
            target_index = next(index for index, item in enumerate(intent.steps)
                                if item.step_id == step_intent.step_id)
            if operation.current_step is not None:
                current_index = next(index for index, item in enumerate(intent.steps)
                                     if item.step_id == operation.current_step)
                if target_index <= current_index:
                    raise GuaranteeUnavailableError("an earlier operation step claim is missing")
            if operation.status in {"published", "refused", "cancelled", "unknown"}:
                raise UnknownResultError("operation does not permit a new step")
            for previous in intent.steps:
                if previous.step_id == step_intent.step_id:
                    break
                record = self._step_row(request, previous.step_id)
                if record is None or self._step_record(request, record).outcome != "concluded":
                    raise UnknownResultError("prior step has not been conclusively recorded")
            self._write_usages(request, intent, usage_rows)
            self._conn.execute(
                "INSERT INTO env_request_steps(environment,principal,request_id,step_id,intent_json,revision,outcome,evidence_json) "
                "VALUES(?,?,?,?,?,1,'possibly-dispatched','{}')",
                (*_identity(request), step_intent.step_id, encoded),
            )
            self._set_operation(request, row, "running", step=step_intent.step_id)
            return StepClaimResult(True, self._step_record(request, self._step_row(request, step_intent.step_id)))

    @_serialized
    def read_operation_step(self, request, step_id):
        row = self._operation_row(request)
        if row is None:
            return None
        self._operation_record(request, row)
        step = self._step_row(request, step_id)
        return self._step_record(request, step) if step is not None else None

    @_serialized
    def record_operation_step(self, request, operation_digest, step_id, step_digest,
                              expected_revision, outcome, evidence, writes=(), usages=(),
                              *, require_complete_usages=False, release_holder=None):
        if outcome not in {"concluded", "refused", "unknown"}:
            raise ValueError("invalid step result outcome")
        if type(require_complete_usages) is not bool or require_complete_usages and outcome != "concluded":
            raise ValueError("complete retained Usage check requires a concluded step")
        if release_holder is not None and (not isinstance(release_holder, Mapping) or outcome != "concluded"):
            raise ValueError("Usage release requires a concluded step and an explicit release holder")
        evidence_json = safe_json(evidence)
        if outcome != "unknown" and not evidence:
            raise ValueError("a known result requires explicit evidence references")
        domains, usage_rows = _domain_encoding(writes), _usage_encoding(usages)
        change_digest = _change_digest(outcome, evidence, domains, usage_rows)
        if require_complete_usages:
            change_digest = hashlib.sha256(safe_json({"changeDigest": change_digest,
                                                     "requireCompleteUsages": True}).encode()).hexdigest()
        if release_holder is not None:
            change_digest = hashlib.sha256(safe_json({"changeDigest": change_digest,
                                                     "releaseHolder": release_holder}).encode()).hexdigest()
        with self._operation_transaction():
            op_row, operation = self._check_operation(request, operation_digest)
            row = self._step_row(request, step_id)
            if row is None:
                raise GuaranteeUnavailableError("cannot record an unclaimed step")
            step = self._step_record(request, row)
            if step.intent.input_digest != step_digest:
                raise IdentityMismatchError("step result input digest changed")
            if row["result_digest"] == change_digest:
                return step
            if (type(expected_revision) is not int or row["revision"] != expected_revision
                    or step.outcome in {"concluded", "refused"}
                    or operation.status in {"published", "refused", "cancelled"}):
                raise OperationRevisionConflict("step result revision or terminal state conflict")
            if require_complete_usages:
                held = self._conn.execute(
                    "SELECT usage_id FROM env_usages WHERE environment=? AND holder_ref=? AND state!='released'",
                    (request.environment_namespace, safe_json(operation_holder(request, operation.intent.operation_ref))),
                ).fetchall()
                if (not {item["usage_id"] for item in held} <= {item[0].usage_id for item in usage_rows}
                        or any(item[0].state != "active" for item in usage_rows)):
                    raise IdentityMismatchError("step conclusion must account for every retained operation Usage")
            self._write_domains(request.environment_namespace, domains)
            self._write_usages(request, operation.intent, usage_rows, uncertain=(outcome == "unknown"),
                               concluded=(outcome == "concluded"), release_holder=release_holder)
            self._conn.execute(
                "UPDATE env_request_steps SET revision=?,outcome=?,evidence_json=?,result_digest=?,evidence_digest=? "
                "WHERE environment=? AND principal=? AND request_id=? AND step_id=?",
                (row["revision"] + 1, outcome, evidence_json, change_digest,
                 _evidence_digest(outcome, evidence), *_identity(request), step_id),
            )
            self._set_operation(request, op_row, "unknown" if outcome == "unknown" else "running", step=step_id)
            return self._step_record(request, self._step_row(request, step_id))

    @_serialized
    def publish_operation(self, request, digest, expected_revision, required_steps, writes, usages, result):
        result_json = safe_json(result)
        domains, usage_rows = _domain_encoding(writes), _usage_encoding(usages)
        publication_digest = _change_digest("published", result, domains, usage_rows)
        with self._operation_transaction():
            row, operation = self._check_operation(request, digest)
            if (row["staged_operation_json"] is not None
                    and not self._staged_metadata(operation, row["staged_operation_json"]).sealed):
                raise UnknownResultError("staged operation must be sealed before publication")
            if required_steps != tuple(step.step_id for step in operation.intent.steps):
                raise IdentityMismatchError("publication must cover every fixed step")
            if operation.status == "published":
                if (operation.result_json != result_json
                        or _load(row["receipt"]).get("publication_digest") != publication_digest):
                    raise IdentityMismatchError("publication replay changed its result or writes")
                return operation
            if type(expected_revision) is not int or operation.revision != expected_revision:
                raise OperationRevisionConflict("operation publication revision changed")
            if operation.status in {"unknown", "refused", "cancelled"}:
                raise UnknownResultError("uncertain or terminal operation cannot publish")
            if operation.intent.node_ref is not None and json.loads(result_json).get("nodeRef") != operation.intent.node_ref:
                raise IdentityMismatchError("publication result differs from fixed node identity")
            for step_id in required_steps:
                step_row = self._step_row(request, step_id)
                if step_row is None or self._step_record(request, step_row).outcome != "concluded":
                    raise UnknownResultError("publication lacks complete step evidence")
            held = self._conn.execute(
                "SELECT usage_id,state FROM env_usages WHERE environment=? AND holder_ref=?",
                (request.environment_namespace, safe_json(operation_holder(request, operation.intent.operation_ref))),
            ).fetchall()
            required_usage_ids = {item["usage_id"] for item in held if item["state"] != "released"}
            if {item[0].usage_id for item in usage_rows} != required_usage_ids:
                raise IdentityMismatchError("publication must transfer every retained operation Usage")
            if any(item["state"] == "unknown" for item in held):
                raise UnknownResultError("publication cannot conclude an uncertain retained Usage")
            self._write_domains(request.environment_namespace, domains)
            self._write_usages(request, operation.intent, usage_rows, publication=True, concluded=True)
            self._set_operation(request, row, "published", step=operation.current_step,
                                result=json.loads(result_json), publication_digest=publication_digest)
            return self._operation_record(request, self._operation_row(request))

    @_serialized
    def record_operation_outcome(self, request, digest, expected_revision, outcome, evidence):
        if outcome not in {"unknown", "refused", "cancelled"}:
            raise ValueError("only non-publication outcomes are accepted")
        evidence_json = safe_json(evidence)
        if outcome != "unknown" and not evidence:
            raise ValueError("known operation outcome requires explicit evidence")
        with self._operation_transaction():
            row, operation = self._check_operation(request, digest)
            if operation.status == outcome and operation.evidence_json == evidence_json:
                return operation
            if type(expected_revision) is not int or operation.revision != expected_revision or operation.status in {"published", "refused", "cancelled"}:
                raise OperationRevisionConflict("operation outcome revision or terminal state changed")
            if outcome != "unknown":
                rows = self._conn.execute(
                    "SELECT outcome FROM env_request_steps WHERE environment=? AND principal=? AND request_id=?",
                    _identity(request),
                ).fetchall()
                if any(item["outcome"] in {"possibly-dispatched", "unknown"} for item in rows):
                    raise UnknownResultError("cancellation/refusal cannot conclude uncertain steps")
            self._set_operation(request, row, outcome, step=operation.current_step, evidence=json.loads(evidence_json))
            return self._operation_record(request, self._operation_row(request))

    @_serialized
    def refuse_unclaimed_operation(self, request, digest, expected_revision, evidence, writes):
        """Atomically refuse a reserved operation and CAS its rollback writes.

        The durable step table, rather than a caller assertion, is the source
        of truth for proving that no dispatch claim exists.
        """
        if not isinstance(evidence, Mapping) or set(evidence) != {"phase", "reason"}:
            raise ValueError("pre-dispatch refusal requires fixed phase and reason")
        allowed = {
            ("owner-recheck", "admission-refused"),
            ("owner-recheck", "owner-evidence-changed"),
            ("owner-recheck", "configuration-revision-changed"),
            ("owner-recheck", "configuration-unsupported"),
            ("invocation-issuance", "invocation-authority-refused"),
        }
        phase, reason = evidence.get("phase"), evidence.get("reason")
        if not isinstance(phase, str) or not isinstance(reason, str) or (phase, reason) not in allowed:
            raise ValueError("pre-dispatch refusal phase or reason is not recognized")
        domains = _domain_encoding(writes)
        # Bind idempotent replay to both the original evidence and the exact
        # DomainWrite identities/payloads without putting native data in the
        # operation receipt.
        writes_digest = hashlib.sha256(safe_json({
            "writes": [{"namespace": item.namespace, "recordId": item.record_id,
                        "expectedRevision": item.expected_revision, "value": item.value}
                       for item, _ in domains]
        }).encode()).hexdigest()
        stored_evidence = {"preDispatchRefusal": dict(evidence), "domainWritesDigest": writes_digest}
        evidence_json = safe_json(stored_evidence)
        with self._operation_transaction():
            row, operation = self._check_operation(request, digest)
            claims = self._conn.execute(
                "SELECT 1 FROM env_request_steps WHERE environment=? AND principal=? AND request_id=? LIMIT 1",
                _identity(request),
            ).fetchone()
            if claims is not None:
                raise UnknownResultError("a durable step claim prevents pre-dispatch refusal")
            if operation.status == "refused":
                if (type(expected_revision) is not int
                        or operation.revision != expected_revision + 1):
                    raise OperationRevisionConflict("pre-dispatch refusal replay revision changed")
                if operation.evidence_json != evidence_json:
                    raise IdentityMismatchError("pre-dispatch refusal replay changed its evidence or writes")
                return operation
            if operation.status != "reserved":
                raise UnknownResultError("only a reserved operation can be refused as unclaimed")
            if type(expected_revision) is not int or operation.revision != expected_revision:
                raise OperationRevisionConflict("pre-dispatch refusal operation revision changed")
            self._write_domains(request.environment_namespace, domains)
            self._set_operation(request, row, "refused", step=None, evidence=stored_evidence)
            return self._operation_record(request, self._operation_row(request))
