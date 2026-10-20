"""Same-case original SQLite method/Profile + native Decision gateway.

Provider, management permission and public Unit assembly are explicitly
controlled. No model, process, permission grant or default app is exercised.
"""
import asyncio

import pytest
from dataclasses import replace
from decision_runtime import DecisionAnswer, FilesystemEvidenceStore
from decision_runtime.evidence import EvidenceScope
from ordessa_engineering.adapters.decision.source_job import SourceReviewJobServices
from ordessa_engineering.adapters.execution_profiles import ProfileTaskInput
from ordessa_engineering.adapters.profile_flow import ProfileSelectionServices, run_method_profile_selection
from ordessa_engineering.adapters.profile_method import build_method_execution_selection
from ordessa_execution_agents.profiles import encode_revision_ref
from ordessa_units.api import UnitManager
from test_method_control_admission import context
from test_method_profile_policy_phase2 import frozen_policy
from test_native_profile_selection_phase2 import _profile_owner, _content


@pytest.mark.parametrize('case', ['unique', 'tie', 'archive', 'disable', 'cancel'])
def test_original_gateway_and_profile_owner_select_then_refuse_or_delegate_exact_unit(
        frozen_policy, tmp_path, case):
    _, method_ref, methods, management = frozen_policy
    with _profile_owner(tmp_path) as (profiles, descriptor, _policy):
        # This store is the original Profile owner; only policy is synthetic.
        created = profiles.create(profile_id='task-executor', name='Controlled executor',
            content=_content(descriptor, 'controlled-native'),
            request=profiles.request_key('create-task-executor'))
        exact = created.current_revision
        chosen = []
        created_units = []
        class SyntheticAssembly:
            def create(self, spec, authorization):
                created_units.append((spec, authorization))
                return object()
        selection = build_method_execution_selection(methods, profiles, method_ref=method_ref,
            allowed_revisions=(exact,), unit_manager=UnitManager(SyntheticAssembly()), agent_id='executor',
            environment_reference={'environmentNamespace': profiles.environment_namespace})
        admitted_context = context('profile-flow')
        policy_ref = selection.policy_ref(admitted_context)
        authorization = object()  # Explicitly no claim of real Unit/human authority.
        class ControlledProvider:
            binding_ref = 'test.controlled-profile-choice'
            settings_digest = 'sha256:' + 'c' * 64
            calls = 0
            def receipt(self, question, tie):
                options = tuple(question.options)
                return {'probabilities':{key:(1/len(options) if tie else float(key == options[0])) for key in options},
                    'question_digest':question.question_digest, 'provider_settings_digest':self.settings_digest,
                    'resolved_model':'controlled','requested_model':'controlled','protocol_validation_version':'controlled/1'}
            async def decide(self, question, model_context):
                self.calls += 1
                model_context.claim(question, self.settings_digest)
                if case == 'cancel':
                    raise asyncio.CancelledError()
                if case == 'archive':
                    profiles.archive(exact.profile_id, expected_version=1,
                        request=profiles.request_key('archive-during-choice'))
                if case == 'disable':
                    management.control(method_ref, context('disable-during-choice'),
                        expected_version=0, enabled=False, reason='Controlled method stop')
                options = tuple(question.options)
                if case == 'tie':
                    return DecisionAnswer(question.question_id, 'choice', None,
                        {'selection_status': 'tie', 'tied_option_ids': options, **self.receipt(question, True)})
                return DecisionAnswer(question.question_id, 'choice', options[0],
                    {'selection_status': 'unique', **self.receipt(question, False)}, {'status': 'reported'})
        provider = ControlledProvider()
        owner = FilesystemEvidenceStore(tmp_path/'profile-current-job')
        scope = EvidenceScope('principal','controlled-native-profile-flow')
        jobs = SourceReviewJobServices(provider, owner, lambda ctx:ctx, lambda *_:scope,
            lambda ctx, request_id:replace(ctx, request_id=request_id))
        operation = run_method_profile_selection(selection, admitted_context,
            ProfileTaskInput('task-a','r1','Implement the fixed specification',
                boundaries=('method-approved bounds',)),
            services=ProfileSelectionServices(jobs,(policy_ref,)), request_id='controlled-'+case,
            review_ref='controlled-native-profile-fixture/2',
            limits={'max_model_calls':1,'max_steps':2,'max_value_bytes':65536,'timeout_seconds':5.0})
        if case == 'cancel':
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(operation)
            assert chosen == [] and created_units == [] and provider.calls == 1
            return
        selected, answer, result = asyncio.run(operation)
        if selected is not None:
            unit = selection.create(admitted_context, selected, authorization)
            chosen.append((selected, answer, unit))
        captured = result.decision
        assert provider.calls == 1  # One original gateway call; no retry.
        if case == 'unique':
            assert result.status == 'completed'
            assert result.disposition == 'clarify'
            assert chosen[0][0] is exact
            spec, admitted = created_units[0]
            assert spec.profile_revision is exact and admitted is authorization
            assert captured.status == 'completed'
            assert answer.answer_digest == chosen[0][1].answer_digest
            assert captured.operation_ref.startswith('decision-run/')
        else:
            assert result.status == 'failed'
            assert result.disposition is None
            assert chosen == [] and created_units == []
