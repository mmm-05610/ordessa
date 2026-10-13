"""Same-library persisted source for the current MethodRun Work contract.

This adapter reads only exact references already present in a Work selection or
in its persisted context slots. It does not infer readiness from a caller flag,
notification, filesystem state, executor code, or a second workflow store.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict

from ordessa_engineering.application.contracts.commands import ReadSet, ReadVersion
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_work import WorkSeed, WorkWaitSelection
from ordessa_engineering.application.contracts.run_waits import BoundRunWait
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.usecases.queries.references import resolve_exact
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.ref_codec import decode_artifact_ref
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.values import Digest, validate_id
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.methods.definitions.models.compiled import WaitNode
from ordessa_engineering.methods.loading.parsing import parse_document


_WORK_SOURCE_CONTRACT = "ordessa.persisted-work-source/1"
_WAIT_FAMILIES = frozenset({
    "object_exists", "review_gate", "action_authorization", "result_exists",
})


def _method_ref(snapshot) -> MethodRef:
    ref = snapshot.ref
    return MethodRef(ref.method_id, ref.release_version, ref.schema_version,
                     Digest("sha256", ref.snapshot_digest))


def _exact_ref(value):
    """Decode only the existing domain ref codecs used by original repositories."""
    from ordessa_engineering.domain.approvals.refs import ApprovalRef
    from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
    from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
    from ordessa_engineering.domain.reviews.refs import ReviewRef, SubmissionRef
    from ordessa_engineering.domain.changes.adoption import AcceptanceReceiptRef
    if type(value) in (ArtifactRevisionRef, ProposalRef, ApprovalRef,
                       RepositorySnapshotRef, ImplementationPackageRef, ReviewRef,
                       SubmissionRef, AcceptanceReceiptRef):
        return value
    if type(value) is not dict:
        raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
    try:
        kind = value.get("kind")
        if kind == "artifact_revision":
            return decode_artifact_ref(value)
        if kind == "proposal":
            return decode_proposal_ref(value)
        if kind == "approval":
            from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
            return decode_approval_ref(value)
        if kind == "review":
            from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
            return decode_review_ref(value)
        if kind == "submission":
            from ordessa_engineering.domain.common.mechanisms.codec import require_object, decode_digest
            require_object(value, {"kind", "realm_id", "project_id", "submission_id", "digest"}, "INVALID_SCHEMA")
            return SubmissionRef(value["realm_id"], value["project_id"], value["submission_id"], decode_digest(value["digest"]))
        if kind == "repository_snapshot":
            from ordessa_engineering.domain.changes.baseline_codec import decode_repository_ref
            return decode_repository_ref(value)
        if kind == "implementation_package":
            from ordessa_engineering.domain.packages.codec import decode_package_ref
            return decode_package_ref(value)
        if kind == "acceptance-receipt":
            from ordessa_engineering.domain.common.mechanisms.codec import require_object, decode_digest
            require_object(value, {"kind", "realm_id", "project_id", "adoption_id", "digest"}, "INVALID_SCHEMA")
            return AcceptanceReceiptRef(value["realm_id"], value["project_id"], value["adoption_id"], decode_digest(value["digest"]))
    except (ReferenceError, TypeError, ValueError, KeyError):
        raise ApplicationError("WORK_CONDITION_INPUT_INVALID") from None
    raise ApplicationError("WORK_CONDITION_INPUT_MISSING")


def _resolve_ref(uow, ref):
    from ordessa_engineering.domain.changes.adoption import AcceptanceReceiptRef
    if type(ref) is AcceptanceReceiptRef:
        if (ref.realm_id, ref.project_id) != (uow.scope.realm_id, uow.scope.project_id):
            raise ApplicationError("SCOPE_MISMATCH")
        record = uow.acceptance.resolve(ref.adoption_id)
        if record.ref != ref:
            raise ApplicationError("REFERENCE_MISMATCH")
        return record
    return resolve_exact(uow, ref)


class SQLitePersistedMethodWorkSource:
    """Resolve method-selected Work facts through the original Engineering UoW.

    ``phase_bindings`` must be the exact, configured EngineeringTargetBindings
    from the trusted owner. They are used only to verify a complete Proposal
    review requirement set; this class does not manufacture reviewer authority.
    """

    def __init__(self, factory, method_control, *, phase_bindings=(), blobs=None,
                 review_bindings=None, execution_records=None,
                 execution_query_factory=None):
        from .persistence.sqlite.unit_of_work import SQLiteUoWFactory
        if (type(factory) is not SQLiteUoWFactory
                or getattr(method_control, "factory", None) is not factory
                or getattr(method_control, "snapshots", None) is None
                or getattr(method_control.snapshots, "library", None) is not factory.library):
            raise ApplicationError("WORK_SOURCE_AUTHORITY_MISMATCH")
        from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
        if (type(phase_bindings) is not tuple
                or any(type(item) is not EngineeringTargetBindings for item in phase_bindings)
                or len({item.phase_key for item in phase_bindings}) != len(phase_bindings)):
            raise ApplicationError("WORK_SOURCE_BINDING_INVALID")
        if blobs is not None and (
                getattr(blobs, "library", None) is not factory.library
                or getattr(blobs, "authority_id", None) != factory.library.library_id
                or not callable(getattr(blobs, "read_verified", None))):
            raise ApplicationError("WORK_SOURCE_AUTHORITY_MISMATCH")
        if review_bindings is not None and (
                getattr(review_bindings, "factory", None) is not factory
                or getattr(review_bindings, "methods", None) is not method_control
                or not callable(getattr(review_bindings, "resolve_intent_bindings", None))):
            raise ApplicationError("WORK_SOURCE_REVIEW_BINDING_MISMATCH")
        if ((execution_records is None) != (execution_query_factory is None)
                or execution_records is not None and (
                    not callable(getattr(execution_records, "acp_turn_query_digest", None))
                    or not callable(getattr(execution_records, "query_acp_turn", None))
                    or not callable(execution_query_factory)
                    or blobs is None)):
            raise ApplicationError("WORK_NATIVE_SOURCE_UNAVAILABLE")
        self.factory = factory
        self.methods = method_control
        self.phase_bindings = phase_bindings
        self.blobs = blobs
        self.review_bindings = review_bindings
        self.execution_records = execution_records
        self.execution_query_factory = execution_query_factory

    def _manifest_policy(self, snapshot):
        """Read the exact frozen manifest bytes from its original blob authority."""
        try:
            raw = self.methods.snapshots.read_blob(snapshot.manifest_ref)
            value = parse_document(raw, snapshot.manifest_ref.media_type,
                                   "method.yaml")
            metadata = value.get("metadata") if type(value) is dict else None
            policy = metadata.get("work_source") if type(metadata) is dict else None
        except Exception as exc:
            if isinstance(exc, ApplicationError):
                raise
            raise ApplicationError("WORK_SOURCE_BINDING_INVALID") from None
        if (type(policy) is not dict
                or policy.get("contract_version") != _WORK_SOURCE_CONTRACT
                or type(policy.get("waits")) is not dict
                or type(policy.get("input_document_slot")) is not str
                or type(policy.get("input_document_type")) is not str
                or set(policy) != {"contract_version", "waits", "input_document_slot", "input_document_type"}):
            raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
        declared_waits = {node.id for node in snapshot.program.workflow.steps
                          if type(node) is WaitNode}
        if set(policy["waits"]) != declared_waits:
            raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
        return policy

    @staticmethod
    def _input_document(uow, snapshot, policy, slots, *, run_id):
        """Read the method-declared immutable input document and validate its schema."""
        slot = policy["input_document_slot"]
        if slot not in slots:
            raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
        ref = _exact_ref(slots[slot])
        if type(ref) is not ArtifactRevisionRef:
            raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
        artifact = uow.engineering.get_artifact(ref.artifact_id)
        if artifact.scope != uow.scope:
            raise ApplicationError("SCOPE_MISMATCH")
        revision = uow.engineering.resolve_revision(ref)
        from ordessa_engineering.application.orchestration.method_content import document_type_for_payload
        from ordessa_engineering.domain.artifacts.models import MethodPayload
        if type(revision.payload) is not MethodPayload:
            raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        if document_type_for_payload(snapshot, revision.payload) != policy["input_document_type"]:
            raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        value = revision.payload.content.value
        if (type(value) is not dict
                or set(value) != {"document_type", "schema_version", "run_id", "proposal_ref", "events"}
                or value["document_type"] != policy["input_document_type"]
                or type(value["schema_version"]) is not int or value["schema_version"] != 1
                or value["run_id"] != run_id or type(value["events"]) is not dict):
            raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        if set(value["events"]) - set(policy["waits"]):
            raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        truth_names = {"ready", "accepted", "approved", "authorized", "complete",
                       "completed", "exists", "satisfied", "passed"}
        for event in value["events"].values():
            if type(event) is not dict or any(
                    name.lower() in truth_names and type(field_value) is bool
                    for name, field_value in event.items()):
                raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        proposal_ref = _exact_ref(value["proposal_ref"])
        if type(proposal_ref) is not ProposalRef:
            raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        return ref, value, proposal_ref

    @staticmethod
    def _slots(raw):
        if type(raw) is not dict:
            raise ApplicationError("WORK_BINDING_INVALID")
        return raw

    def _proposal_material(self, uow, proposal_ref, supplied_refs):
        budget = uow.proposals.validated_budget()
        proposal = uow.proposals.get_proposal(proposal_ref, budget=budget)
        from ordessa_engineering.application.usecases.proposal_closure import resolve_record
        resolve_record(proposal, uow.proposals, budget)
        change = uow.proposals.get_change(proposal_ref.change_id)
        control = uow.proposals.get_control(proposal_ref, budget=budget)
        # Work selection binds the exact proposal subject for this method run;
        # global Change selection is a separate ChangeApply decision.
        if (change.change_id != proposal_ref.change_id
                or proposal.ref != proposal_ref
                or control.disposition != "available"):
            raise ApplicationError("WORK_PROPOSAL_UNAVAILABLE")
        roots = [m.proposed_ref for m in proposal.mutations]
        roots.extend(m.base_ref for m in proposal.mutations if m.base_ref is not None)
        roots.extend(c.owner_revision_ref for c in proposal.claim_refs)
        roots.extend(supplied_refs)
        revisions = uow.proposals.resolve_revision_graph(tuple(dict.fromkeys(roots)), budget)
        by_ref = {revision.ref: revision for revision in revisions}
        for ref in roots:
            if ref not in by_ref:
                # resolve_revision_graph must include every exact requested root.
                raise ApplicationError("WORK_SOURCE_MATERIAL_UNAVAILABLE")
        artifacts = {}
        for ref in by_ref:
            artifact = uow.engineering.get_artifact(ref.artifact_id)
            if artifact.scope != uow.scope:
                raise ApplicationError("SCOPE_MISMATCH")
            artifacts[ref.artifact_id] = artifact
        return proposal, tuple(by_ref.values()), tuple(artifacts.values()), control, change

    @staticmethod
    def _proposal_reads(scope, proposal_ref, control, change, artifacts):
        versions = [
            ReadVersion("proposal_control", proposal_ref.digest.hex, control.version),
            ReadVersion("change", change.change_id, change.version),
        ]
        versions.extend(ReadVersion("artifact", artifact.artifact_id, artifact.version)
                        for artifact in artifacts)
        return ReadSet(scope, tuple(versions))

    def _guard_read_set(self, reads):
        guard = getattr(self.factory, "guard_read_set", None)
        if not callable(guard):
            raise ApplicationError("WORK_READ_SET_GUARD_UNAVAILABLE")
        return guard(reads)

    def _review_requirements(self, context, snapshot, proposal, revisions, artifacts, *, phase_key=None):
        if not proposal.review_requirement_templates:
            return ()
        if self.review_bindings is not None:
            phase_bindings = self.review_bindings.resolve_intent_bindings(
                context, _method_ref(snapshot), proposal.ref)
        elif self.phase_bindings:
            # An explicitly supplied exact phase tuple remains useful for
            # isolated mechanism tests. Product composition uses the original
            # SQLiteWorkReviewBindings reader above.
            phase_bindings = tuple(binding for binding in self.phase_bindings
                                   if binding.scope == proposal.scope)
        else:
            raise ApplicationError("WORK_REVIEW_BINDING_UNAVAILABLE")
        if phase_key is not None:
            phase_bindings = tuple(binding for binding in phase_bindings
                                   if binding.phase_key == phase_key)
            if len(phase_bindings) != 1:
                raise ApplicationError("WORK_REVIEW_BINDING_UNAVAILABLE")
        if any(binding.scope != proposal.scope for binding in phase_bindings):
            raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
        return MethodBridge().proposal_review_requirements(
                snapshot, phase_bindings, proposal=proposal,
                artifacts=artifacts, revisions=revisions)

    def _work_review_requirements(self, context, snapshot, node, view, spec,
                                  plan, proposal, revisions, artifacts,
                                  input_ref, reads):
        """Prove a persisted plan came from this exact original Work attempt."""
        if self.review_bindings is None:
            raise ApplicationError("WORK_REVIEW_BINDING_UNAVAILABLE")
        from ordessa_engineering.application.contracts.method_work import (
            decode_work_review_selector, work_review_selector_projection,
        )
        from ordessa_engineering.domain.artifacts.method_binding import MethodRef
        from ordessa_engineering.domain.reviews.models import ReviewPlan
        from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
        import json
        try:
            entry = self.review_bindings.read_request_correlation(context, plan)
            if (entry is None or entry.operation != "engineering.reviews.request"
                    or entry.state != "completed" or type(entry.result_bytes) is not bytes):
                raise ApplicationError("WORK_REVIEW_CORRELATION_UNAVAILABLE")
            result = json.loads(entry.result_bytes.decode("utf-8"))
            proof = result["work_review"]
            selector = decode_work_review_selector(proof["selector"])
            if (type(plan) is not ReviewPlan
                    or proof["review_id"] != plan.review_id
                    or proof["plan_digest"] != asdict(plan.plan_digest)
                    or proof["command"] != {"key": asdict(entry.key),
                                           "operation_id": entry.operation_id}
                    or selector.scope != context.scope
                    or selector.run_id != view.get("run_id")
                    or selector.method_ref != _method_ref(snapshot)
                    or selector.phase_key != spec.get("phase_key")
                    or plan.requirement.phase_key != selector.phase_key
                    or selector.input_ref != input_ref):
                raise ApplicationError("WORK_REVIEW_CORRELATION_MISMATCH")
            expected_cursor = view.get("row", {}).get("cursor")
            program = snapshot.program
            if (type(expected_cursor) is not int or not 0 <= expected_cursor < len(program.workflow.steps)
                    or program.workflow.steps[expected_cursor] is not node):
                raise ApplicationError("WORK_REVIEW_CORRELATION_MISMATCH")
            receipt_candidates = []
            for item in view.get("step_receipts", ()):
                body = item.get("body") if type(item) is dict else None
                if type(body) is dict and body.get("node_id") == selector.phase_key:
                    receipt_candidates.append((item.get("step"), body))
            if not receipt_candidates:
                raise ApplicationError("WORK_REVIEW_CORRELATION_UNAVAILABLE")
            step_row, body = max(receipt_candidates, key=lambda item: item[0]["ordinal"])
            if (body.get("work_review") != proof
                    or body.get("run_id") != selector.run_id
                    or body.get("method_ref") != asdict(selector.method_ref)
                    or body.get("input_ref") != asdict(selector.input_ref)
                    or body.get("node_id") != selector.phase_key
                    or body.get("attempt") != selector.attempt
                    or body.get("expected_row_digest") != asdict(selector.expected_row_digest)
                    or body.get("expected_next_step_ordinal") != selector.expected_next_step_ordinal
                    or step_row.get("ordinal") != body.get("ordinal")
                    or view.get("next_step_ordinal") != body.get("ordinal") + 1):
                raise ApplicationError("WORK_REVIEW_CORRELATION_MISMATCH")

            binding = self.review_bindings.resolve_plan_bindings(context, plan)
            if (type(binding) is not EngineeringTargetBindings
                    or binding.scope != context.scope or binding.phase_key != selector.phase_key):
                raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
            from ordessa_engineering.domain.reviews.refs import SubmissionRef
            from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
            phase_key = selector.phase_key
            if type(selector.subject_ref) is ProposalRef:
                if selector.subject_ref != proposal.ref:
                    raise ApplicationError("WORK_REVIEW_SUBJECT_MISMATCH")
                proposal_phases = self.review_bindings.resolve_intent_bindings(
                    context, _method_ref(snapshot), proposal.ref)
                if (type(proposal_phases) is not tuple or not proposal_phases
                        or binding not in proposal_phases
                        or any(type(item) is not EngineeringTargetBindings
                               for item in proposal_phases)):
                    raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
                requirements = MethodBridge().proposal_review_requirements(
                    snapshot, proposal_phases, proposal=proposal,
                    artifacts=artifacts, revisions=revisions)
            elif type(selector.subject_ref) is SubmissionRef:
                selected = self.review_bindings.resolve_review_submission_for_plan(context, plan)
                if selected != selector.subject_ref:
                    raise ApplicationError("WORK_REVIEW_SUBJECT_MISMATCH")
                phase_bindings = self.review_bindings.resolve_submission_bindings_for_plan(context, plan)
                if (type(phase_bindings) is not tuple or not phase_bindings
                        or binding not in phase_bindings
                        or any(type(item) is not EngineeringTargetBindings for item in phase_bindings)):
                    raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
                from ordessa_engineering.application.usecases.changes.acceptance_closure import resolve_submission_acceptance
                with self.factory.begin(context.scope, "read") as uow:
                    closure = resolve_submission_acceptance(uow, selected)
                    closure_proposals = {item.ref: item for item in closure.proposals}
                    if (proposal.ref not in closure_proposals
                            or closure_proposals[proposal.ref] != proposal
                            or closure.package.payload.method_ref != _method_ref(snapshot)
                            or closure.submission.ref != selected):
                        raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
                    requirements = MethodBridge().submission_review_requirements(
                        snapshot, phase_bindings, requirements=closure.requirements,
                        revisions=closure.artifact_revisions)
                    versions = {(item.kind, item.identifier): item.version for item in reads.versions}
                    for revision in closure.artifact_revisions:
                        artifact = uow.engineering.get_artifact(revision.ref.artifact_id)
                        if artifact.scope != context.scope:
                            raise ApplicationError("SCOPE_MISMATCH")
                        versions[("artifact", artifact.artifact_id)] = artifact.version
                    reads = ReadSet(context.scope, tuple(
                        ReadVersion(kind, identifier, version)
                        for (kind, identifier), version in sorted(versions.items())))
            elif type(selector.subject_ref) is ArtifactRevisionRef:
                raise ApplicationError("WORK_REVIEW_SUBJECT_OWNER_UNAVAILABLE")
            else:
                raise ApplicationError("WORK_REVIEW_SUBJECT_OWNER_UNAVAILABLE")
            expected = tuple(item for item in requirements if item.phase_key == phase_key)
            if not expected or plan.requirement not in expected:
                raise ApplicationError("METHOD_REQUIREMENTS_CHANGED")
            return expected, reads
        except ApplicationError:
            raise
        except Exception:
            raise ApplicationError("WORK_REVIEW_CORRELATION_UNAVAILABLE") from None

    @contextmanager
    def guard_start(self, context, snapshot, *, run_id, selection):
        """Bind Work to a selected original Proposal and exact revision refs."""
        from ordessa_engineering.domain.approvals.refs import ApprovalRef
        from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
        from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
        from ordessa_engineering.domain.reviews.refs import ReviewRef, SubmissionRef
        from ordessa_engineering.domain.changes.adoption import AcceptanceReceiptRef
        try:
            validate_id(run_id)
        except (ReferenceError, TypeError, ValueError):
            raise ApplicationError("INVALID_INPUT") from None
        if (type(selection) is not dict
                or set(selection) != {"proposal_ref", "initial_slot_refs"}
                or type(selection["initial_slot_refs"]) is not dict):
            raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
        try:
            proposal_ref = _exact_ref(selection["proposal_ref"])
        except ApplicationError:
            raise
        if type(proposal_ref) is not ProposalRef:
            raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
        refs_by_slot = {}
        for slot, raw_ref in selection["initial_slot_refs"].items():
            try:
                validate_id(slot)
            except (ReferenceError, TypeError, ValueError):
                raise ApplicationError("WORK_CONDITION_INPUT_INVALID") from None
            ref = _exact_ref(raw_ref)
            if type(ref) not in (ArtifactRevisionRef, ProposalRef, ApprovalRef,
                                 ReviewRef, SubmissionRef, RepositorySnapshotRef,
                                 ImplementationPackageRef, AcceptanceReceiptRef):
                raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
            refs_by_slot[slot] = ref
        program = snapshot.program
        slots_allowed = set(program.workflow.context_slots or ())
        if (set(refs_by_slot) - slots_allowed
                or ("proposal_ref" in refs_by_slot and refs_by_slot["proposal_ref"] != proposal_ref)):
            raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
        refs_by_slot.setdefault("proposal_ref", proposal_ref)
        if "proposal_ref" not in slots_allowed:
            raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
        policy = self._manifest_policy(snapshot)
        if (policy["input_document_slot"] not in slots_allowed
                or policy["input_document_slot"] not in refs_by_slot):
            raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
        if (proposal_ref.realm_id, proposal_ref.project_id) != (
                context.scope.realm_id, context.scope.project_id):
            raise ApplicationError("SCOPE_MISMATCH")
        expected_method = _method_ref(snapshot)
        if (getattr(snapshot, "ref", None) is None
                or len({binding.phase_key for binding in self.phase_bindings}) != len(self.phase_bindings)):
            raise ApplicationError("WORK_BINDING_INVALID")
        supplied_artifacts = tuple(ref for ref in refs_by_slot.values()
                                   if type(ref) is ArtifactRevisionRef)
        with self.factory.begin(context.scope, "read") as uow:
            _input_ref, input_document, input_proposal_ref = self._input_document(
                uow, snapshot, policy,
                {slot: asdict(ref) for slot, ref in refs_by_slot.items()},
                run_id=run_id)
            if input_proposal_ref != proposal_ref:
                raise ApplicationError("WORK_INPUT_DOCUMENT_MISMATCH")
            proposal, revisions, artifacts, control, change = self._proposal_material(
                uow, proposal_ref, supplied_artifacts)
            if proposal.method_ref != expected_method:
                raise ApplicationError("WORK_METHOD_MISMATCH")
            for ref in refs_by_slot.values():
                resolved = _resolve_ref(uow, ref)
                if getattr(resolved, "ref", None) != ref:
                    raise ApplicationError("WORK_SOURCE_MATERIAL_UNAVAILABLE")
            reads = self._proposal_reads(context.scope, proposal_ref, control, change, artifacts)
        entry = next((node for node in program.workflow.steps
                      if node.id == program.workflow.entry), None)
        if type(entry) is not WaitNode:
            raise ApplicationError("WORK_ENTRY_UNAVAILABLE")
        # Context slots seed exact selected refs. User-authored work-input data
        # stays in its immutable schema-owned artifact rather than new run state.
        seed_slots = {slot: asdict(ref) for slot, ref in refs_by_slot.items()}
        if "method_ref" in slots_allowed:
            seed_slots["method_ref"] = asdict(expected_method)
        with self._guard_read_set(reads):
            yield WorkSeed(seed_slots, reads)

    @contextmanager
    def guard_condition(self, context, snapshot, node, view):
        """Resolve a declared wait from persisted refs and original records.

        Schema-validated work-input values are event data only; they establish
        no readiness, review, authorization, or completion fact by themselves.
        """
        if type(node) is not WaitNode or type(view) is not dict:
            raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
        policy = self._manifest_policy(snapshot)
        waits = policy["waits"]
        spec = waits.get(node.id)
        if type(spec) is not dict or spec.get("family") not in _WAIT_FAMILIES:
            raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
        family = spec["family"]
        family_fields = {
            "object_exists": {"family", "refs", "event_slots"},
            "result_exists": {"family", "refs", "event_slots"},
            "review_gate": {"family", "plan_slot", "phase_key", "event_slots"},
            "action_authorization": {"family", "intent_slot", "approval_slot", "action", "event_slots"},
        }
        if family == "object_exists":
            allowed = family_fields[family] | {"intent_result_slots", "native_report_slot"}
            if set(spec) - allowed or not family_fields[family].issubset(spec):
                raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
        elif set(spec) != family_fields[family]:
            raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
        slots = self._slots(view.get("row", {}).get("inputs", {}).get("slots"))
        event_slots = spec.get("event_slots", {})
        if type(event_slots) is not dict:
            raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
        required_events = {binding.name for binding in (() if node.match is None else node.match.entries)}
        required_events.update(binding.slot[6:] for binding in (() if node.bind is None else node.bind.entries)
                               if binding.slot.startswith("event."))
        if set(event_slots) != required_events:
            raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
        event_values = {}
        refs = ()
        intent = None
        approval_ref = None
        action = None
        expected_control_version = None
        native_execution = None
        for event_name in event_slots:
            try:
                validate_id(event_name)
            except (ReferenceError, TypeError, ValueError):
                raise ApplicationError("WORK_CONDITION_INPUT_INVALID") from None
        with self.factory.begin(context.scope, "read") as uow:
            input_ref, input_document, input_proposal_ref = self._input_document(
                uow, snapshot, policy, slots, run_id=view.get("run_id"))
            if ("proposal_ref" not in slots
                    or _exact_ref(slots["proposal_ref"]) != input_proposal_ref):
                raise ApplicationError("WORK_INPUT_DOCUMENT_MISMATCH")
            proposal, revisions, artifacts, control, change = self._proposal_material(
                uow, input_proposal_ref, (input_ref,))
            if proposal.method_ref != _method_ref(snapshot):
                raise ApplicationError("WORK_METHOD_MISMATCH")
            reads = self._proposal_reads(context.scope, input_proposal_ref, control, change, artifacts)
            node_events = input_document["events"].get(node.id, {})
            if type(node_events) is not dict:
                raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
            input_fields = {selector.get("field") for selector in event_slots.values()
                            if type(selector) is dict and selector.get("source") in {"work_input", "blob_utf8"}}
            if set(node_events) != input_fields:
                raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
            for event_name, selector in event_slots.items():
                if (type(selector) is not dict or selector.get("source") not in {"slot", "work_input", "blob_utf8"}
                        or (selector["source"] == "slot" and set(selector) != {"source", "slot"})
                        or (selector["source"] in {"work_input", "blob_utf8"}
                            and set(selector) != {"source", "field"})):
                    raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
                if selector["source"] == "slot":
                    if set(selector) != {"source", "slot"} or selector["slot"] not in slots:
                        raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
                    raw_event = slots[selector["slot"]]
                else:
                    if set(selector) != {"source", "field"} or selector["field"] not in node_events:
                        raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
                    raw_event = node_events[selector["field"]]
                    if selector["source"] == "blob_utf8":
                        if self.blobs is None:
                            raise ApplicationError("WORK_SOURCE_BLOB_READER_UNAVAILABLE")
                        try:
                            from ordessa_engineering.domain.common.mechanisms.codec import decode_blob_ref
                            from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
                            raw_event = decode_blob_ref(raw_event)
                            raw_event = self.blobs.read_verified(raw_event).decode("utf-8", errors="strict")
                        except (ReferenceError, TypeError, ValueError, UnicodeError):
                            raise ApplicationError("WORK_INPUT_BLOB_INVALID") from None
                event_values[event_name] = raw_event

            # The method and proposal bindings are immutable Work identity.
            # A later schema-valid event may repeat them but cannot replace them.
            for binding in (() if node.bind is None else node.bind.entries):
                if binding.name in {"method_ref", "proposal_ref"}:
                    value = event_values.get(binding.slot[6:]) if binding.slot.startswith("event.") else None
                    if binding.name not in slots or value != slots[binding.name]:
                        raise ApplicationError("WORK_INPUT_DOCUMENT_MISMATCH")

            def context_value(slot_name):
                if slot_name in slots:
                    return slots[slot_name]
                for binding in (() if node.bind is None else node.bind.entries):
                    if binding.name == slot_name and binding.slot.startswith("event."):
                        return event_values.get(binding.slot[6:])
                raise ApplicationError("WORK_CONDITION_INPUT_MISSING")

            if family in ("object_exists", "result_exists"):
                ref_slots = spec.get("refs")
                if (type(ref_slots) is not list or not ref_slots
                        or any(type(s) is not str for s in ref_slots)
                        or len(set(ref_slots)) != len(ref_slots)):
                    raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
                resolved_refs = tuple(_exact_ref(context_value(s)) for s in ref_slots)
                if family == "result_exists":
                    from ordessa_engineering.domain.reviews.refs import SubmissionRef
                    from ordessa_engineering.domain.changes.adoption import AcceptanceReceiptRef
                    if any(type(ref) not in (SubmissionRef, AcceptanceReceiptRef) for ref in resolved_refs):
                        raise ApplicationError("WAIT_RESULT_OWNER_UNAVAILABLE")
                for ref in resolved_refs:
                    if _resolve_ref(uow, ref).ref != ref:
                        raise ApplicationError("REFERENCE_MISMATCH")
                refs = resolved_refs
                if "intent_result_slots" in spec:
                    mapping = spec["intent_result_slots"]
                    if (type(mapping) is not dict or set(mapping) != {"id", "digest"}
                            or any(type(value) is not str for value in mapping.values())
                            or len(set(mapping.values())) != 2
                            or any(value not in event_values for value in mapping.values())):
                        raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
                    intent_id = event_values.get(mapping["id"])
                    intent_digest = event_values.get(mapping["digest"])
                    try:
                        validate_id(intent_id)
                        from ordessa_engineering.domain.common.mechanisms.codec import decode_digest
                        parsed_digest = decode_digest(intent_digest) if type(intent_digest) is dict else None
                    except (ReferenceError, TypeError, ValueError):
                        raise ApplicationError("WORK_CONDITION_INPUT_INVALID") from None
                    if parsed_digest is None and type(intent_digest) is str:
                        if len(intent_digest) != 64 or any(c not in "0123456789abcdef" for c in intent_digest):
                            raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
                        digest_hex = intent_digest
                    elif parsed_digest is not None:
                        digest_hex = parsed_digest.hex
                    else:
                        raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
                    try:
                        actual_intent = uow.authorization.get_intent(intent_id)
                    except ApplicationError as exc:
                        if exc.code == "NOT_FOUND":
                            raise ApplicationError("WORK_CONDITION_INPUT_MISSING") from None
                        raise
                    if (actual_intent.scope != context.scope
                            or actual_intent.method_ref != _method_ref(snapshot)
                            or actual_intent.digest.hex != digest_hex):
                        raise ApplicationError("WORK_INTENT_BINDING_MISMATCH")
                if "native_report_slot" in spec:
                    native_slot = spec["native_report_slot"]
                    if type(native_slot) is not str or native_slot not in event_values:
                        raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
                    if self.execution_records is None or self.execution_query_factory is None or self.blobs is None:
                        raise ApplicationError("WORK_NATIVE_SOURCE_UNAVAILABLE")
                    try:
                        from ordessa_infrastructure.encoding import canonical_bytes, decode_json
                        from ordessa_engineering.domain.changes.submission_codec import decode_submission
                        submission = decode_submission(canonical_bytes(event_values[native_slot]))
                        execution = submission.execution_ref
                        row = uow.dispatch.by_operation(execution.operation_ref, context.scope)
                        from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
                        binding = decode_dispatch(row["binding_bytes"])
                        owner_ref = decode_json(execution.owner_provider_ref_bytes)
                        unit_ref = {
                            "environmentNamespace": execution.environment_namespace,
                            "unitId": execution.unit_id,
                            "ownerProviderRef": owner_ref,
                            "sourceRevision": execution.source_revision,
                        }
                        from ordessa_infrastructure.encoding import canonical_bytes as _canonical_bytes
                        from dataclasses import asdict as _asdict
                        if (submission.scope != context.scope
                                or submission.package_ref != binding.package_ref
                                or binding.package_ref not in refs
                                or submission.authorization_refs != (binding.approval_ref,)
                                or binding.scope != context.scope
                                or binding.run_id != view.get("run_id")
                                or row["run_id"] != binding.run_id
                                or row["execution_operation_ref"] != execution.operation_ref
                                or binding.execution_operation_ref != execution.operation_ref
                                or binding.unit_ref_bytes != _canonical_bytes(unit_ref)
                                or binding.prompt_input_digest != execution.prompt_input_digest
                                or row["dispatch_phase"] != "completed"
                                or row["dispatch_fence"] != binding.fence
                                or row["result_blob_json"] != _canonical_bytes(_asdict(execution.captured_observation_ref)).decode("utf-8")):
                            raise ApplicationError("WORK_NATIVE_BINDING_MISMATCH")
                        native_execution = (execution, binding, unit_ref)
                    except ApplicationError:
                        raise
                    except Exception:
                        raise ApplicationError("WORK_NATIVE_SOURCE_UNAVAILABLE") from None
            elif family == "review_gate":
                plan_slot = spec.get("plan_slot")
                phase_key = spec.get("phase_key")
                if type(plan_slot) is not str or type(phase_key) is not str:
                    raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
                try:
                    validate_id(plan_slot)
                    validate_id(phase_key)
                except (ReferenceError, TypeError, ValueError):
                    raise ApplicationError("WORK_CONDITION_INPUT_INVALID") from None
                plan_value = slots.get(plan_slot)
                if plan_value is None:
                    event_keys = {binding.slot[6:]: binding.name
                                  for binding in (() if node.bind is None else node.bind.entries)
                                  if binding.slot.startswith("event.")}
                    event_name = next((event for event, target in event_keys.items()
                                       if target == plan_slot), None)
                    if event_name is not None:
                        plan_value = event_values.get(event_name)
                if type(plan_value) is not dict:
                    raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
                try:
                    from ordessa_infrastructure.encoding import canonical_bytes
                    from ordessa_engineering.domain.reviews.codec import decode_plan
                    plan = decode_plan(canonical_bytes(plan_value))
                    stored_plan = uow.reviews.get_plan(plan.review_id)
                    request = uow.reviews.get_request(plan.review_id)
                except Exception as exc:
                    if isinstance(exc, ApplicationError):
                        raise
                    raise ApplicationError("WORK_REVIEW_BINDING_UNAVAILABLE") from None
                if (stored_plan != plan or request.state == "withdrawn"
                        or request.scope != context.scope or request.review_id != plan.review_id
                        or plan.scope != context.scope
                        or plan.requirement.phase_key != phase_key
                        or plan.requirement.method_ref != _method_ref(snapshot)):
                    raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
                proposal_value = slots.get("proposal_ref")
                if proposal_value is None:
                    raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
                proposal_ref = _exact_ref(proposal_value)
                if type(proposal_ref) is not ProposalRef:
                    raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
                if proposal_ref != input_proposal_ref:
                    raise ApplicationError("WORK_INPUT_DOCUMENT_MISMATCH")
                review_plan = plan
                review_proposal = proposal
                review_revisions = revisions
                review_artifacts = artifacts
                review_input_ref = input_ref
            else:
                intent_slot = spec.get("intent_slot")
                if type(intent_slot) is not str:
                    raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
                approval_slot = spec.get("approval_slot")
                action = spec.get("action")
                if type(approval_slot) is not str or type(action) is not str:
                    raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
                try:
                    validate_id(intent_slot)
                    validate_id(approval_slot)
                    validate_id(action)
                    intent_id = context_value(intent_slot)
                    validate_id(intent_id)
                    intent = uow.authorization.get_intent(intent_id)
                except (ReferenceError, TypeError, ValueError):
                    raise ApplicationError("WORK_CONDITION_INPUT_INVALID") from None
                if intent.method_ref != _method_ref(snapshot):
                    raise ApplicationError("WORK_METHOD_MISMATCH")
                approval_ref = _exact_ref(context_value(approval_slot))
                from ordessa_engineering.domain.approvals.refs import ApprovalRef
                if type(approval_ref) is not ApprovalRef or action not in intent.actions:
                    raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
                grant = uow.authorization.get_grant(approval_ref)
                control = uow.authorization.get_control(approval_ref)
                if grant.intent != intent or control["state"] != "granted":
                    raise ApplicationError("AUTHORIZATION_REVOKED")
                expected_control_version = control["version"]
            # Retain method-schema-validated input values exactly. Actual
            # repository facts above establish condition truth; ordinary input
            # values are checked by the next operation's original owner.
        if native_execution is not None:
            execution, binding, unit_ref = native_execution
            try:
                from ordessa_engineering.application.usecases.changes.execution_capture import capture_execution_observation
                captured = capture_execution_observation(
                    self.execution_records, self.blobs,
                    authority_id=self.factory.library.library_id,
                    unit_ref=unit_ref,
                    operation_ref=execution.operation_ref,
                    expected_prompt_digest="sha256:" + execution.prompt_input_digest.hex,
                    query_invocation=self.execution_query_factory(binding))
            except ApplicationError:
                raise
            except Exception:
                raise ApplicationError("WORK_NATIVE_SOURCE_UNAVAILABLE") from None
            if (captured.state != "completed"
                    or captured.unit_ref != unit_ref
                    or captured.operation_ref != execution.operation_ref
                    or captured.expected_prompt_digest != "sha256:" + execution.prompt_input_digest.hex
                    or captured.query_digest != binding.expected_query_digest
                    or captured.blob_ref != execution.captured_observation_ref
                    or captured.authority_id != self.factory.library.library_id):
                raise ApplicationError("WORK_NATIVE_RESULT_UNAVAILABLE")
        if family == "review_gate":
            expected, reads = self._work_review_requirements(
                context, snapshot, node, view, spec, review_plan, review_proposal,
                review_revisions, review_artifacts, review_input_ref, reads)
            from ordessa_engineering.application.contracts.method_work import ReviewWaitRequirements
            intent = ReviewWaitRequirements(context.scope, expected)
        condition = BoundRunWait(
            context.scope, view["run_id"], view["row_digest"],
            view["next_step_ordinal"], family, refs, intent,
            approval_ref, action, expected_control_version)
        with self._guard_read_set(reads):
            yield WorkWaitSelection(condition, event_values)

    @contextmanager
    def guard_inputs(self, context, snapshot, view, input_ref):
        """Validate one explicit immutable input revision before Work slot CAS.

        The operation selects the revision; this source does not search for an
        accepted head or infer a human action from append-only material.
        """
        if type(view) is not dict or type(view.get("row")) is not dict:
            raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        ref = _exact_ref(input_ref)
        if type(ref) is not ArtifactRevisionRef:
            raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        row = view["row"]
        slots = self._slots(row.get("inputs", {}).get("slots"))
        policy = self._manifest_policy(snapshot)
        slot = policy["input_document_slot"]
        previous_ref = _exact_ref(slots.get(slot))
        if (type(previous_ref) is not ArtifactRevisionRef
                or previous_ref.artifact_id != ref.artifact_id
                or ref == previous_ref):
            raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        program = snapshot.program
        cursor = row.get("cursor")
        if (type(cursor) is not int or not 0 <= cursor < len(program.workflow.steps)
                or type(program.workflow.steps[cursor]) is not WaitNode
                or row.get("wait_reason") != program.workflow.steps[cursor].id):
            raise ApplicationError("WORK_WAIT_UNAVAILABLE")
        next_slots = {**slots, slot: asdict(ref)}
        with self.factory.begin(context.scope, "read") as uow:
            _input_ref, document, proposal_ref = self._input_document(
                uow, snapshot, policy, next_slots, run_id=view.get("run_id"))
            revision = uow.engineering.resolve_revision(ref)
            if previous_ref not in revision.parent_revision_refs:
                raise ApplicationError("WORK_INPUT_REVISION_NOT_APPENDED")
            if _exact_ref(slots.get("proposal_ref")) != proposal_ref:
                raise ApplicationError("WORK_INPUT_DOCUMENT_MISMATCH")
            proposal, revisions, artifacts, control, change = self._proposal_material(
                uow, proposal_ref, (ref,))
            if proposal.method_ref != _method_ref(snapshot):
                raise ApplicationError("WORK_METHOD_MISMATCH")
            reads = self._proposal_reads(context.scope, proposal_ref, control, change, artifacts)
        with self._guard_read_set(reads):
            yield WorkSeed({slot: asdict(ref)}, reads)

    def step_input_ref(self, context, snapshot, view):
        """Return the exact declared input-document revision for a Work step.

        This is only an identity projection from persisted slots. The guarded
        completion path resolves and versions the document in the original UoW.
        Methods without an input document return None; request steps require a
        concrete ref before they can be correlated.
        """
        if type(view) is not dict or type(view.get("row")) is not dict:
            raise ApplicationError("WORK_STEP_CORRELATION_UNAVAILABLE")
        policy = self._manifest_policy(snapshot)
        slots = self._slots(view["row"].get("inputs", {}).get("slots"))
        raw = slots.get(policy["input_document_slot"])
        if raw is None:
            return None
        ref = _exact_ref(raw)
        if type(ref) is not ArtifactRevisionRef:
            raise ApplicationError("WORK_STEP_CORRELATION_UNAVAILABLE")
        return ref

    @contextmanager
    def guard_step_completion(self, context, snapshot, node, view):
        """Return exact artifact-version reads for the current persisted slots.

        Command identity, schema, request digest, terminal journal state and
        one-time receipt consumption remain checked by MethodRunOrchestrator in
        its original write transaction. Any command depending on review-set or
        control state must supply that original ReadSet; it cannot be inferred
        from a completed journal row.
        """
        slots = self._slots(view.get("row", {}).get("inputs", {}).get("slots"))
        policy = self._manifest_policy(snapshot)
        with self.factory.begin(context.scope, "read") as uow:
            input_ref, _document, proposal_ref = self._input_document(
                uow, snapshot, policy, slots, run_id=view.get("run_id"))
            proposal, revisions, artifacts, control, change = self._proposal_material(
                uow, proposal_ref, (input_ref,))
            if proposal.method_ref != _method_ref(snapshot):
                raise ApplicationError("WORK_METHOD_MISMATCH")
            versions = {("proposal_control", proposal_ref.digest.hex): control.version,
                        ("change", change.change_id): change.version}
            versions.update({("artifact", artifact.artifact_id): artifact.version
                             for artifact in artifacts})
            for raw in slots.values():
                try:
                    ref = _exact_ref(raw)
                except ApplicationError:
                    continue
                if type(ref) is ProposalRef:
                    selected, _revisions, _artifacts, _control, _change = self._proposal_material(uow, ref, ())
                    if selected.method_ref != _method_ref(snapshot):
                        raise ApplicationError("WORK_METHOD_MISMATCH")
                elif type(ref) is ArtifactRevisionRef:
                    revision = uow.engineering.resolve_revision(ref)
                    artifact = uow.engineering.get_artifact(ref.artifact_id)
                    versions[("artifact", ref.artifact_id)] = artifact.version
            reads = ReadSet(context.scope, tuple(
                ReadVersion(kind, identifier, version)
                for (kind, identifier), version in sorted(versions.items())))
        with self._guard_read_set(reads):
            yield reads


__all__ = ["SQLitePersistedMethodWorkSource"]
