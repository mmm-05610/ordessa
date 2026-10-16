"""Plan-aware review bindings over the original persisted MethodRun and journal.

This adapter derives phase targets from an explicitly selected Work row and the
method snapshot pinned to that row. It does not persist a phase registry or
select a latest proposal. Historical access is recovered only from the exact
completed reviews.request journal result that recorded the Work selector.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import base64
import hashlib
import json

from ....application.contracts.commands import CommandContext, JournalEntry
from ....application.contracts.errors import ApplicationError
from ....application.contracts.commands import ReadSet, ReadVersion
from ....application.contracts.method_work import (
    WorkReviewSelector, work_review_selector_projection,
)
from ....application.contracts.snapshots import EngineeringTargetBindings, ResolvedReviewMaterial
from ....application.orchestration.method_bridge import MethodBridge
from ....application.contracts.run_waits import run_wait_row_digest
from ....application.usecases.proposal_closure import resolve_record
from ....domain.artifacts.method_binding import MethodRef
from ....domain.artifacts.ref_codec import decode_artifact_ref
from ....domain.artifacts.refs import ArtifactRevisionRef
from ....domain.changes.refs import ProposalRef
from ....domain.changes.ref_codec import decode_proposal_ref
from ....domain.common.mechanisms.codec import canonical_value
from ....domain.common.models.identity import Scope
from ....domain.common.models.values import Digest
from ....domain.common.outcomes.diagnostics import ReferenceError
from ....domain.packages.refs import ImplementationPackageRef
from ....domain.reviews.models import ReviewPlan
from ....domain.reviews.refs import ReviewRef, SubmissionRef
from ....domain.reviews.targets import Target, TargetSet
from ....methods.definitions.models.compiled import OperationNode, thaw_value
from ordessa_infrastructure.encoding import canonical_bytes
from .review_bindings import ConfiguredReviewPhase, SQLiteReviewBindings


@dataclass(frozen=True)
class _ReviewSelection:
    phase_key: str
    subject_ref: object


class SQLiteWorkReviewBindings:
    """Resolve the exact current review stage from original persisted Work.

    ``review_selection`` is a read-only convenience for the product caller. Its
    output remains a selector and a normal ReviewPlan; it is not permission.
    """

    def __init__(self, factory, method_control, *, scope, blobs):
        from .unit_of_work import SQLiteUoWFactory
        if (type(factory) is not SQLiteUoWFactory
                or getattr(method_control, 'factory', None) is not factory
                or getattr(getattr(method_control, 'snapshots', None), 'library', None)
                    is not factory.library
                or type(scope) is not Scope
                or getattr(blobs, 'library', None) is not factory.library
                or getattr(blobs, 'authority_id', None) != factory.authority_id
                or not callable(getattr(blobs, 'read_verified', None))):
            raise ApplicationError('WORK_REVIEW_BINDING_UNAVAILABLE')
        self.factory, self.methods, self.scope, self.blobs = factory, method_control, scope, blobs
        self.bridge = MethodBridge()

    @staticmethod
    def _method_ref_from_snapshot(snapshot):
        ref = snapshot.ref
        return MethodRef(ref.method_id, ref.release_version, ref.schema_version,
                         Digest('sha256', ref.snapshot_digest))

    def _snapshot(self, context, method_ref):
        return self.methods.guard_method(context, method_ref)

    def _policy(self, snapshot, *, uow=None):
        # Keep the reader on the same frozen-manifest parser and declaration
        # checks as the Work source; a second partial policy decoder could
        # accept a different set of waits or revision semantics.
        from ...method_work import SQLitePersistedMethodWorkSource
        source = SQLitePersistedMethodWorkSource(self.factory, self.methods)
        return source._manifest_policy(snapshot, uow=uow)

    @staticmethod
    def _slots(row):
        inputs = row.get('inputs')
        slots = inputs.get('slots') if type(inputs) is dict else None
        if type(slots) is not dict:
            raise ApplicationError('WORK_BINDING_INVALID')
        return slots

    def _run_row(self, context, run_id):
        if type(context) is not CommandContext or context.scope != self.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        try:
            row = self.factory.library.run_row(run_id)
        except Exception:
            raise ApplicationError('WORK_BINDING_INVALID') from None
        if type(row) is not dict:
            raise ApplicationError('WORK_BINDING_INVALID')
        from ....application.orchestration.method_runs import MethodRunBindings
        MethodRunBindings._inputs(context, row)
        row = {**row, 'run_id': run_id}
        inputs = row.get('inputs')
        if (type(inputs) is not dict or inputs.get('work_contract') != 'ordessa.engineering.current-work/1'
                or inputs.get('scope') != asdict(context.scope)):
            raise ApplicationError('WORK_BINDING_INVALID')
        return row

    @staticmethod
    def _method_ref_from_row(context, row):
        from ....application.orchestration.method_runs import MethodRunBindings
        return MethodRunBindings._inputs(context, row)

    @staticmethod
    def _row_digest(row):
        # run_id is the query key, not a field in the original persisted row.
        return run_wait_row_digest({k:v for k,v in row.items() if k!='run_id'})

    def _work_values(self, uow, snapshot, row, input_ref):
        policy = self._policy(snapshot, uow=uow)
        slot_name = policy['input_document_slot']
        slots = self._slots(row)
        try:
            slot_ref = decode_artifact_ref(slots[slot_name])
        except (KeyError, ReferenceError, TypeError, ValueError):
            raise ApplicationError('WORK_REVIEW_INPUT_UNAVAILABLE') from None
        if slot_ref != input_ref:
            raise ApplicationError('WORK_REVIEW_SELECTOR_STALE')
        from ...method_work import read_work_input_document
        try:
            _, value, input_proposal = read_work_input_document(
                uow, snapshot, policy, slots, run_id=row['run_id'])
        except ApplicationError as exc:
            if exc.code in {'WORK_INPUT_DOCUMENT_INVALID', 'WORK_CONDITION_INPUT_INVALID'}:
                raise ApplicationError('WORK_REVIEW_INPUT_INVALID') from None
            if exc.code in {'WORK_CONDITION_INPUT_MISSING', 'WORK_INPUT_DOCUMENT_MISMATCH'}:
                raise ApplicationError('WORK_REVIEW_INPUT_UNAVAILABLE') from None
            raise
        if input_proposal is None:
            raise ApplicationError('WORK_REVIEW_INPUT_INVALID')
        if slots.get('proposal_ref') != asdict(input_proposal):
            raise ApplicationError('WORK_REVIEW_INPUT_MISMATCH')
        return policy, slots, value, input_proposal

    @staticmethod
    def _phase_nodes(snapshot):
        return tuple(node for node in snapshot.program.workflow.steps
                     if type(node) is OperationNode and node.operation == 'engineering.reviews.request')

    def _role_and_purpose(self, snapshot, node):
        config = thaw_value(node.config)
        if type(config) is not dict:
            raise ApplicationError('METHOD_REVIEW_PHASE_UNAVAILABLE')
        strategy = config.get('unit_submission_review_strategy')
        roles = strategy.get('roles') if type(strategy) is dict else None
        reviewer = roles.get('reviewer') if type(roles) is dict else None
        purpose = config.get('purpose')
        if type(reviewer) is not str or not reviewer or type(purpose) is not str:
            raise ApplicationError('METHOD_REVIEW_PHASE_UNAVAILABLE')
        return (reviewer,), purpose

    def _phases(self, context, snapshot, proposal, selector, slots, uow,
                proposal_revisions=()):
        """Resolve every member of the explicitly selected frozen group."""
        from ....methods import decode_review_groups, decode_review_binding
        from ....domain.artifacts.models import ArtifactRevision
        from ....domain.artifacts.refs import ArtifactRevisionRef
        from ....domain.packages.refs import ImplementationPackageRef
        from ....domain.reviews.targets import Target
        from ....application.orchestration.method_content import document_type_for_payload
        from ....methods.definitions.models.compiled import OperationNode, thaw_value
        from ....domain.common.outcomes.diagnostics import ReferenceError
        try:
            groups = decode_review_groups(snapshot.program.workflow)
            nodes = {node.id:node for node in snapshot.program.workflow.steps}
            current = nodes.get(selector.phase_key)
            spec = decode_review_binding(current)
            if spec is None:
                raise ApplicationError('WORK_REVIEW_TARGET_POLICY_UNAVAILABLE')
            group = next(g for g in groups if g.anchor_node == spec.anchor_node
                         and g.group_id == spec.group_id)
        except (StopIteration, TypeError, ValueError, ReferenceError):
            raise ApplicationError('METHOD_REVIEW_GROUP_UNAVAILABLE') from None
        if (type(current) is not OperationNode or current.operation != 'engineering.reviews.request'
                or spec is None):
            raise ApplicationError('METHOD_REVIEW_GROUP_UNAVAILABLE')
        try:
            subject_ref = self._decode_group_ref(slots[group.subject_slot])
        except (KeyError, TypeError, ValueError, ReferenceError):
            raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH') from None
        if subject_ref != selector.subject_ref:
            raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH')

        if type(proposal) is not type(None) and (
                proposal.ref != self._proposal_ref_from_slots(slots, context)):
            raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH')

        # The group declares the complete target set. Every declared source is
        # resolved against the original proposal/submission/material owner.
        target_rows = []
        revisions = {}
        for source in group.target_sources:
            refs = []
            if source.source == 'slot':
                if source.slot in slots:
                    try:
                        ref = self._decode_group_ref(slots[source.slot])
                    except (KeyError, TypeError, ValueError, ReferenceError):
                        raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE') from None
                    if type(ref) is not ArtifactRevisionRef:
                        raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
                    refs = [ref]
                elif not (proposal is not None and 'session-summary' in source.document_types):
                    raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
            elif source.source == 'proposal_proposed_revisions':
                if proposal is None:
                    raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
                refs = [mutation.proposed_ref for mutation in proposal.mutations]
            elif source.source == 'submission_output_revisions':
                if type(subject_ref) is not SubmissionRef:
                    raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
                closure = self._submission_closure(uow, subject_ref)
                if any(type(ref) is not ArtifactRevisionRef for ref in closure.submission.output_refs):
                    raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
                refs = list(closure.submission.output_refs)
            else:
                raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
            for ref in refs:
                if (ref.realm_id, ref.project_id) != (context.scope.realm_id, context.scope.project_id):
                    raise ApplicationError('METHOD_SUBJECT_OWNER_UNAVAILABLE')
                revision = uow.engineering.resolve_revision(ref)
                document_type = document_type_for_payload(snapshot, revision.payload)
                if document_type not in source.document_types:
                    continue
                target_rows.append((Target(source.role, ref), document_type, revision))
                revisions[ref] = revision
            # A summary is eligible only when this frozen source explicitly
            # declares that document type. Its exact ref is selected from the
            # Proposal's frozen exact targets and the already-resolved graph.
            if proposal is not None and 'session-summary' in source.document_types:
                from ....application.usecases.proposal_closure import proposal_exact_document_revision_ref
                schema_resource_ids=tuple(definition.schema_resource.resource_id
                    for definition in snapshot.program.document_definitions
                    if definition.document_type=='session-summary')
                summary_ref=proposal_exact_document_revision_ref(
                    proposal,proposal_revisions,document_type='session-summary',
                    schema_resource_ids=schema_resource_ids)
                if (summary_ref.realm_id,summary_ref.project_id)!=(context.scope.realm_id,context.scope.project_id):
                    raise ApplicationError('METHOD_SUBJECT_OWNER_UNAVAILABLE')
                if source.source == 'slot' and source.slot in slots:
                    if len(refs) != 1 or refs[0] != summary_ref:
                        raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
                summary_revision=uow.engineering.resolve_revision(summary_ref)
                if Target(source.role,summary_ref) not in {row[0] for row in target_rows}:
                    target_rows.append((Target(source.role,summary_ref),'session-summary',summary_revision))
                revisions[summary_ref]=summary_revision
        if not target_rows:
            raise ApplicationError('METHOD_REVIEW_TARGET_UNCOVERED')
        if len({row[0] for row in target_rows}) != len(target_rows):
            raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')

        declared_types = {doc_type for _, doc_type, _ in target_rows}
        members = []
        coverage = set()
        for member in group.members:
            node = nodes[member.request_node]
            request_config = thaw_value(node.config)
            standard_matches = tuple(s for s in snapshot.program.standard_definitions
                if s.resource_ref == member.standard_ref)
            if len(standard_matches) != 1:
                raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
            standard = standard_matches[0]
            applicable_types = set()
            for criterion in standard.criteria:
                applicable_types.update(set(criterion.applies_to or ()) or declared_types)
            selected_rows = tuple(row for row in target_rows if row[1] in applicable_types)
            if not selected_rows:
                raise ApplicationError('METHOD_REVIEW_TARGET_UNCOVERED')
            coverage.update(row[0] for row in selected_rows)
            roles, purpose = self._role_and_purpose(snapshot, node)
            if purpose != standard.purpose:
                raise ApplicationError('METHOD_REVIEW_PURPOSE_UNAVAILABLE')
            targets = TargetSet(tuple(row[0] for row in selected_rows))
            labels = tuple((target, doc_type) for target, doc_type, _ in selected_rows)
            members.append(EngineeringTargetBindings(context.scope, targets, labels,
                tuple(item.name for item in group.material_sources), roles,
                member.request_node, workflow_node_id=member.request_node,
                review_purpose=purpose))
        expected_targets = {row[0] for row in target_rows}
        if coverage != expected_targets:
            raise ApplicationError('METHOD_REVIEW_TARGET_UNCOVERED')
        selected = tuple(binding for binding in members if binding.phase_key == selector.phase_key)
        if len(selected) != 1:
            raise ApplicationError('METHOD_REVIEW_GROUP_UNAVAILABLE')
        return group, tuple(members), selected[0], subject_ref, tuple(revisions.values()), tuple(target_rows)

    @staticmethod
    def _decode_group_ref(value):
        from ....domain.artifacts.ref_codec import decode_artifact_ref
        from ....domain.changes.ref_codec import decode_proposal_ref
        from ....domain.changes.baseline_codec import decode_repository_ref
        from ....domain.packages.codec import decode_package_ref
        from ....domain.reviews.ref_codec import decode_review_ref
        from ....domain.reviews.target_codec import decode_subject_ref
        if type(value) is not dict:
            raise ReferenceError('INVALID_PARENT')
        kind=value.get('kind')
        decoder={'artifact_revision':decode_artifact_ref,'proposal':decode_proposal_ref,
            'repository_snapshot':decode_repository_ref,'implementation_package':decode_package_ref,
            'submission':decode_subject_ref,'review':decode_review_ref}.get(kind)
        if decoder is None:
            raise ReferenceError('INVALID_PARENT')
        return decoder(value)

    @staticmethod
    def _proposal_ref_from_slots(slots, context):
        try:
            ref=SQLiteWorkReviewBindings._decode_group_ref(slots['proposal_ref'])
        except (KeyError,TypeError,ValueError,ReferenceError):
            raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH') from None
        if type(ref) is not ProposalRef or (ref.realm_id,ref.project_id)!=(context.scope.realm_id,context.scope.project_id):
            raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH')
        return ref

    def _proposal_closure(self, uow, proposal_ref):
        from ....application.usecases.proposal_closure import resolve_record
        try:
            budget=uow.proposals.validated_budget()
            proposal=uow.proposals.get_proposal(proposal_ref,budget=budget)
            resolve_record(proposal,uow.proposals,budget)
            roots=(tuple(m.proposed_ref for m in proposal.mutations)
                   +tuple(m.base_ref for m in proposal.mutations if m.base_ref is not None)
                   +tuple(c.owner_revision_ref for c in proposal.claim_refs))
            from ....application.usecases.proposal_closure import proposal_review_revision_refs
            roots += proposal_review_revision_refs(proposal)
            revisions=uow.proposals.resolve_revision_graph(roots,budget)
            artifacts=tuple(uow.engineering.get_artifact(m.artifact_id) for m in proposal.mutations)
            control=uow.proposals.control_by_digest(proposal.ref.digest.hex)
            change=uow.proposals.get_change(proposal.change_id)
            # The original Change row is the membership authority. Do not call
            # a second proposal index or infer selection from selected_proposal_id.
            if proposal.proposal_id not in change.proposal_ids:
                raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH')
            if control.disposition!='available':
                raise ApplicationError('PROPOSAL_NOT_AVAILABLE')
            return proposal,revisions,artifacts,(control,change)
        except ApplicationError:
            raise
        except Exception:
            raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH') from None

    def _submission_closure(self, uow, submission_ref):
        from ....application.usecases.changes.acceptance_closure import resolve_submission_acceptance
        return resolve_submission_acceptance(uow,submission_ref)

    def _binding(self, context, snapshot, row, selector, plan):
        if (type(selector) is not WorkReviewSelector
                or (plan is not None and type(plan) is not ReviewPlan)
                or selector.scope != context.scope or selector.scope != self.scope
                or selector.run_id != row['run_id'] or self._method_ref_from_row(context,row) != self._method_ref_from_snapshot(snapshot)
                or (plan is not None and (selector.phase_key != plan.requirement.phase_key
                    or selector.method_ref != plan.requirement.method_ref))):
            raise ApplicationError('WORK_REVIEW_SELECTOR_INVALID')
        policy=self._policy(snapshot)
        try:
            slots=self._slots(row)
            input_ref=decode_artifact_ref(slots[policy['input_document_slot']])
        except (KeyError,ReferenceError,TypeError,ValueError):
            raise ApplicationError('WORK_REVIEW_INPUT_UNAVAILABLE') from None
        with self.factory.begin(context.scope,'read') as uow:
            _,slots,input_value,proposal_ref=self._work_values(uow,snapshot,row,input_ref)
            proposal,revisions,artifacts,control_change=self._proposal_closure(uow,proposal_ref)
            group,phase_bindings,binding,subject_ref,target_revisions,target_rows=self._phases(
                context,snapshot,proposal,selector,slots,uow,proposal_revisions=tuple(revisions))
            version_by_key={}
            for revision in (uow.engineering.resolve_revision(input_ref), *revisions,
                             *target_revisions):
                artifact=uow.engineering.get_artifact(revision.artifact_id)
                version_by_key[artifact.artifact_id]=artifact.version
            control,change=control_change
            reads=ReadSet(context.scope,(
                ReadVersion('proposal_control',proposal.ref.digest.hex,control.version),
                ReadVersion('change',change.change_id,change.version),
                *(ReadVersion('artifact',artifact_id,version)
                  for artifact_id,version in sorted(version_by_key.items()))))
        if selector.subject_ref != subject_ref:
            raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH')
        # The group closure is frozen on the selected method. Work input data
        # chooses only its explicit subject and references; it never trims the
        # group member set or standard target coverage.
        material_context=(group,subject_ref,target_revisions,target_rows)
        return (binding,proposal,phase_bindings,material_context,policy,slots,reads)

    @contextmanager
    def _resolve_live(self, context, plan, selector):
        row=self._run_row(context,selector.run_id)
        with self._snapshot(context,selector.method_ref) as snapshot:
            bindings,proposal,phases,adapter,policy,slots,reads=self._binding(context,snapshot,row,selector,plan)
            with self.factory.guard_read_set(reads):
                yield snapshot,bindings,proposal,phases,adapter,policy,slots,row

    def resolve_bindings(self, context, plan, *, work_selector=None):
        if work_selector is None:
            raise ApplicationError('WORK_REVIEW_SELECTOR_REQUIRED')
        with self._resolve_live(context,plan,work_selector) as (_,binding,proposal,phases,adapter,_,_,_):
            if type(work_selector.subject_ref) is SubmissionRef:
                self._validate_submission_plan(context,plan,proposal,phases,binding,
                                               work_selector.subject_ref)
            else:
                self._validate_proposal_plan(context,plan,proposal,phases,binding)
            return binding

    @contextmanager
    def guard_plan_bindings(self, context, plan, *, work_selector=None):
        """Hold original source versions and library identity through admission COMMIT."""
        if work_selector is not None:
            with self._resolve_live(context, plan, work_selector) as resolved:
                yield resolved[1]
            return
        selector, row = self._historical_row(context, plan)
        with self._resolve_historical(context, plan, selector, row) as resolved:
            yield resolved[1]

    def resolve_phase_bindings_for_work(self, context, plan, selector):
        with self._resolve_live(context,plan,selector) as (_,_,_,phases,_,_,_,_):
            if type(selector.subject_ref) is SubmissionRef:
                return tuple(p for p in phases if p.review_purpose=='acceptance')
            return tuple(p for p in phases if p.review_purpose!='acceptance')

    def resolve_proposal_for_work(self, context, plan, selector):
        if type(selector) is not WorkReviewSelector:
            raise ApplicationError('WORK_REVIEW_SELECTOR_INVALID')
        return selector.subject_ref if type(selector.subject_ref) is ProposalRef else None

    def review_selection(self, context, *, run_id, review_id, subject_ref):
        """Build a current selector/plan pair from an explicitly named subject.

        The selected ref must already be present in the original Work slots and
        is re-resolved by the same-library owner before the caller can use it.
        """
        from ....domain.common.models.values import validate_id
        from ....methods import decode_review_binding, decode_review_groups
        from ....domain.reviews.models import ReviewPlan
        from ....domain.artifacts.models import ArtifactRevision
        from ....domain.artifacts.method_binding import MethodRef
        from ....domain.common.outcomes.library_failures import EngineeringError
        try:
            validate_id(review_id)
        except ReferenceError:
            raise ApplicationError('INVALID_INPUT') from None
        if type(context) is not CommandContext or context.scope!=self.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        with self.factory.begin(context.scope,'read') as uow:
            try:
                row=uow.workflow.run_row(run_id)
            except EngineeringError as exc:
                if exc.code == 'run_not_found':
                    raise ApplicationError('WORK_BINDING_INVALID') from None
                raise
            try:
                try:
                    uow.reviews.get_plan(review_id)
                except ApplicationError as exc:
                    if exc.code!='NOT_FOUND':
                        raise
                else:
                    raise ApplicationError('WORK_REVIEW_PLAN_ALREADY_BOUND')
                ordinal=uow.workflow.next_step_ordinal(run_id)
                steps=uow.workflow.step_rows(run_id)
            except ApplicationError:
                raise
            row={**row,'run_id':run_id}
            if row.get('status')!='RUNNING' or type(row.get('cursor')) is not int:
                raise ApplicationError('WORK_REVIEW_SELECTION_UNAVAILABLE')
            try:
                method_ref=self._method_ref_from_row(context,row)
                policy_slots=self._slots(row)
                method_slots=policy_slots
            except (ApplicationError,KeyError,TypeError):
                raise ApplicationError('WORK_REVIEW_SELECTION_UNAVAILABLE') from None
            row_digest=self._row_digest(row)
        with self._snapshot(context,method_ref) as snapshot:
            nodes=snapshot.program.workflow.steps
            if not 0<=row['cursor']<len(nodes):
                raise ApplicationError('WORK_REVIEW_SELECTION_UNAVAILABLE')
            node=nodes[row['cursor']]
            if type(node) is not OperationNode or node.operation!='engineering.reviews.request':
                raise ApplicationError('WORK_REVIEW_SELECTION_UNAVAILABLE')
            attempt=1+sum(1 for step in steps if step.get('step_id')==node.id
                          and step.get('receipt_ref') is not None)
            work_policy=self._policy(snapshot)
            try:
                input_ref=decode_artifact_ref(method_slots[work_policy['input_document_slot']])
                if type(input_ref) is not ArtifactRevisionRef:
                    raise ReferenceError('INVALID_PARENT')
                group_spec=decode_review_binding(node)
                group=next(g for g in decode_review_groups(snapshot.program.workflow)
                           if g.anchor_node==group_spec.anchor_node and g.group_id==group_spec.group_id)
                actual_subject=self._decode_group_ref(method_slots[group.subject_slot])
            except (StopIteration,ApplicationError,ReferenceError,TypeError,ValueError,KeyError):
                raise ApplicationError('WORK_REVIEW_SELECTION_UNAVAILABLE') from None
            if actual_subject!=subject_ref or (subject_ref.realm_id,subject_ref.project_id)!=(context.scope.realm_id,context.scope.project_id):
                raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH')
            selector=WorkReviewSelector(context.scope,run_id,method_ref,node.id,attempt,input_ref,
                subject_ref,row_digest,ordinal)
            with self.factory.begin(context.scope,'read') as uow:
                _,slots,input_document,proposal_ref=self._work_values(uow,snapshot,row,input_ref)
                proposal,revisions,artifacts,(control,change)=self._proposal_closure(uow,proposal_ref)
                proxy=_ReviewSelection(node.id,subject_ref)
                group,phases,binding,_,target_revisions,_=self._phases(
                    context,snapshot,proposal,proxy,slots,uow,proposal_revisions=tuple(revisions))
                all_revisions={revision.ref:revision for revision in (*revisions,*target_revisions)}
                expected=self.bridge.proposal_review_requirements(snapshot,phases,proposal=proposal,
                    artifacts=tuple(artifacts),revisions=tuple(all_revisions.values()))
                matches=tuple(item for item in expected if item.phase_key==node.id)
                if len(matches)!=1:
                    raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
                plan=self.bridge.review_plan(snapshot,binding,matches[0],review_id,
                    proposal=proposal,artifacts=tuple(artifacts),revisions=tuple(all_revisions.values()),
                    phase_bindings=phases)
                version_by_id={}
                for revision in (uow.engineering.resolve_revision(input_ref),*all_revisions.values()):
                    artifact=uow.engineering.get_artifact(revision.artifact_id)
                    version_by_id[artifact.artifact_id]=artifact.version
                reads=ReadSet(context.scope,(
                    ReadVersion('proposal_control',proposal.ref.digest.hex,control.version),
                    ReadVersion('change',change.change_id,change.version),
                    *(ReadVersion('artifact',key,value) for key,value in sorted(version_by_id.items()))))
        with self.factory.guard_read_set(reads):
            pass
        return selector,plan

    def _validate_proposal_plan(self, context, plan, proposal, phases, binding):
        with self.factory.begin(context.scope,'read') as uow:
            budget=uow.proposals.validated_budget()
            roots=tuple(m.proposed_ref for m in proposal.mutations)+tuple(m.base_ref for m in proposal.mutations if m.base_ref is not None)+tuple(c.owner_revision_ref for c in proposal.claim_refs)
            from ....application.usecases.proposal_closure import proposal_review_revision_refs
            roots += proposal_review_revision_refs(proposal)
            revisions=uow.proposals.resolve_revision_graph(roots,budget)
            artifacts=tuple(uow.engineering.get_artifact(m.artifact_id) for m in proposal.mutations)
        with self._snapshot(context, plan.requirement.method_ref) as snapshot:
            expected=self.bridge.proposal_review_requirements(snapshot,phases,
                proposal=proposal,artifacts=artifacts,revisions=revisions)
        matches=tuple(r for r in expected if r.phase_key==binding.phase_key)
        if len(matches)!=1 or matches[0]!=plan.requirement:
            raise ApplicationError('METHOD_REVIEW_PLAN_CHANGED')

    def _validate_submission_plan(self, context, plan, proposal, phases, binding, submission_ref):
        from ....application.usecases.changes.acceptance_closure import resolve_submission_acceptance
        if type(submission_ref) is not SubmissionRef:
            raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH')
        with self.factory.begin(context.scope,'read') as uow:
            closure=resolve_submission_acceptance(uow,submission_ref)
        with self._snapshot(context, plan.requirement.method_ref) as snapshot:
            acceptance_phases=tuple(p for p in phases if p.review_purpose=='acceptance')
            if not acceptance_phases:
                raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH')
            expected=self.bridge.submission_review_requirements(snapshot,acceptance_phases,
                requirements=closure.requirements,revisions=closure.artifact_revisions)
        matching=tuple(r for r in expected if r.phase_key==binding.phase_key)
        if plan.requirement not in matching:
            raise ApplicationError('METHOD_REVIEW_PLAN_CHANGED')

    def check_work_review_current(self, uow, context, plan, work_selector):
        """Repeat selector validation in the same original write UoW as create_plan."""
        try:
            uow.reviews.get_plan(plan.review_id)
        except ApplicationError as exc:
            if exc.code != 'NOT_FOUND':
                raise
        else:
            # A new Work command may not attach proof to a pre-existing plan;
            # otherwise one ReviewPlan could be rebound to multiple Work rows.
            raise ApplicationError('WORK_REVIEW_PLAN_ALREADY_BOUND')
        try:
            row=uow.workflow.run_row(work_selector.run_id)
            row={**row,'run_id':work_selector.run_id}
            ordinal=uow.workflow.next_step_ordinal(work_selector.run_id)
            steps=uow.workflow.step_rows(work_selector.run_id)
        except Exception:
            raise ApplicationError('WORK_REVIEW_SELECTOR_STALE') from None
        attempt=1+sum(1 for step in steps if step.get('step_id')==work_selector.phase_key
                      and step.get('receipt_ref') is not None)
        try:
            cursor=row['cursor']
            method_ref=self._method_ref_from_row(context,row)
        except (KeyError,IndexError,TypeError,ApplicationError):
            raise ApplicationError('WORK_REVIEW_SELECTOR_STALE') from None
        if (method_ref!=work_selector.method_ref or row.get('status')!='RUNNING'
                or attempt!=work_selector.attempt or ordinal!=work_selector.expected_next_step_ordinal
                or self._row_digest(row)!=work_selector.expected_row_digest):
            raise ApplicationError('WORK_REVIEW_SELECTOR_STALE')
        slots=self._slots(row)
        if (not any(value==asdict(work_selector.input_ref) for value in slots.values())
                or not any(value==asdict(work_selector.subject_ref) for value in slots.values())):
            raise ApplicationError('WORK_REVIEW_SELECTOR_STALE')
        from ....domain.artifacts.library_material_codec import material_ref_to_dict
        original={k:v for k,v in row.items() if k!='run_id'}
        original['method_ref']=material_ref_to_dict(original['method_ref'])
        return {'row':canonical_value(canonical_bytes(original)),
                'attempt':attempt,'next_step_ordinal':ordinal}

    def work_review_result(self, context, plan, work_selector, entry, *, request, work_facts):
        if (type(entry) is not JournalEntry or entry.operation!='engineering.reviews.request'
                or entry.state!='pending' or entry.key!=context.key
                or type(request) is not dict or request.get('state')!='requested'
                or type(work_facts) is not dict
                or set(work_facts) != {'row','attempt','next_step_ordinal'}):
            raise ApplicationError('WORK_REVIEW_CORRELATION_UNAVAILABLE')
        return {'work_review':{'selector':work_review_selector_projection(work_selector),
                'plan_digest':asdict(plan.plan_digest),'review_id':plan.review_id,
                'command':{'key':asdict(entry.key),'operation_id':entry.operation_id}},
                'work_bindings':work_facts}

    def read_request_correlation(self, context, plan):
        if type(context) is not CommandContext or type(plan) is not ReviewPlan or plan.scope!=context.scope:
            raise ApplicationError('WORK_REVIEW_PROOF_UNAVAILABLE')
        with self.factory.begin(context.scope,'read') as uow:
            entry=uow.commands.find_completed_review_request(context.scope,
                review_id=plan.review_id,plan_digest=plan.plan_digest)
            if entry is None:
                raise ApplicationError('WORK_REVIEW_PROOF_UNAVAILABLE')
            try:
                result=canonical_value(entry.result_bytes)
                proof=result['work_review']
                selector=proof['selector']
                facts=result['work_bindings']
                if (type(result) is not dict or set(proof)!={'selector','plan_digest','review_id','command'}
                        or set(proof['command'])!={'key','operation_id'}
                        or entry.operation!='engineering.reviews.request' or entry.state!='completed'
                        or proof['review_id']!=plan.review_id or proof['plan_digest']!=asdict(plan.plan_digest)
                        or proof['command']!={'key':asdict(entry.key),'operation_id':entry.operation_id}
                        or type(facts) is not dict or set(facts) != {'row','attempt','next_step_ordinal'}
                        or plan.request_digest != uow.reviews.get_plan(plan.review_id).request_digest):
                    raise ValueError
                from ....application.contracts.method_work import decode_work_review_selector
                decoded=decode_work_review_selector(selector)
                if (decoded.scope!=context.scope or decoded.method_ref!=plan.requirement.method_ref
                        or decoded.phase_key!=plan.requirement.phase_key):
                    raise ValueError
            except (ApplicationError,ReferenceError,TypeError,ValueError,KeyError):
                raise ApplicationError('WORK_REVIEW_PROOF_UNAVAILABLE') from None
            return entry

    def _selector_for_plan(self, context, plan):
        entry=self.read_request_correlation(context,plan)
        result=canonical_value(entry.result_bytes)
        from ....application.contracts.method_work import decode_work_review_selector
        return decode_work_review_selector(result['work_review']['selector'])

    def _historical_row(self, context, plan):
        entry=self.read_request_correlation(context,plan)
        result=canonical_value(entry.result_bytes)
        from ....application.contracts.method_work import decode_work_review_selector
        selector=decode_work_review_selector(result['work_review']['selector'])
        facts=result['work_bindings']
        from ....domain.artifacts.library_material_codec import material_ref_from_dict
        try:
            row=canonical_value(canonical_bytes(facts['row']))
            row['method_ref']=material_ref_from_dict(row['method_ref'])
            row['run_id']=selector.run_id
            method_ref=self._method_ref_from_row(context,row)
            if (method_ref!=selector.method_ref or type(row['cursor']) is not int
                    or facts['attempt']!=selector.attempt
                    or facts['next_step_ordinal']!=selector.expected_next_step_ordinal
                    or self._row_digest(row)!=selector.expected_row_digest):
                raise ValueError
            return selector,row
        except (KeyError,ReferenceError,TypeError,ValueError):
            raise ApplicationError('WORK_REVIEW_PROOF_UNAVAILABLE') from None

    @contextmanager
    def _resolve_historical(self, context, plan, selector, row):
        with self._snapshot(context,selector.method_ref) as snapshot:
            bindings,proposal,phases,adapter,policy,slots,reads=self._binding(
                context,snapshot,row,selector,plan)
            with self.factory.guard_read_set(reads):
                yield snapshot,bindings,proposal,phases,adapter,policy,slots,row

    def resolve_phase_bindings_for_plan(self, context, plan):
        selector,row=self._historical_row(context,plan)
        with self._resolve_historical(context,plan,selector,row) as (_,_,_,phases,_,_,_,_):
            if type(selector.subject_ref) is SubmissionRef:
                return tuple(p for p in phases if p.review_purpose=='acceptance')
            return tuple(p for p in phases if p.review_purpose!='acceptance')

    def resolve_proposal_for_plan(self, context, plan):
        selector,row=self._historical_row(context,plan)
        if type(selector.subject_ref) is ProposalRef:
            return selector.subject_ref
        if type(selector.subject_ref) is SubmissionRef:
            return None
        # Other review subjects (for example a correction-plan revision) have
        # their own method requirements. The Work's Proposal context is not
        # their frozen Proposal review subject.
        return None

    def resolve_plan_bindings(self, context, plan):
        selector,row=self._historical_row(context,plan)
        with self._resolve_historical(context,plan,selector,row) as (_,binding,_,_,_,_,_,_):
            return binding

    def _readiness_source(self, context, snapshot, *, phase_key, input_ref, subject_ref, view):
        """Resolve a plan's exact compiled group against the live Work view."""
        from ....methods import decode_review_groups
        from ....methods.definitions.models.compiled import WaitNode
        from ....application.contracts.run_waits import run_wait_row_digest
        if (type(context) is not CommandContext or context.scope!=self.scope
                or type(view) is not dict or type(phase_key) is not str
                or not isinstance(input_ref,ArtifactRevisionRef)):
            raise ApplicationError('WORK_REVIEW_READINESS_UNAVAILABLE')
        run_id=view.get('run_id')
        if type(run_id) is not str:
            raise ApplicationError('WORK_REVIEW_READINESS_UNAVAILABLE')
        row=self._run_row(context,run_id)
        if (row.get('status')!='WAITING_FOR_CONDITION' or self._row_digest(row)!=view.get('row_digest')
                or type(row.get('cursor')) is not int
                or type(view.get('row')) is not dict
                or view['row'].get('cursor')!=row.get('cursor')):
            raise ApplicationError('WORK_REVIEW_SELECTOR_STALE')
        method_ref=self._method_ref_from_row(context,row)
        if method_ref!=self._method_ref_from_snapshot(snapshot):
            raise ApplicationError('WORK_METHOD_MISMATCH')
        if not 0<=row['cursor']<len(snapshot.program.workflow.steps):
            raise ApplicationError('WORK_REVIEW_READINESS_UNAVAILABLE')
        wait=snapshot.program.workflow.steps[row['cursor']]
        if type(wait) is not WaitNode:
            raise ApplicationError('WORK_REVIEW_READINESS_UNAVAILABLE')
        slots=self._slots(row)
        policy=self._policy(snapshot)
        with self.factory.begin(context.scope,'read') as uow:
            _,slots,input_document,proposal_ref=self._work_values(uow,snapshot,row,input_ref)
            proposal,revisions,artifacts,(control,change)=self._proposal_closure(uow,proposal_ref)
            current_input=uow.engineering.resolve_revision(input_ref)
            event_slots=policy['waits'].get(wait.id,{}).get('event_slots',{})
            from ...method_work import selected_wait_input_event
            event_map=selected_wait_input_event(
                policy,input_document,wait.id,row,snapshot.program)
            for group in decode_review_groups(snapshot.program.workflow):
                member=next((item for item in group.members if item.request_node==phase_key),None)
                if member is None:
                    continue
                wait_family=policy['waits'].get(wait.id,{}).get('family')
                if ((wait_family=='review_plan_ready' and wait.next!=phase_key)
                        or (wait_family=='review_response_ready' and wait.id!=member.response_wait)):
                    raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH')
                if group.subject_slot not in slots:
                    # The selected subject may be an incoming value from this
                    # exact Work wait. The caller has already decoded it from
                    # the method-declared binding; no slot alias is inferred.
                    slots[group.subject_slot]=asdict(subject_ref)
                subject=self._decode_group_ref(slots[group.subject_slot])
                if subject!=subject_ref:
                    raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH')
                for event_name,selector in event_slots.items():
                    binding=next((item for item in (() if wait.bind is None else wait.bind.entries)
                                  if item.slot=='event.'+event_name),None)
                    if binding is None or binding.name not in {group.subject_slot,
                            *(source.slot for source in group.target_sources if source.slot is not None)}:
                        continue
                    if type(selector) is not dict:
                        raise ApplicationError('WORK_CONDITION_INPUT_INVALID')
                    if selector.get('source')=='work_input':
                        field=selector.get('field')
                        if type(field) is not str or field not in event_map:
                            raise ApplicationError('WORK_CONDITION_INPUT_MISSING')
                        slots[binding.name]=event_map[field]
                    elif selector.get('source')=='slot':
                        slot=selector.get('slot')
                        if type(slot) is not str or slot not in slots:
                            raise ApplicationError('WORK_CONDITION_INPUT_MISSING')
                        slots[binding.name]=slots[slot]
                proxy=type('_ReadinessSelection',(),{'phase_key':phase_key,'subject_ref':subject_ref})()
                _,phase_bindings,binding,_,target_revisions,target_rows=self._phases(
                    context,snapshot,proposal,proxy,slots,uow,proposal_revisions=tuple(revisions))
                all_revisions={revision.ref:revision for revision in (*revisions,*target_revisions)}
                version_by_id={}
                for revision in (current_input,*all_revisions.values()):
                    artifact=uow.engineering.get_artifact(revision.artifact_id)
                    version_by_id[artifact.artifact_id]=artifact.version
                read_set=ReadSet(context.scope,(
                    ReadVersion('proposal_control',proposal.ref.digest.hex,control.version),
                    ReadVersion('change',change.change_id,change.version),
                    *(ReadVersion('artifact',key,value) for key,value in sorted(version_by_id.items()))))
                return proposal,tuple(artifacts),tuple(all_revisions.values()),phase_bindings,binding,read_set,member
        raise ApplicationError('WORK_REVIEW_GROUP_UNAVAILABLE')

    @contextmanager
    def guard_plan_ready(self, context, snapshot, plan, *, phase_key, input_ref,
                         subject_ref, view):
        from ....application.contracts.run_waits import ReviewReadiness
        from ....domain.reviews.models import ReviewPlan
        method_ref=self._method_ref_from_snapshot(snapshot)
        if type(plan) is not ReviewPlan or plan.requirement.method_ref!=method_ref:
            raise ApplicationError('WORK_REVIEW_READINESS_UNAVAILABLE')
        with self.methods.guard_method(context,method_ref) as current_snapshot:
            proposal,artifacts,revisions,phases,binding,reads,member=self._readiness_source(
                context,current_snapshot,phase_key=phase_key,input_ref=input_ref,
                subject_ref=subject_ref,view=view)
            cursor=view.get('row',{}).get('cursor')
            if (type(cursor) is not int or not 0<=cursor<len(current_snapshot.program.workflow.steps)
                    or self._policy(current_snapshot)['waits'].get(
                        current_snapshot.program.workflow.steps[cursor].id,{}).get('family')!='review_plan_ready'
                    or member.request_node!=phase_key):
                raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH')
            if plan.requirement.phase_key!=phase_key:
                raise ApplicationError('METHOD_REVIEW_PLAN_CHANGED')
            expected=self.bridge.review_plan(current_snapshot,binding,plan.requirement,
                plan.review_id,proposal=proposal,artifacts=artifacts,revisions=revisions,
                phase_bindings=phases)
            if expected!=plan:
                raise ApplicationError('METHOD_REVIEW_PLAN_CHANGED')
            with self.factory.guard_read_set(reads):
                yield ReviewReadiness(plan,input_ref,subject_ref,reads)

    @contextmanager
    def guard_response_ready(self, context, snapshot, plan, request, raw_response_ref, *,
                             phase_key, input_ref, subject_ref, view):
        # A durable blob plus a requested plan proves neither reviewer identity
        # nor response provenance. Until the original EngineeringReviewAdmission
        # is bound here, refusing is safer than advertising response readiness.
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        yield  # pragma: no cover - keeps this a context-manager generator.

    def material_inputs_for_plan(self, context, plan):
        selector,row=self._historical_row(context,plan)
        with self._resolve_historical(context,plan,selector,row) as (
                snapshot,binding,proposal,_,material_context,_,slots,_):
            group,subject_ref,target_revisions,target_rows=material_context
            with self.factory.begin(context.scope,'read') as uow:
                values,pending_sources=self._material_values(uow,snapshot,group,proposal,subject_ref,
                                                            target_revisions,target_rows,slots)
            if pending_sources:
                from ....domain.common.mechanisms.selection import SelectorChecks
                from ....domain.artifacts.provenance import ExcerptCapture, VersionCapture
                checks=SelectorChecks()
                for name,ref,sources in pending_sources:
                    selected_by_id={}
                    rows=[]
                    for source in sources:
                        if type(source.capture) is VersionCapture:
                            raise ApplicationError('METHOD_SOURCE_CAPTURE_UNAVAILABLE')
                        if type(source.capture) is not ExcerptCapture or source.kind=='artifact':
                            raise ApplicationError('METHOD_SOURCE_CAPTURE_UNAVAILABLE')
                        raw=self.blobs.read_verified(source.capture.blob_ref)
                        try:
                            selected=checks.check(raw,source.capture.selector,source.capture.excerpt_digest)
                        except ReferenceError:
                            raise ApplicationError('METHOD_SOURCE_CAPTURE_INVALID') from None
                        selected_by_id[source.source_id]=selected
                        rows.append({'source':asdict(source),'selected_utf8_b64':base64.b64encode(selected).decode('ascii')})
                    links=tuple(proposal.evidence_links)+tuple(
                        link for revision in target_revisions for link in revision.evidence_links)
                    for link in links:
                        selected=selected_by_id.get(link.source_ref.source_id)
                        if selected is None:
                            continue
                        try:
                            checks.check(selected,link.source_selector)
                        except ReferenceError:
                            raise ApplicationError('METHOD_SOURCE_CAPTURE_INVALID') from None
                    values.append(ResolvedReviewMaterial(name,ref,'source_captures',
                                                         canonical_bytes(rows)))
            return tuple(values)

    def _material_values(self,uow,snapshot,group,proposal,subject_ref,
                         target_revisions,target_rows,slots):
        """Resolve only compiled, named owner projections to immutable DTOs."""
        from dataclasses import asdict
        from ....domain.artifacts.models import InlinePayload, MethodPayload
        from ....domain.artifacts.provenance import ExcerptCapture, VersionCapture
        from ....domain.packages.refs import ImplementationPackageRef
        from ....domain.reviews.refs import ReviewRef
        from ....domain.artifacts.ref_codec import decode_artifact_ref
        from ....domain.packages.codec import decode_package_ref
        from ....domain.reviews.ref_codec import decode_review_ref
        from ordessa_infrastructure.encoding import canonical_bytes
        from ....domain.common.outcomes.diagnostics import ReferenceError

        revisions={revision.ref:revision for revision in target_revisions}
        values=[]
        pending_sources=[]
        for source in group.material_sources:
            ref=None
            value=None
            projection=source.source
            if source.source=='slot':
                try:
                    ref=decode_artifact_ref(slots[source.slot])
                    revision=uow.engineering.resolve_revision(ref)
                except (KeyError,ReferenceError,TypeError,ValueError):
                    raise ApplicationError('METHOD_INPUT_SLOT_UNAVAILABLE') from None
                if type(revision.payload) is MethodPayload:
                    value=revision.payload.content.value
                elif type(revision.payload) is InlinePayload:
                    value=revision.payload.value
                else:
                    raise ApplicationError('METHOD_INPUT_CONTENT_UNAVAILABLE')
                ref=revision.ref
            elif source.source=='proposal_record':
                try:
                    selected=(self._decode_group_ref(slots[source.slot]) if source.slot is not None
                              else subject_ref)
                    if type(selected) is not ProposalRef:
                        raise ReferenceError('INVALID_PARENT')
                    selected_proposal=uow.proposals.get_proposal(selected)
                    if type(subject_ref) is ProposalRef:
                        related=selected==subject_ref
                    elif type(subject_ref) is SubmissionRef:
                        related=selected in {item.ref for item in
                                             self._submission_closure(uow,subject_ref).proposals}
                    elif type(subject_ref) is ImplementationPackageRef:
                        related=selected in uow.implementation.resolve_package(
                            subject_ref).payload.change_set.proposal_refs
                    else:
                        related=False
                    if not related or selected_proposal.method_ref!=self._method_ref_from_snapshot(snapshot):
                        raise ReferenceError('INVALID_PARENT')
                    ref=selected
                    value=selected_proposal.projection()
                except (ApplicationError,ReferenceError,TypeError,ValueError):
                    raise ApplicationError('METHOD_PROPOSAL_SOURCE_UNAVAILABLE') from None
            elif source.source=='implementation_intent':
                try:
                    selected=(self._decode_group_ref(slots[source.slot]) if source.slot is not None
                              else subject_ref)
                    if type(selected) is not ProposalRef:
                        raise ReferenceError('INVALID_PARENT')
                    selected_proposal=uow.proposals.get_proposal(selected)
                    if type(subject_ref) is ProposalRef:
                        related=selected==subject_ref
                    elif type(subject_ref) is SubmissionRef:
                        related=selected in {item.ref for item in
                                             self._submission_closure(uow,subject_ref).proposals}
                    elif type(subject_ref) is ImplementationPackageRef:
                        related=selected in uow.implementation.resolve_package(
                            subject_ref).payload.change_set.proposal_refs
                    else:
                        related=False
                    if not related or selected_proposal.method_ref!=self._method_ref_from_snapshot(snapshot):
                        raise ReferenceError('INVALID_PARENT')
                except (ApplicationError,ReferenceError,TypeError,ValueError):
                    raise ApplicationError('METHOD_IMPLEMENTATION_INTENT_UNAVAILABLE') from None
                if selected_proposal.implementation_intent is None:
                    raise ApplicationError('METHOD_IMPLEMENTATION_INTENT_UNAVAILABLE')
                ref=selected_proposal.ref
                value=asdict(selected_proposal.implementation_intent)
            elif source.source=='targets':
                ref=subject_ref
                value=[{'target':asdict(target),'document_type':document_type,
                        'revision':revision.projection()}
                       for target,document_type,revision in target_rows]
            elif source.source=='method_content':
                matches=[(target,document_type,revision) for target,document_type,revision in target_rows
                         if type(revision.payload) is MethodPayload]
                if not matches:
                    raise ApplicationError('METHOD_CONTENT_SOURCE_UNAVAILABLE')
                ref=subject_ref
                value=[{'target':asdict(target),'document_type':document_type,
                        'ref':asdict(revision.ref),
                        'content':revision.payload.content.projection()}
                       for target,document_type,revision in matches]
            elif source.source=='claim_bindings':
                ref=subject_ref
                value=[{'target':asdict(target),'claims':[asdict(item) for item in revision.claims],
                        'evidence_links':[asdict(item) for item in revision.evidence_links]}
                       for target,_,revision in target_rows]
            elif source.source=='package_record':
                try:
                    package_ref=(decode_package_ref(slots[source.slot]) if source.slot is not None
                                 else subject_ref if type(subject_ref) is ImplementationPackageRef else None)
                    if package_ref is None:
                        raise ReferenceError('INVALID_PARENT')
                    package=uow.implementation.resolve_package(package_ref)
                    if package.payload.method_ref!=self._method_ref_from_snapshot(snapshot):
                        raise ReferenceError('INVALID_PARENT')
                except (ApplicationError,ReferenceError,TypeError,ValueError):
                    raise ApplicationError('METHOD_PACKAGE_SOURCE_UNAVAILABLE') from None
                ref=package.ref
                value=asdict(package)
            elif source.source=='submission_record':
                try:
                    submission_ref=(self._decode_group_ref(slots[source.slot]) if source.slot is not None
                                    else subject_ref)
                    if type(submission_ref) is not SubmissionRef:
                        raise ReferenceError('INVALID_PARENT')
                    submission=uow.submissions.resolve(submission_ref)
                    if (submission.scope!=uow.scope
                            or submission.method_content is None
                            or submission.package_ref.realm_id!=uow.scope.realm_id
                            or submission.package_ref.project_id!=uow.scope.project_id):
                        raise ReferenceError('INVALID_PARENT')
                    if type(subject_ref) is ImplementationPackageRef and submission.package_ref!=subject_ref:
                        raise ReferenceError('INVALID_PARENT')
                    if type(subject_ref) is SubmissionRef and submission.ref!=subject_ref:
                        raise ReferenceError('INVALID_PARENT')
                except (ApplicationError,ReferenceError,TypeError,ValueError):
                    raise ApplicationError('METHOD_SUBMISSION_SOURCE_UNAVAILABLE') from None
                ref=submission.ref
                from ....domain.changes.submission_codec import submission_projection
                value=submission_projection(submission)
            elif source.source=='review_record':
                try:
                    review_ref=(decode_review_ref(slots[source.slot]) if source.slot is not None
                                else subject_ref if type(subject_ref) is ReviewRef else None)
                    if review_ref is None:
                        raise ReferenceError('INVALID_PARENT')
                    controlled=uow.reviews.get_review(review_ref)
                    record=controlled.record
                    if record.plan.requirement.method_ref!=self._method_ref_from_snapshot(snapshot):
                        raise ReferenceError('INVALID_PARENT')
                    if type(subject_ref) is ReviewRef:
                        if record.ref!=subject_ref:
                            raise ReferenceError('INVALID_PARENT')
                    elif type(subject_ref) is SubmissionRef:
                        submission=self._submission_closure(uow,subject_ref).submission
                        output_refs={ref for ref in submission.output_refs
                                     if type(ref) is ArtifactRevisionRef}
                        reviewed_refs={target.ref for target in record.plan.requirement.expected_targets.targets
                                       if type(target.ref) is ArtifactRevisionRef}
                        if (record.plan.requirement.purpose!='acceptance'
                                or reviewed_refs!=output_refs):
                            raise ReferenceError('INVALID_PARENT')
                    elif type(subject_ref) is ImplementationPackageRef:
                        package=uow.implementation.resolve_package(subject_ref)
                        if record.ref not in package.payload.required_review_refs:
                            raise ReferenceError('INVALID_PARENT')
                    else:
                        # Rework stages can name prior package, submission and
                        # review records in explicit slots. Correlate them via
                        # the original records; scope/method equality alone is
                        # not enough to treat unrelated history as a rework.
                        related_submission=None
                        related_package=None
                        for declared in group.material_sources:
                            if declared.source=='submission_record':
                                raw=(slots.get(declared.slot) if declared.slot is not None
                                     else asdict(subject_ref) if type(subject_ref) is SubmissionRef else None)
                                if raw is not None:
                                    candidate=self._decode_group_ref(raw)
                                    if type(candidate) is SubmissionRef:
                                        related_submission=uow.submissions.resolve(candidate)
                            elif declared.source=='package_record':
                                raw=(slots.get(declared.slot) if declared.slot is not None
                                     else asdict(subject_ref) if type(subject_ref) is ImplementationPackageRef else None)
                                if raw is not None:
                                    candidate=self._decode_group_ref(raw)
                                    if type(candidate) is ImplementationPackageRef:
                                        related_package=uow.implementation.resolve_package(candidate)
                        if related_submission is not None:
                            if (related_package is not None
                                    and related_submission.package_ref!=related_package.ref):
                                raise ReferenceError('INVALID_PARENT')
                            output_refs={ref for ref in related_submission.output_refs
                                         if type(ref) is ArtifactRevisionRef}
                            reviewed_refs={target.ref for target in record.plan.requirement.expected_targets.targets
                                           if type(target.ref) is ArtifactRevisionRef}
                            acceptance_link=(record.plan.requirement.purpose=='acceptance'
                                             and reviewed_refs==output_refs)
                            package_link=(related_package is not None
                                and record.ref in related_package.payload.required_review_refs)
                            if not (acceptance_link or package_link):
                                raise ReferenceError('INVALID_PARENT')
                        elif related_package is None or record.ref not in related_package.payload.required_review_refs:
                            raise ReferenceError('INVALID_PARENT')
                except (ApplicationError,ReferenceError,TypeError,ValueError):
                    raise ApplicationError('METHOD_REVIEW_RECORD_UNAVAILABLE') from None
                ref=record.ref
                value=record.projection()
            elif source.source=='acceptance_mapping':
                try:
                    selected=(self._decode_group_ref(slots[source.slot]) if source.slot is not None
                              else subject_ref)
                except (ReferenceError,TypeError,ValueError,KeyError):
                    raise ApplicationError('METHOD_ACCEPTANCE_MAPPING_UNAVAILABLE') from None
                if (type(subject_ref) is not SubmissionRef or selected!=subject_ref
                        or type(selected) is not SubmissionRef):
                    raise ApplicationError('METHOD_ACCEPTANCE_MAPPING_UNAVAILABLE')
                from ....application.usecases.changes.acceptance_closure import resolve_submission_acceptance
                closure=resolve_submission_acceptance(uow,selected)
                ref=selected
                value={'requirements':[asdict(item) for item in closure.requirements],
                       'artifact_revisions':[asdict(item.ref) for item in closure.artifact_revisions]}
            elif source.source=='source_captures':
                all_sources=list(proposal.basis_sources)
                for revision in target_revisions:
                    all_sources.extend(revision.sources)
                pending_sources.append((source.name,subject_ref,tuple(all_sources)))
                continue
            else:
                raise ApplicationError('METHOD_MATERIAL_SOURCE_UNAVAILABLE')
            try:
                values.append(ResolvedReviewMaterial(source.name,ref,projection,canonical_bytes(value)))
            except (ReferenceError,TypeError,ValueError):
                raise ApplicationError('METHOD_MATERIAL_SOURCE_UNAVAILABLE') from None
        return tuple(values),tuple(pending_sources)

    def _historical_material_slots(self, context, selector, row, binding):
        slots=self._slots(row)
        result=[]
        for name in binding.input_slots:
            if name=='proposal_ref':
                continue
            try:
                ref=decode_artifact_ref(slots[name])
            except (KeyError,ReferenceError,TypeError,ValueError):
                raise ApplicationError('METHOD_INPUT_SLOT_UNAVAILABLE') from None
            if type(ref) is not ArtifactRevisionRef:
                raise ApplicationError('METHOD_INPUT_SLOT_UNAVAILABLE')
            result.append((name,ref))
        return tuple(result)

    def resolve_review_proposal_for_plan(self, context, plan):
        selector=self._selector_for_plan(context,plan)
        return selector.subject_ref if type(selector.subject_ref) is ProposalRef else None

    def resolve_review_submission_for_plan(self, context, plan):
        selector=self._selector_for_plan(context,plan)
        return selector.subject_ref if type(selector.subject_ref) is SubmissionRef else None

    def resolve_submission_bindings_for_plan(self, context, plan):
        selector=self._selector_for_plan(context,plan)
        if type(selector.subject_ref) is not SubmissionRef:
            return ()
        return tuple(binding for binding in self.resolve_phase_bindings_for_plan(context,plan)
                     if binding.review_purpose=='acceptance')

    def guard_current_request(self, context, plan, request):
        """Refuse sending after the selected review stage has moved away."""
        selector,row=self._historical_row(context,plan)
        current=self._run_row(context,selector.run_id)
        with self._snapshot(context,selector.method_ref) as snapshot:
            if self._method_ref_from_row(context,current)!=selector.method_ref:
                raise ApplicationError('WORK_REVIEW_STALE')
            from ....application.orchestration.method_runs import observed_loop_round
            saved_round=observed_loop_round(snapshot.program,row,selector.phase_key)
            current_round=observed_loop_round(snapshot.program,current,selector.phase_key)
            if saved_round!=current_round:
                raise ApplicationError('WORK_REVIEW_STALE')
            steps=snapshot.program.workflow.steps
            saved_cursor=row['cursor']
            cursor=current.get('cursor')
            if type(cursor) is not int or not 0 <= cursor < len(steps):
                raise ApplicationError('WORK_REVIEW_STALE')
            review_node=steps[saved_cursor] if saved_cursor < len(steps) else None
            if type(review_node) is not OperationNode or review_node.id != selector.phase_key:
                raise ApplicationError('WORK_REVIEW_STALE')
            policy=self._policy(snapshot)
            slots=self._slots(current)
            try:
                input_ref=decode_artifact_ref(slots[policy['input_document_slot']])
            except (KeyError,ReferenceError,TypeError,ValueError):
                raise ApplicationError('WORK_REVIEW_INPUT_UNAVAILABLE') from None
            if not any(v==asdict(selector.subject_ref) for v in slots.values()):
                raise ApplicationError('WORK_REVIEW_STALE')
            if cursor == saved_cursor:
                node=steps[cursor] if cursor < len(steps) else None
                if node is not review_node:
                    raise ApplicationError('WORK_REVIEW_STALE')
            else:
                node=steps[cursor] if cursor < len(steps) else None
                completed=next((b.target for b in review_node.outcomes.entries
                                if b.outcome=='completed'),None)
                wait_decl=policy['waits'].get(node.id) if type(node).__name__=='WaitNode' else None
                family=wait_decl.get('family') if type(wait_decl) is dict else None
                if (type(node).__name__ != 'WaitNode' or completed is None
                        or completed.next != node.id or type(wait_decl) is not dict
                        or family not in {'review_gate','review_response_ready'}
                        or wait_decl.get('phase_key')!=selector.phase_key):
                    raise ApplicationError('WORK_REVIEW_STALE')
                if family=='review_response_ready':
                    event_slots=wait_decl.get('event_slots')
                    response_event=wait_decl.get('response_event')
                    if (type(response_event) is not str or type(event_slots) is not dict
                            or type(event_slots.get(response_event)) is not dict
                            or event_slots[response_event].get('source')!='blob_utf8'):
                        raise ApplicationError('WORK_REVIEW_STALE')
            with self.factory.begin(context.scope,'read') as uow:
                from ...method_work import SQLitePersistedMethodWorkSource
                SQLitePersistedMethodWorkSource._input_progression_in_uow(
                    uow,snapshot,policy,selector.input_ref,input_ref,run_id=selector.run_id)
                self._work_values(uow,snapshot,current,input_ref)
                current_request=uow.reviews.get_request(plan.review_id)
            if (current_request.state!='requested' or current_request.version!=request.version
                    or current_request.fence!=request.fence):
                raise ApplicationError('WORK_REVIEW_STALE')
        if request.review_id != plan.review_id:
            raise ApplicationError('REVIEW_REQUEST_CHANGED')

    def resolve_intent_bindings(self, context, method_ref, proposal_ref):
        """Bind only Proposal phases for the explicit Work start selection."""
        from ....methods import decode_review_groups
        if (type(context) is not CommandContext or context.scope!=self.scope
                or type(proposal_ref) is not ProposalRef
                or (proposal_ref.realm_id,proposal_ref.project_id)!=(context.scope.realm_id,context.scope.project_id)):
            raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH')
        with self._snapshot(context,method_ref) as snapshot:
            with self.factory.begin(context.scope,'read') as uow:
                proposal,revisions,artifacts,(control,change)=self._proposal_closure(uow,proposal_ref)
                groups=decode_review_groups(snapshot.program.workflow)
                selected=[]
                for group in groups:
                    # This entry point receives exactly one ProposalRef and no
                    # other Work slots. It can resolve only a group whose
                    # declared subject and target sources need no unprovided
                    # values; required slot sources fail closed in _phases.
                    if group.subject_slot!='proposal_ref':
                        continue
                    slots={'proposal_ref':asdict(proposal_ref),group.subject_slot:asdict(proposal_ref)}
                    proxy=type('_StartSelection',(),{'phase_key':group.members[0].request_node,
                                                     'subject_ref':proposal_ref})()
                    _,phases,_,_,_,_=self._phases(context,snapshot,proposal,proxy,slots,uow,
                        proposal_revisions=tuple(revisions))
                    selected.extend(phases)
                if not selected:
                    raise ApplicationError('WORK_REVIEW_BINDING_UNAVAILABLE')
                result=tuple(selected)
                version_by_key={}
                for ref in revisions:
                    artifact=uow.engineering.get_artifact(ref.artifact_id)
                    version_by_key[artifact.artifact_id]=artifact.version
                read_set=ReadSet(context.scope,(
                    ReadVersion('proposal_control',proposal_ref.digest.hex,control.version),
                    ReadVersion('change',change.change_id,change.version),
                    *(ReadVersion('artifact',artifact_id,version)
                      for artifact_id,version in sorted(version_by_key.items()))))
        # Work.start performs its own same-owner proposal read and original
        # start-CAS; this fence makes the review-source snapshot independently
        # fail closed while its exact bindings are being returned.
        with self.factory.guard_read_set(read_set):
            return result

    def resolve_review_submission(self, context, method_ref, phase_key):
        raise ApplicationError('WORK_REVIEW_PLAN_REQUIRED')

    def resolve_review_proposal(self, context, method_ref, phase_key):
        raise ApplicationError('WORK_REVIEW_PLAN_REQUIRED')

    def resolve_submission_bindings(self, context, method_ref, submission_ref):
        raise ApplicationError('WORK_REVIEW_PLAN_REQUIRED')


