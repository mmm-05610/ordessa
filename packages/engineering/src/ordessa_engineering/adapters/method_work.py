"""Same-library persisted source for the current MethodRun Work contract.

This adapter reads only exact references already present in a Work selection or
in its persisted context slots. It does not infer readiness from a caller flag,
notification, filesystem state, executor code, or a second workflow store.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace

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
    "review_plan_ready", "review_response_ready",
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


def _input_map_version(policy):
    revision = policy.get('input_revision_policy')
    return 2 if type(revision) is dict and revision.get('contract') == \
        'ordessa.append-only-work-inputs/2' else 1


def parse_round_event_key(value):
    """Parse a canonical nonnegative decimal JSON object key."""
    if type(value) is not str or not value.isdecimal():
        raise ApplicationError('WORK_INPUT_DOCUMENT_INVALID')
    try:
        number = int(value)
    except ValueError:
        raise ApplicationError('WORK_INPUT_DOCUMENT_INVALID') from None
    if str(number) != value:
        raise ApplicationError('WORK_INPUT_DOCUMENT_INVALID')
    return number


def selected_wait_input_event(policy, document, node_id, row, program):
    """Select one method-declared event map for the persisted Work round.

    Schema-v1 snapshots keep their fixed ``events`` interpretation. Schema-v2
    snapshots must declare each wait's map and loop membership must agree; a
    missing current-round event is an error, never a fallback to the old map.
    """
    spec = policy.get('waits', {}).get(node_id)
    if type(spec) is not dict:
        raise ApplicationError('WORK_CONDITION_INPUT_MISSING')
    version = _input_map_version(policy)
    if version == 1:
        if 'event_map' in spec or 'events_by_round' in document:
            raise ApplicationError('WORK_INPUT_EVENT_MAP_UNAVAILABLE')
        selected = document.get('events', {}).get(node_id, {})
    else:
        from ordessa_engineering.application.orchestration.method_runs import observed_loop_round
        observation = observed_loop_round(program, row, node_id)
        event_map = spec.get('event_map')
        expected = 'events_by_round' if observation is not None else 'events'
        if event_map != expected:
            raise ApplicationError('WORK_INPUT_EVENT_MAP_MISMATCH')
        if event_map == 'events':
            selected = document.get('events', {}).get(node_id, {})
        else:
            _loop_id, round_number = observation
            if type(round_number) is not int or round_number < 1:
                raise ApplicationError('WORK_LOOP_STATE_INVALID')
            round_events = document.get('events_by_round', {}).get(str(round_number))
            if type(round_events) is not dict or node_id not in round_events:
                raise ApplicationError('WORK_INPUT_EVENT_MISSING')
            selected = round_events[node_id]
    if type(selected) is not dict:
        raise ApplicationError('WORK_INPUT_DOCUMENT_INVALID')
    return selected


def validate_work_input_progression(policy, previous, current):
    """Validate append-only event prefixes between two validated input docs.

    The caller remains responsible for resolving the exact same-artifact
    revision ancestry and holding its original ReadSet through the Work CAS.
    """
    if type(policy) is not dict or type(previous) is not dict or type(current) is not dict:
        raise ApplicationError('WORK_INPUT_DOCUMENT_INVALID')
    version = _input_map_version(policy)
    expected_keys = {'document_type', 'schema_version', 'run_id', 'proposal_ref', 'events'}
    if version == 2:
        expected_keys.add('events_by_round')
    if (set(previous) != expected_keys or set(current) != expected_keys
            or type(previous.get('schema_version')) is not int
            or type(current.get('schema_version')) is not int
            or previous.get('schema_version') != version
            or current.get('schema_version') != version
            or type(previous.get('events')) is not dict
            or type(current.get('events')) is not dict
            or version == 2 and (type(previous.get('events_by_round')) is not dict
                                 or type(current.get('events_by_round')) is not dict)):
        raise ApplicationError('WORK_INPUT_DOCUMENT_INVALID')
    mutable = {'events'} | ({'events_by_round'} if version == 2 else set())
    if ({key: value for key, value in previous.items() if key not in mutable} !=
            {key: value for key, value in current.items() if key not in mutable}):
        raise ApplicationError('WORK_INPUT_DOCUMENT_MISMATCH')
    for event_map in ('events', 'events_by_round')[:version]:
        if event_map == 'events':
            old_rows = {'': previous['events']}
            new_rows = {'': current['events']}
        else:
            old_rows = previous['events_by_round']
            new_rows = current['events_by_round']
        for round_key, old_waits in old_rows.items():
            new_waits = new_rows.get(round_key)
            if type(new_waits) is not dict:
                raise ApplicationError('WORK_INPUT_EVENT_CHANGED')
            for wait_id, old_fields in old_waits.items():
                new_fields = new_waits.get(wait_id)
                if type(new_fields) is not dict or any(
                        key not in new_fields or new_fields[key] != value
                        for key, value in old_fields.items()):
                    raise ApplicationError('WORK_INPUT_EVENT_CHANGED')


class SQLitePersistedMethodWorkSource:
    """Resolve method-selected Work facts through the original Engineering UoW.

    ``phase_bindings`` must be the exact, configured EngineeringTargetBindings
    from the trusted owner. They are used only to verify a complete Proposal
    review requirement set; this class does not manufacture reviewer authority.
    """

    def __init__(self, factory, method_control, *, phase_bindings=(), blobs=None,
                 review_bindings=None, execution_records=None,
                 execution_query_factory=None, review_readiness=None):
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
        if review_readiness is not None and (
                getattr(review_readiness, "factory", None) is not factory
                or getattr(review_readiness, "methods", None) is not method_control
                or not callable(getattr(review_readiness, "guard_plan_ready", None))
                or not callable(getattr(review_readiness, "guard_response_ready", None))):
            raise ApplicationError("WORK_REVIEW_READINESS_UNAVAILABLE")
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
        self.review_readiness = review_readiness
        self.execution_records = execution_records
        self.execution_query_factory = execution_query_factory

    def _manifest_policy(self, snapshot, *, uow=None):
        """Read the exact frozen manifest bytes from its original blob authority."""
        try:
            if uow is None:
                raw = self.methods.snapshots.read_blob(snapshot.manifest_ref)
            else:
                access = getattr(getattr(uow, 'implementation', None), 'access', None)
                if getattr(access, 'authority_id', None) != self.factory.authority_id:
                    raise ApplicationError('WORK_SOURCE_AUTHORITY_MISMATCH')
                from .persistence.sqlite.snapshot_store import read_snapshot_blob
                raw = read_snapshot_blob(access, self.factory.authority_id,
                                         snapshot.manifest_ref)
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
                or not {"contract_version", "waits", "input_document_slot", "input_document_type"} <= set(policy)
                or set(policy) - {"contract_version", "waits", "input_document_slot", "input_document_type",
                                  "input_revision_policy"}):
            raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
        input_policy = policy.get('input_revision_policy')
        if 'input_revision_policy' in policy and input_policy not in (
                {'contract': 'ordessa.append-only-work-inputs/1',
                 'event_values': 'immutable_once_present'},
                {'contract': 'ordessa.append-only-work-inputs/2',
                 'event_values': 'immutable_once_present',
                 'round_events': 'events_by_round'}):
            raise ApplicationError('WORK_INPUT_REVISION_POLICY_UNAVAILABLE')
        declared_waits = {node.id for node in snapshot.program.workflow.steps
                          if type(node) is WaitNode}
        if set(policy["waits"]) != declared_waits:
            raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
        if (input_policy is not None
                and input_policy['contract'] == 'ordessa.append-only-work-inputs/2'):
            if any(type(spec) is not dict or spec.get('event_map') not in
                   {'events', 'events_by_round'} for spec in policy['waits'].values()):
                raise ApplicationError('WORK_INPUT_EVENT_MAP_UNAVAILABLE')
        elif any(type(spec) is dict and 'event_map' in spec
                 for spec in policy['waits'].values()):
            # Historical frozen manifests have no event-map selector. Keep their
            # schema/meaning fixed instead of interpreting a partial v2 upgrade.
            raise ApplicationError('WORK_INPUT_EVENT_MAP_UNAVAILABLE')
        return policy

    @staticmethod
    def _event_map_version(policy):
        return _input_map_version(policy)

    @staticmethod
    def _wait_input_events(policy, document, program, row, wait_id):
        return selected_wait_input_event(policy, document, wait_id, row, program)

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
        input_version = SQLitePersistedMethodWorkSource._event_map_version(policy)
        required_keys = {"document_type", "schema_version", "run_id", "proposal_ref", "events"}
        if input_version == 2:
            required_keys.add('events_by_round')
        if (type(value) is not dict
                or set(value) != required_keys
                or value["document_type"] != policy["input_document_type"]
                or type(value["schema_version"]) is not int or value["schema_version"] != input_version
                or value["run_id"] != run_id or type(value["events"]) is not dict
                or input_version == 2 and type(value.get('events_by_round')) is not dict):
            raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        if set(value["events"]) - set(policy["waits"]):
            raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        for wait_id, event in value['events'].items():
            if (type(event) is not dict or input_version == 2
                    and policy['waits'][wait_id].get('event_map') != 'events'):
                raise ApplicationError('WORK_INPUT_DOCUMENT_INVALID')
        if input_version == 2:
            for round_key, wait_events in value['events_by_round'].items():
                parse_round_event_key(round_key)
                if type(wait_events) is not dict or not wait_events:
                    raise ApplicationError('WORK_INPUT_DOCUMENT_INVALID')
                for wait_id, event in wait_events.items():
                    if (wait_id not in policy['waits']
                            or policy['waits'][wait_id].get('event_map') != 'events_by_round'
                            or type(event) is not dict):
                        raise ApplicationError('WORK_INPUT_DOCUMENT_INVALID')
        truth_names = {"ready", "accepted", "approved", "authorized", "complete",
                       "completed", "exists", "satisfied", "passed"}
        all_events = list(value['events'].values())
        if input_version == 2:
            all_events.extend(event for mapping in value['events_by_round'].values()
                              for event in mapping.values())
        for event in all_events:
            if type(event) is not dict or any(
                    name.lower() in truth_names and type(field_value) is bool
                    for name, field_value in event.items()):
                raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        proposal_ref = _exact_ref(value["proposal_ref"])
        if type(proposal_ref) is not ProposalRef:
            raise ApplicationError("WORK_INPUT_DOCUMENT_INVALID")
        return ref, value, proposal_ref

    @staticmethod
    def _input_progression_in_uow(uow, snapshot, policy, previous_ref, current_ref, *, run_id):
        """Resolve an exact same-artifact ancestor with declared immutable input values."""
        if (type(previous_ref) is not ArtifactRevisionRef
                or type(current_ref) is not ArtifactRevisionRef
                or previous_ref.artifact_id != current_ref.artifact_id
                or (previous_ref.realm_id, previous_ref.project_id) !=
                   (current_ref.realm_id, current_ref.project_id)):
            raise ApplicationError('WORK_INPUT_REVISION_NOT_APPENDED')
        if previous_ref == current_ref:
            return
        revision_policy = policy.get('input_revision_policy')
        if revision_policy not in ({
                'contract': 'ordessa.append-only-work-inputs/1',
                'event_values': 'immutable_once_present'}, {
                'contract': 'ordessa.append-only-work-inputs/2',
                'event_values': 'immutable_once_present',
                'round_events': 'events_by_round'}):
            raise ApplicationError('WORK_INPUT_REVISION_POLICY_UNAVAILABLE')
        slot = policy['input_document_slot']
        _, previous, old_subject = SQLitePersistedMethodWorkSource._input_document(
            uow, snapshot, policy, {slot: asdict(previous_ref)}, run_id=run_id)
        _, current, new_subject = SQLitePersistedMethodWorkSource._input_document(
            uow, snapshot, policy, {slot: asdict(current_ref)}, run_id=run_id)
        if old_subject != new_subject:
            raise ApplicationError('WORK_INPUT_DOCUMENT_MISMATCH')
        validate_work_input_progression(policy, previous, current)
        pending, seen = [current_ref], set()
        while pending:
            ref = pending.pop()
            if ref == previous_ref:
                return
            if ref in seen:
                continue
            seen.add(ref)
            if len(seen) > 10000:
                raise ApplicationError('MATERIAL_LIMIT')
            revision = uow.engineering.resolve_revision(ref)
            pending.extend(parent for parent in revision.parent_revision_refs
                if parent.artifact_id == current_ref.artifact_id
                and (parent.realm_id, parent.project_id) ==
                    (current_ref.realm_id, current_ref.project_id))
        raise ApplicationError('WORK_INPUT_REVISION_NOT_APPENDED')

    def _verify_input_progression(self, context, snapshot, previous_ref, current_ref, *, run_id):
        policy = self._manifest_policy(snapshot)
        with self.factory.begin(context.scope, 'read') as uow:
            self._input_progression_in_uow(uow, snapshot, policy, previous_ref, current_ref,
                                           run_id=run_id)

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
        from ordessa_engineering.application.usecases.proposal_closure import proposal_review_revision_refs
        roots.extend(proposal_review_revision_refs(proposal))
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
        """Check the exact declared prefix, then gate every frozen member."""
        from ordessa_engineering.methods import decode_review_binding, decode_review_groups
        from ordessa_engineering.domain.reviews.codec import decode_plan
        from ordessa_infrastructure.encoding import canonical_bytes
        nodes = {item.id: item for item in snapshot.program.workflow.steps}
        request_node = nodes.get(spec.get('phase_key'))
        try:
            declaration = decode_review_binding(request_node)
            if declaration is None:
                return self._work_member_requirement(context, snapshot, node, view, spec,
                    plan, proposal, revisions, artifacts, input_ref, reads)
            group = next(item for item in decode_review_groups(snapshot.program.workflow)
                if item.anchor_node == declaration.anchor_node
                and item.group_id == declaration.group_id)
            member_index = next(index for index, member in enumerate(group.members)
                                if member.member_id == declaration.member_id)
        except (TypeError, ValueError, StopIteration):
            raise ApplicationError('METHOD_REVIEW_GROUP_UNAVAILABLE') from None
        if node.id == group.gate_wait:
            if member_index != len(group.members) - 1:
                raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH')
            members = group.members
        elif node.id in group.members[member_index].advance_waits:
            members = group.members[:member_index + 1]
        else:
            raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH')

        slots = view.get('row', {}).get('inputs', {}).get('slots', {})
        plans, requirements = [], []
        for member in members:
            try:
                selected = decode_plan(canonical_bytes(slots[member.plan_slot]))
            except (KeyError, TypeError, ValueError, ReferenceError):
                raise ApplicationError('WORK_REVIEW_BINDING_UNAVAILABLE') from None
            if (selected.scope != context.scope
                    or selected.requirement.phase_key != member.request_node
                    or selected.requirement.method_ref != _method_ref(snapshot)):
                raise ApplicationError('WORK_REVIEW_BINDING_MISMATCH')
            selected_requirements, reads = self._work_member_requirement(
                context, snapshot, node, view, {**spec, 'phase_key': member.request_node},
                selected, proposal, revisions, artifacts, input_ref, reads,
                declared_group=True)
            if len(selected_requirements) != 1 or selected.requirement != selected_requirements[0]:
                raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
            plans.append(selected)
            requirements.extend(selected_requirements)

        # Wait resumes do not create operation receipts. The original request
        # and record receipts must form this exact contiguous member prefix;
        # an arbitrary later ordinal is never evidence of completion.
        first_entry = self.review_bindings.read_request_correlation(context, plans[0])
        import json
        first_proof = json.loads(first_entry.result_bytes.decode('utf-8'))['work_review']
        start = first_proof['selector']['expected_next_step_ordinal']
        expected_nodes = tuple(value for member in members
                               for value in (member.request_node, member.record_node))
        rows = {item['step']['ordinal']: item for item in view.get('step_receipts', ())
                if type(item) is dict and type(item.get('step')) is dict}
        if (type(start) is not int
                or view.get('next_step_ordinal') != start + len(expected_nodes)):
            raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH')
        for offset, node_id in enumerate(expected_nodes):
            item = rows.get(start + offset)
            body = item.get('body') if item is not None else None
            from ordessa_engineering.application.orchestration.method_runs import _loop_round
            expected_round = _loop_round(snapshot.program, view.get('row', {}), node_id)
            if (type(body) is not dict or item['step'].get('step_id') != node_id
                    or body.get('node_id') != node_id
                    or body.get('ordinal') != start + offset
                    or body.get('round') != expected_round
                    or body.get('run_id') != view.get('run_id')
                    or body.get('scope') != asdict(context.scope)
                    or body.get('method_ref') != asdict(_method_ref(snapshot))
                    or item['step'].get('status') != 'completed'):
                raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH')
            if offset % 2:
                selected_plan = plans[offset // 2]
                try:
                    result = json.loads(body['result'])
                    from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
                    ref = decode_review_ref(result['review_ref'])
                    from ordessa_engineering.application.contracts.commands import CommandKey
                    key = CommandKey(**body['original_command_key'])
                    with self.factory.begin(context.scope, 'read') as uow:
                        entry = uow.commands.get(key)
                        record = uow.reviews.get_review(ref).record
                        request = uow.reviews.get_request(selected_plan.review_id)
                    if (entry is None or entry.operation != 'engineering.reviews.record'
                            or entry.state != 'completed'
                            or entry.operation_id != body.get('original_operation_id')
                            or entry.result_bytes != body['result'].encode('utf-8')
                            or asdict(entry.request_digest) != body.get('request_digest')
                            or record.plan != selected_plan
                            or result['plan_digest'] != asdict(selected_plan.plan_digest)
                            or result['verdict'] != record.verdict
                            or type(result['request_version']) is not int
                            or type(result['fence']) is not int
                            or request.state != 'recorded'
                            or request.version != result['request_version'] + 1
                            or request.fence != result['fence']):
                        raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH')
                except (KeyError, TypeError, ValueError, ReferenceError):
                    raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH') from None
        return tuple(requirements), reads

    def _work_member_requirement(self, context, snapshot, node, view, spec,
                                  plan, proposal, revisions, artifacts,
                                  input_ref, reads, *, declared_group=False):
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
                    or plan.requirement.phase_key != selector.phase_key):
                raise ApplicationError("WORK_REVIEW_CORRELATION_MISMATCH")
            if selector.input_ref != input_ref:
                self._verify_input_progression(context, snapshot, selector.input_ref,
                    input_ref, run_id=selector.run_id)
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
                    or (not declared_group and
                        view.get("next_step_ordinal") != body.get("ordinal") + 1)):
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
                proposal_phases = self.review_bindings.resolve_phase_bindings_for_plan(
                    context, plan)
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
            "review_plan_ready": {"family", "plan_slot", "phase_key", "subject_slot", "event_slots"},
            "review_response_ready": {"family", "plan_slot", "phase_key", "subject_slot",
                                       "review_id_slot", "request_version_slot", "fence_slot",
                                       "response_event", "event_slots"},
            "action_authorization": {"family", "intent_slot", "approval_slot", "action", "event_slots"},
        }
        # V2 chooses the declared fixed/round event map. Its parser below
        # validates the value and loop membership; it is common metadata,
        # separate from each family's event/readiness fields. V1 still
        # rejects the V2 selector rather than silently accepting a fallback.
        selector_fields = {"event_map"} if _input_map_version(policy) == 2 else set()
        expected_fields = family_fields[family] | selector_fields
        if family == "object_exists":
            allowed = expected_fields | {"intent_result_slots", "native_report_slot"}
            if set(spec) - allowed or not expected_fields.issubset(spec):
                raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
        elif set(spec) != expected_fields:
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
        event_blob_refs = {}
        refs = ()
        intent = None
        approval_ref = None
        action = None
        expected_control_version = None
        native_execution = None
        readiness_call = None
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
            node_events = selected_wait_input_event(
                policy, input_document, node.id, view.get('row', {}), snapshot.program)
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
                            raw_event = decode_blob_ref(raw_event)
                            event_blob_refs[event_name] = raw_event
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
            elif family in {"review_gate", "review_plan_ready", "review_response_ready"}:
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
                except Exception as exc:
                    if isinstance(exc, ApplicationError):
                        raise
                    raise ApplicationError("WORK_REVIEW_BINDING_UNAVAILABLE") from None
                if (plan.scope != context.scope
                        or plan.requirement.phase_key != phase_key
                        or plan.requirement.method_ref != _method_ref(snapshot)):
                    raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
                from ordessa_engineering.methods.definitions.models.compiled import OperationNode
                step_index = view.get("row", {}).get("cursor")
                steps = snapshot.program.workflow.steps
                if (type(step_index) is not int or not 0 <= step_index < len(steps)
                        or steps[step_index] is not node):
                    raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
                if family == "review_plan_ready":
                    next_node = next((item for item in steps if item.id == node.next), None)
                    if (type(next_node) is not OperationNode
                            or next_node.operation != "engineering.reviews.request"
                            or next_node.id != phase_key):
                        raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
                elif family == "review_response_ready":
                    next_node = next((item for item in steps if item.id == node.next), None)
                    request_node = next((item for item in steps
                                         if type(item) is OperationNode
                                         and item.id == phase_key
                                         and item.operation == "engineering.reviews.request"), None)
                    request_reaches_wait = (request_node is not None and any(
                        binding.target.next == node.id or binding.target.wait == node.id
                        for binding in request_node.outcomes.entries))
                    if (not request_reaches_wait
                            or type(next_node) is not OperationNode
                            or next_node.operation != "engineering.reviews.record"):
                        raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
                if family == "review_gate":
                    try:
                        stored_plan = uow.reviews.get_plan(plan.review_id)
                        request = uow.reviews.get_request(plan.review_id)
                    except Exception:
                        raise ApplicationError("WORK_REVIEW_BINDING_UNAVAILABLE") from None
                    if (stored_plan != plan or request.state == "withdrawn"
                            or request.scope != context.scope or request.review_id != plan.review_id):
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
                    from ordessa_engineering.domain.reviews.models import ReviewPlan
                    if self.review_readiness is None:
                        raise ApplicationError("WORK_REVIEW_READINESS_UNAVAILABLE")
                    subject_slot = spec.get("subject_slot")
                    if type(subject_slot) is not str:
                        raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
                    # A declared wait may bind its subject from this event.
                    # Resolve it from the exact compiled incoming binding, not
                    # only from the run's pre-existing context slots.
                    subject_raw = context_value(subject_slot)
                    subject_ref = _exact_ref(subject_raw)
                    if type(plan) is not ReviewPlan:
                        raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
                    if family == "review_plan_ready":
                        # Capture only immutable selections while this original
                        # read UoW is open. The provider may read through the
                        # same factory, so it must be entered after this UoW
                        # closes.
                        readiness_call = ("plan", plan, input_ref, subject_ref, None)
                    else:
                        review_id_slot = spec.get("review_id_slot")
                        request_version_slot = spec.get("request_version_slot")
                        fence_slot = spec.get("fence_slot")
                        response_event = spec.get("response_event")
                        if any(type(v) is not str for v in
                               (review_id_slot, request_version_slot, fence_slot, response_event)):
                            raise ApplicationError("WORK_CONDITION_INPUT_INVALID")
                        response_selector = event_slots.get(response_event)
                        response_ref = event_blob_refs.get(response_event)
                        if (type(response_selector) is not dict
                                or set(response_selector) != {"source", "field"}
                                or response_selector.get("source") != "blob_utf8"
                                or type(response_selector.get("field")) is not str
                                or response_ref is None):
                            raise ApplicationError("WORK_REVIEW_RESPONSE_UNAVAILABLE")
                        try:
                            stored_plan = uow.reviews.get_plan(plan.review_id)
                            request = uow.reviews.get_request(plan.review_id)
                        except Exception:
                            raise ApplicationError("WORK_REVIEW_BINDING_UNAVAILABLE") from None
                        def selected_value(name):
                            if name in slots:
                                return slots[name]
                            for bound in (() if node.bind is None else node.bind.entries):
                                if bound.name == name and bound.slot.startswith("event."):
                                    return event_values.get(bound.slot[6:])
                            return None
                        selected_review_id = selected_value(review_id_slot)
                        selected_request_version = selected_value(request_version_slot)
                        selected_fence = selected_value(fence_slot)
                        if (stored_plan != plan or request.review_id != plan.review_id
                                or request.scope != context.scope or request.state != "requested"
                                or type(selected_review_id) is not str
                                or selected_review_id != request.review_id
                                or type(selected_request_version) is not int
                                or selected_request_version != request.version
                                or type(selected_fence) is not int
                                or selected_fence != request.fence):
                            raise ApplicationError("WORK_REVIEW_BINDING_MISMATCH")
                        readiness_call = ("response", plan, input_ref, subject_ref,
                                          request, response_ref)
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
        # BlobStore reads are deliberately outside every business UoW. The
        # exact BlobRef was selected from the already schema-validated input
        # document above and is retained for the readiness source guard.
        for event_name, blob_ref in event_blob_refs.items():
            try:
                event_values[event_name] = self.blobs.read_verified(blob_ref).decode(
                    "utf-8", errors="strict")
            except (ReferenceError, TypeError, ValueError, UnicodeError):
                raise ApplicationError("WORK_INPUT_BLOB_INVALID") from None
        if readiness_call is not None:
            from ordessa_engineering.application.contracts.run_waits import ReviewReadiness
            provider = self.review_readiness
            if readiness_call[0] == "plan":
                _, plan, input_ref, subject_ref, _ = readiness_call
                readiness_guard = provider.guard_plan_ready(
                    context, snapshot, plan, phase_key=spec["phase_key"],
                    input_ref=input_ref, subject_ref=subject_ref, view=view)
                request = None
                response_ref = None
            else:
                _, plan, input_ref, subject_ref, request, response_ref = readiness_call
                readiness_guard = provider.guard_response_ready(
                    context, snapshot, plan, request, response_ref,
                    phase_key=spec["phase_key"], input_ref=input_ref,
                    subject_ref=subject_ref, view=view)
            with readiness_guard as readiness:
                if (type(readiness) is not ReviewReadiness
                        or readiness.plan != plan or readiness.input_ref != input_ref
                        or readiness.subject_ref != subject_ref
                        or readiness.raw_response_ref != response_ref
                        or readiness.read_set.scope != context.scope
                        or readiness.read_set.review_sets or readiness.read_set.review_controls):
                    raise ApplicationError("WORK_REVIEW_READINESS_UNAVAILABLE")
                if family == "review_plan_ready" and readiness.read_set.review_requests:
                    raise ApplicationError("WORK_REVIEW_READINESS_UNAVAILABLE")
                if family == "review_response_ready":
                    expectations = readiness.read_set.review_requests
                    if (len(expectations) != 1
                            or expectations[0].review_id != request.review_id
                            or expectations[0].expected_plan_digest != plan.plan_digest
                            or expectations[0].expected_request_version != request.version
                            or expectations[0].expected_fence != request.fence):
                        raise ApplicationError("WORK_REVIEW_READINESS_UNAVAILABLE")
                readiness = replace(readiness,
                    read_set=self._merge_read_sets(reads, readiness.read_set))
                from contextlib import ExitStack
                with ExitStack() as guards:
                    guards.enter_context(self._guard_read_set(readiness.read_set))
                    condition = BoundRunWait(
                        context.scope, view["run_id"], view["row_digest"],
                        view["next_step_ordinal"], family, readiness=readiness)
                    yield WorkWaitSelection(condition, event_values)
            return
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

    @staticmethod
    def _merge_read_sets(left, right):
        if type(left) is not ReadSet or type(right) is not ReadSet or left.scope != right.scope:
            raise ApplicationError("WORK_READ_SET_INVALID")
        versions = {}
        for item in left.versions + right.versions:
            key = (item.kind, item.identifier)
            previous = versions.get(key)
            if previous is not None and previous.version != item.version:
                raise ApplicationError("WORK_READ_SET_CHANGED")
            versions[key] = item
        request_expectations = {}
        for item in left.review_requests + right.review_requests:
            previous = request_expectations.get(item.review_id)
            if previous is not None and previous != item:
                raise ApplicationError("WORK_READ_SET_CHANGED")
            request_expectations[item.review_id] = item
        try:
            return ReadSet(left.scope, tuple(versions.values()),
                           left.review_sets + right.review_sets,
                           left.review_controls + right.review_controls,
                           tuple(request_expectations.values()))
        except Exception:
            raise ApplicationError("WORK_READ_SET_INVALID") from None

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
            current_node = program.workflow.steps[cursor]
            current_events = selected_wait_input_event(
                policy, document, current_node.id, row, program)
            current_spec = policy['waits'][current_node.id]
            current_event_slots = current_spec['event_slots']
            if type(current_event_slots) is not dict:
                raise ApplicationError('WORK_CONDITION_INPUT_INVALID')
            required_fields = set()
            for selector in current_event_slots.values():
                if type(selector) is dict and selector.get('source') in {'work_input', 'blob_utf8'}:
                    field = selector.get('field')
                    if type(field) is not str:
                        raise ApplicationError('WORK_CONDITION_INPUT_INVALID')
                    required_fields.add(field)
            if set(current_events) != required_fields:
                raise ApplicationError('WORK_INPUT_EVENT_MISSING')
            revision = uow.engineering.resolve_revision(ref)
            if previous_ref not in revision.parent_revision_refs:
                raise ApplicationError("WORK_INPUT_REVISION_NOT_APPENDED")
            if 'input_revision_policy' in policy:
                self._input_progression_in_uow(uow, snapshot, policy, previous_ref, ref,
                                              run_id=view.get('run_id'))
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


def read_work_input_document(uow, snapshot, policy, slots, *, run_id):
    """Read and validate the selected exact input ArtifactRevision in ``uow``.

    The caller owns the original UoW and ReadSet lifecycle. The returned
    revision, parsed document and ProposalRef are projections of that exact
    same-transaction source; this helper does not select an artifact head.
    """
    return SQLitePersistedMethodWorkSource._input_document(
        uow, snapshot, policy, slots, run_id=run_id)


__all__ = ["SQLitePersistedMethodWorkSource", "read_work_input_document",
           "selected_wait_input_event", "validate_work_input_progression",
           "parse_round_event_key"]
