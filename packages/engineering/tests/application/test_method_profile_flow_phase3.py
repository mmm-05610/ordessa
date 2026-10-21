"""Original native gateway/evidence through the public Engineering flow adapter.

Stored Profile/method owners are real; provider/access/management and Unit
assembly are controlled. No model, secret, network or native process is used.
"""
import asyncio

import pytest
from dataclasses import replace
from ordessa_decision import DecisionError, DecisionAnswer, FilesystemEvidenceStore
from ordessa_decision.evidence import EvidenceScope
from ordessa_engineering.adapters.decision.source_job import SourceReviewJobServices
from ordessa_engineering.adapters.execution_profiles import ProfileTaskInput
from ordessa_engineering.adapters.profile_flow import run_method_profile_selection, ProfileSelectionServices
from ordessa_engineering.adapters.profile_method import build_method_execution_selection
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_units.api import UnitManager

from test_method_control_admission import context
from test_method_profile_policy_phase2 import frozen_policy
from test_native_profile_selection_phase2 import _profile_owner, _content


@pytest.mark.parametrize('case', ('unique', 'tie', 'cancel', 'wrong-policy', 'missing-provider'))
def test_public_method_profile_flow_preserves_native_results_and_refuses_without_retry(
        frozen_policy, tmp_path, case):
    _, method_ref, methods, _ = frozen_policy
    with _profile_owner(tmp_path) as (profiles, descriptor, _):
        profile = profiles.create(profile_id='flow-profile', name='Controlled executor',
            content=_content(descriptor, 'flow-fixed'), request=profiles.request_key('create-flow'))
        exact = profile.current_revision
        unit_calls = []
        class ControlledUnitAssembly:
            def create(self, spec, authorization):
                unit_calls.append((spec, authorization))
                return spec
        selection = build_method_execution_selection(methods, profiles,
            method_ref=method_ref, allowed_revisions=(exact,),
            unit_manager=UnitManager(ControlledUnitAssembly()), agent_id='executor',
            environment_reference={'environmentNamespace': profiles.environment_namespace})
        admitted = context('native-profile-flow')
        policy = selection.policy_ref(admitted)
        answers = []
        class Provider:
            settings_digest = 'sha256:' + 'b'*64
            binding_ref = 'test.controlled-profile-flow'
            calls = 0
            def receipt(self, question, tie):
                options = tuple(question.options)
                return {'probabilities': {key: (1 / len(options) if tie else float(key == options[0])) for key in options},
                    'resolved_model': 'controlled', 'requested_model': 'controlled',
                    'protocol_validation_version': 'controlled/1', 'question_digest': question.question_digest,
                    'provider_settings_digest': self.settings_digest}
            async def decide(self, question, invocation):
                self.calls += 1
                invocation.claim(question, self.settings_digest)
                if case == 'cancel':
                    raise asyncio.CancelledError()
                if case == 'tie':
                    answer = DecisionAnswer(question.question_id, 'choice', None,
                        {'selection_status': 'tie', 'tied_option_ids': tuple(question.options), **self.receipt(question, True)})
                else:
                    answer = DecisionAnswer(question.question_id, 'choice', next(iter(question.options)),
                        {'selection_status': 'unique', **self.receipt(question, False)}, {'status': 'reported'})
                answers.append(answer)
                return answer
        provider = Provider()
        owner = FilesystemEvidenceStore(tmp_path / 'profile-decision-evidence')
        scope = EvidenceScope('principal', 'controlled-profile-flow')
        refs = (policy,)
        if case == 'wrong-policy':
            from ordessa_decision import PolicyRef
            refs = (PolicyRef('different', '1', 'sha256:'+'c'*64),)
        jobs = SourceReviewJobServices(provider, owner, lambda ctx: ctx, lambda *_: scope,
            lambda ctx, request_id: replace(ctx, request_id=request_id))
        services = None if case == 'missing-provider' else ProfileSelectionServices(jobs, refs)
        operation = run_method_profile_selection(selection, admitted,
            ProfileTaskInput('implement', '1', 'Implement the exact admitted task'),
            services=services, request_id='flow-request', review_ref='controlled-reviewed-flow/1',
            limits={'max_model_calls':1, 'max_steps':2, 'max_value_bytes':65536,
                    'timeout_seconds':5.0})
        if case == 'cancel':
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(operation)
            assert provider.calls == 1 and unit_calls == []
            return
        if case in ('wrong-policy', 'missing-provider'):
            error = DecisionError if case == 'wrong-policy' else ApplicationError
            code = 'flow_policy_mismatch' if case == 'wrong-policy' else 'PROFILE_SELECTION_SERVICES_UNAVAILABLE'
            with pytest.raises(error, match=code):
                asyncio.run(operation)
            assert provider.calls == 0 and unit_calls == []
            return
        selected, answer, result = asyncio.run(operation)
        assert provider.calls == 1 and unit_calls == []
        assert result.decision.status == 'completed'
        assert result.decision.operation_ref.startswith('decision-run/')
        if case == 'tie':
            assert result.status == 'failed' and selected is None and answer is None
        else:
            assert result.status == 'completed' and selected is exact and answer.answer_digest == answers[0].answer_digest
            assert result.disposition == 'clarify'
            authorization = object()  # Explicitly external controlled Unit permission.
            unit = selection.create(admitted, selected, authorization)
            assert unit.profile_revision is exact
            assert unit_calls[0][1] is authorization