class SQLiteWorkReviewReadiness:
    """Original Work inputs plus the selected original reviewer admission.

    Assembly supplies the exact instances; this adapter cannot create reviewer
    roles, authenticate response text, or replace missing native source proof.
    """

    def __init__(self, factory, method_control, *, bindings, admission=None):
        if (type(bindings) is not SQLiteWorkReviewBindings
                or bindings.factory is not factory or bindings.methods is not method_control
                or getattr(method_control, 'factory', None) is not factory
                or (admission is not None and (
                    getattr(admission, 'factory', None) is not factory
                    or getattr(admission, 'methods', None) is not method_control
                    or getattr(admission, 'bindings', None) is not bindings
                    or not callable(getattr(admission, 'verify_response', None))
                    or not callable(getattr(admission, 'guard_plan', None))
                    or not callable(getattr(admission, 'guard_trust', None))))):
            raise ApplicationError('WORK_REVIEW_READINESS_UNAVAILABLE')
        self.factory, self.methods = factory, method_control
        self.bindings, self.admission = bindings, admission

    @contextmanager
    def guard_plan_ready(self, context, snapshot, plan, *, phase_key, input_ref,
                         subject_ref, view):
        with self.bindings.guard_plan_ready(context, snapshot, plan,
                phase_key=phase_key, input_ref=input_ref, subject_ref=subject_ref,
                view=view) as readiness:
            yield readiness

    @contextmanager
    def guard_response_ready(self, context, snapshot, plan, request, raw_response_ref, *,
                             phase_key, input_ref, subject_ref, view):
        from ....application.contracts.run_waits import ReviewReadiness
        from ....domain.common.models.refs import BlobRef
        from ....domain.reviews.models import ReviewRequestState, ReviewRequestExpectation, ReviewRecord
        if self.admission is None:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        method_ref = self.bindings._method_ref_from_snapshot(snapshot)
        if (type(plan) is not ReviewPlan or type(request) is not ReviewRequestState
                or type(raw_response_ref) is not BlobRef
                or plan.scope != context.scope or plan.requirement.method_ref != method_ref
                or plan.requirement.phase_key != phase_key
                or request.scope != context.scope or request.review_id != plan.review_id
                or request.state != 'requested'):
            raise ApplicationError('WORK_REVIEW_READINESS_UNAVAILABLE')
        with self.methods.guard_method(context, method_ref) as current_snapshot:
            *_, reads, member = self.bindings._readiness_source(context, current_snapshot,
                phase_key=phase_key, input_ref=input_ref, subject_ref=subject_ref, view=view)
            cursor = view.get('row', {}).get('cursor')
            steps = current_snapshot.program.workflow.steps
            if (type(cursor) is not int or not 0 <= cursor < len(steps)
                    or steps[cursor].id != member.response_wait):
                raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH')
            selector = self.bindings._selector_for_plan(context, plan)
            if (selector.run_id != view.get('run_id') or selector.subject_ref != subject_ref):
                raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH')
            _, historical_row = self.bindings._historical_row(context, plan)
            current_row = self.bindings._run_row(context, selector.run_id)
            if self.bindings._method_ref_from_row(context, current_row) != method_ref:
                raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH')
            from ....application.orchestration.method_runs import observed_loop_round
            historical_round = observed_loop_round(
                current_snapshot.program, historical_row, selector.phase_key)
            current_round = observed_loop_round(
                current_snapshot.program, current_row, member.request_node)
            if historical_round != current_round:
                raise ApplicationError('WORK_REVIEW_CORRELATION_MISMATCH')
            from ...method_work import SQLitePersistedMethodWorkSource
            with self.factory.begin(context.scope, 'read') as uow:
                if uow.reviews.get_plan(plan.review_id) != plan or uow.reviews.get_request(plan.review_id) != request:
                    raise ApplicationError('REVIEW_REQUEST_CHANGED')
                SQLitePersistedMethodWorkSource._input_progression_in_uow(uow, current_snapshot,
                    self.bindings._policy(current_snapshot, uow=uow), selector.input_ref, input_ref,
                    run_id=selector.run_id)
            reads = ReadSet(context.scope, reads.versions, (), (), (
                ReviewRequestExpectation(context.scope, request.review_id, plan.plan_digest,
                                         request.version, request.fence),))
            with self.factory.guard_read_set(reads), self.admission.guard_plan(context, plan):
                record = self.admission.verify_response(context, plan, request, raw_response_ref)
                if (type(record) is not ReviewRecord or record.plan != plan
                        or record.identity.schema_version != 2
                        or record.raw_response_ref != raw_response_ref):
                    raise ApplicationError('REVIEW_SOURCE_INVALID')
                # The source/trust guard remains held through the caller's CAS.
                # Its verdict may be fail/indeterminate: readiness is not pass.
                with self.admission.guard_trust(context, (record,)):
                    yield ReviewReadiness(plan, input_ref, subject_ref, reads, raw_response_ref)


__all__=['SQLiteWorkReviewBindings', 'SQLiteWorkReviewReadiness']
