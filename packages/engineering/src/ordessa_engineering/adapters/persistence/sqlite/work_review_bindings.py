"""Plan-aware review bindings over the original persisted MethodRun and journal.

This adapter derives phase targets from an explicitly selected Work row and the
method snapshot pinned to that row. It does not persist a phase registry or
select a latest proposal. Historical access is recovered only from the exact
completed reviews.request journal result that recorded the Work selector.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import json

from ....application.contracts.commands import CommandContext, JournalEntry
from ....application.contracts.errors import ApplicationError
from ....application.contracts.method_work import (
    WorkReviewSelector, work_review_selector_projection,
)
from ....application.contracts.snapshots import EngineeringTargetBindings
from ....application.orchestration.method_bridge import MethodBridge
from ....application.contracts.run_waits import run_wait_row_digest
from ....application.usecases.proposal_closure import resolve_record
from ....domain.artifacts.method_binding import MethodRef
from ....domain.artifacts.models import MethodPayload
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
from ....domain.reviews.refs import SubmissionRef
from ....domain.reviews.targets import Target, TargetSet
from ....methods.definitions.models.compiled import OperationNode, thaw_value
from ....methods.loading.parsing import parse_document
from ordessa_infrastructure.encoding import canonical_bytes
from .review_bindings import ConfiguredReviewPhase, SQLiteReviewBindings


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

    def _policy(self, snapshot):
        try:
            manifest = parse_document(self.methods.snapshots.read_blob(snapshot.manifest_ref),
                                      snapshot.manifest_ref.media_type, 'method.yaml')
            policy = manifest.get('metadata', {}).get('work_source')
        except Exception as exc:
            if isinstance(exc, ApplicationError):
                raise
            raise ApplicationError('WORK_REVIEW_BINDING_UNAVAILABLE') from None
        if (type(policy) is not dict or policy.get('contract_version') != 'ordessa.persisted-work-source/1'
                or set(policy) != {'contract_version','input_document_slot','input_document_type','waits'}
                or type(policy.get('waits')) is not dict):
            raise ApplicationError('WORK_REVIEW_BINDING_UNAVAILABLE')
        return policy

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
        policy = self._policy(snapshot)
        slot_name = policy['input_document_slot']
        slots = self._slots(row)
        try:
            slot_ref = decode_artifact_ref(slots[slot_name])
        except (KeyError, ReferenceError, TypeError, ValueError):
            raise ApplicationError('WORK_REVIEW_INPUT_UNAVAILABLE') from None
        if slot_ref != input_ref:
            raise ApplicationError('WORK_REVIEW_SELECTOR_STALE')
        revision = uow.engineering.resolve_revision(input_ref)
        from ....application.orchestration.method_content import document_type_for_payload
        if (type(revision.payload) is not MethodPayload
                or document_type_for_payload(snapshot, revision.payload) != policy['input_document_type']):
            raise ApplicationError('WORK_REVIEW_INPUT_UNAVAILABLE')
        value = revision.payload.content.value
        if (type(value) is not dict
                or set(value) != {'document_type','schema_version','run_id','proposal_ref','events'}
                or value['document_type'] != policy['input_document_type']
                or value['schema_version'] != 1 or value['run_id'] != row['run_id']
                or type(value['events']) is not dict):
            raise ApplicationError('WORK_REVIEW_INPUT_INVALID')
        try:
            input_proposal = decode_proposal_ref(value['proposal_ref'])
        except (TypeError, ValueError, ReferenceError):
            raise ApplicationError('WORK_REVIEW_INPUT_INVALID') from None
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

    def _phases(self, context, snapshot, proposal, selector, slots, uow):
        # There is no frozen phase-to-subject mapping in the currently selected
        # method declaration. A Work slot by itself cannot supply one.
        raise ApplicationError('WORK_REVIEW_TARGET_POLICY_UNAVAILABLE')

    def _binding(self, context, snapshot, row, selector, plan):
        if (type(selector) is not WorkReviewSelector
                or (plan is not None and type(plan) is not ReviewPlan)
                or selector.scope != context.scope or selector.scope != self.scope
                or selector.run_id != row['run_id'] or self._method_ref_from_row(context,row) != self._method_ref_from_snapshot(snapshot)
                or (plan is not None and (selector.phase_key != plan.requirement.phase_key
                    or selector.method_ref != plan.requirement.method_ref))):
            raise ApplicationError('WORK_REVIEW_SELECTOR_INVALID')
        raise ApplicationError('WORK_REVIEW_TARGET_POLICY_UNAVAILABLE')

    @contextmanager
    def _resolve_live(self, context, plan, selector):
        row=self._run_row(context,selector.run_id)
        with self._snapshot(context,selector.method_ref) as snapshot:
            bindings,proposal,phases,adapter,policy,slots=self._binding(context,snapshot,row,selector,plan)
            yield snapshot,bindings,proposal,phases,adapter,policy,slots,row

    def resolve_bindings(self, context, plan, *, work_selector=None):
        if work_selector is None:
            raise ApplicationError('WORK_REVIEW_SELECTOR_REQUIRED')
        with self._resolve_live(context,plan,work_selector) as (_,binding,proposal,phases,adapter,_,_,_):
            if type(work_selector.subject_ref) is SubmissionRef:
                self._validate_submission_plan(context,plan,proposal,phases,binding)
            else:
                self._validate_proposal_plan(context,plan,proposal,phases,binding)
            return binding

    def resolve_phase_bindings_for_work(self, context, plan, selector):
        with self._resolve_live(context,plan,selector) as (_,_,_,phases,_,_,_,_):
            if type(selector.subject_ref) is SubmissionRef:
                return tuple(p for p in phases if p.review_purpose=='acceptance')
            return tuple(p for p in phases if p.review_purpose!='acceptance')

    def resolve_proposal_for_work(self, context, plan, selector):
        raise ApplicationError('WORK_REVIEW_TARGET_POLICY_UNAVAILABLE')

    def review_selection(self, context, *, run_id, review_id, subject_ref):
        """Build a current selector/plan pair from an explicitly named subject.

        The selected ref must already be present in the original Work slots and
        is re-resolved by the same-library owner before the caller can use it.
        """
        from ....domain.common.models.values import validate_id
        from ....domain.reviews.models import ReviewPlan
        from ....domain.artifacts.models import ArtifactRevision
        try:
            validate_id(review_id)
        except ReferenceError:
            raise ApplicationError('INVALID_INPUT') from None
        raise ApplicationError('WORK_REVIEW_TARGET_POLICY_UNAVAILABLE')

    def _validate_proposal_plan(self, context, plan, proposal, phases, binding):
        with self.factory.begin(context.scope,'read') as uow:
            budget=uow.proposals.validated_budget()
            roots=tuple(m.proposed_ref for m in proposal.mutations)+tuple(m.base_ref for m in proposal.mutations if m.base_ref is not None)+tuple(c.owner_revision_ref for c in proposal.claim_refs)
            revisions=uow.proposals.resolve_revision_graph(roots,budget)
            artifacts=tuple(uow.engineering.get_artifact(m.artifact_id) for m in proposal.mutations)
        with self._snapshot(context, plan.requirement.method_ref) as snapshot:
            expected=self.bridge.proposal_review_requirements(snapshot,phases,
                proposal=proposal,artifacts=artifacts,revisions=revisions)
        matches=tuple(r for r in expected if r.phase_key==binding.phase_key)
        if len(matches)!=1 or matches[0]!=plan.requirement:
            raise ApplicationError('METHOD_REVIEW_PLAN_CHANGED')

    def _validate_submission_plan(self, context, plan, proposal, phases, binding):
        from ....application.usecases.changes.acceptance_closure import resolve_submission_acceptance
        with self.factory.begin(context.scope,'read') as uow:
            submission_ref=binding.targets.targets[0].ref if binding.targets.targets else None
            # The exact SubmissionRef is supplied by the selector-backed phase.
            selected=next((p.submission_ref for p in phases if p.phase_key==binding.phase_key),None)
            if selected is None:
                raise ApplicationError('WORK_REVIEW_SUBJECT_MISMATCH')
            closure=resolve_submission_acceptance(uow,selected)
        with self._snapshot(context, plan.requirement.method_ref) as snapshot:
            expected=self.bridge.submission_review_requirements(snapshot,phases,
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
            bindings,proposal,phases,adapter,policy,slots=self._binding(
                context,snapshot,row,selector,plan)
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
        with self._resolve_historical(context,plan,selector,row) as (_,_,proposal,_,_,_,_,_):
            return proposal.ref

    def resolve_plan_bindings(self, context, plan):
        selector,row=self._historical_row(context,plan)
        with self._resolve_historical(context,plan,selector,row) as (_,binding,_,_,_,_,_,_):
            return binding

    def material_inputs_for_plan(self, context, plan):
        selector,row=self._historical_row(context,plan)
        with self._resolve_historical(context,plan,selector,row) as (_,binding,_,_,_,_,_,_):
            pass
        with self.factory.begin(context.scope,'read') as uow:
            return tuple((name,uow.engineering.resolve_revision(ref))
                for name,ref in self._historical_material_slots(context,selector,row,binding))

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
            if (input_ref!=selector.input_ref
                    or not any(v==asdict(selector.subject_ref) for v in slots.values())):
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
                if (type(node).__name__ != 'WaitNode' or completed is None
                        or completed.next != node.id or type(wait_decl) is not dict
                        or wait_decl.get('family')!='review_gate'
                        or wait_decl.get('phase_key')!=selector.phase_key):
                    raise ApplicationError('WORK_REVIEW_STALE')
        if request.review_id != plan.review_id:
            raise ApplicationError('REVIEW_REQUEST_CHANGED')

    def resolve_intent_bindings(self, context, method_ref, proposal_ref):
        """Bind only Proposal phases for the explicit Work start selection."""
        raise ApplicationError('WORK_REVIEW_TARGET_POLICY_UNAVAILABLE')

    def resolve_review_submission(self, context, method_ref, phase_key):
        raise ApplicationError('WORK_REVIEW_PLAN_REQUIRED')

    def resolve_review_proposal(self, context, method_ref, phase_key):
        raise ApplicationError('WORK_REVIEW_PLAN_REQUIRED')

    def resolve_submission_bindings(self, context, method_ref, submission_ref):
        raise ApplicationError('WORK_REVIEW_PLAN_REQUIRED')


__all__=['SQLiteWorkReviewBindings']
