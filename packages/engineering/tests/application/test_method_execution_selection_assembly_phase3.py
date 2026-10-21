"""Stable public composition over original owners; external Unit is controlled."""
import asyncio
import pytest
from ordessa_decision import DecisionAnswer
from ordessa_engineering.adapters.execution_profiles import ProfileTaskInput
from ordessa_engineering.adapters.profile_method import build_method_execution_selection
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_units.api import UnitManager
from test_method_profile_policy_phase2 import frozen_policy
from test_native_profile_selection_phase2 import _profile_owner, _content
from test_method_control_admission import context


def test_stable_builder_selects_and_creates_with_original_fixed_ref(frozen_policy, tmp_path):
    _, method_ref, methods, _ = frozen_policy
    with _profile_owner(tmp_path) as (profiles, descriptor, _policy):
        profile = profiles.create(profile_id='phase3-profile', name='Controlled profile',
            content=_content(descriptor, 'actual-fixed-revision'),
            request=profiles.request_key('create-profile'))
        exact = profile.current_revision
        class ControlledAssembly:
            def __init__(self): self.calls = []
            def create(self, spec, authorization):
                self.calls.append((spec, authorization))
                return self
        assembly = ControlledAssembly()
        selection = build_method_execution_selection(methods, profiles,
            method_ref=method_ref, allowed_revisions=(exact,),
            unit_manager=UnitManager(assembly), agent_id='agent-a',
            environment_reference={'environmentNamespace': profiles.environment_namespace})
        admitted = context('phase3-selection')
        native_policy = selection.policy_ref(admitted)
        assert native_policy.content_digest == 'sha256:' + method_ref.snapshot_digest.hex
        class ControlledGateway:
            async def decide(self, question):
                assert question.policy_ref == native_policy
                return DecisionAnswer(question.question_id, 'choice', next(iter(question.options)),
                                      {'selection_status': 'unique'})
        ref, answer = asyncio.run(selection.select(admitted,
            ProfileTaskInput('task-a', '1', 'Implement this fixed task'),
            gateway=ControlledGateway(), request_id='phase3-select-request'))
        assert ref is exact and answer.provider_receipt['selection_status'] == 'unique'
        authorization = object()  # External permission is deliberately controlled.
        assert selection.create(admitted, ref, authorization) is assembly
        assert assembly.calls[0][0].profile_revision is exact
        assert assembly.calls[0][1] is authorization
        profiles.archive(exact.profile_id, expected_version=1,
            request=profiles.request_key('archive-before-create'))
        with pytest.raises(EngineeringError, match='candidate_set_unavailable'):
            selection.create(admitted, ref, authorization)
        assert len(assembly.calls) == 1


def test_stable_builder_refuses_nonoriginal_method_authority():
    with pytest.raises(ApplicationError, match='PROFILE_METHOD_AUTHORITY_UNAVAILABLE'):
        build_method_execution_selection(object(), object(), method_ref=object(),
            allowed_revisions=(), unit_manager=object(), agent_id='agent-a',
            environment_reference={})
