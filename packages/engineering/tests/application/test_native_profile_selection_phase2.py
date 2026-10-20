"""Controlled checks over the original Execution public APIs.

The Profile owner below is a real in-process SQLite ProfileService with a
synthetic all-allow policy. The Decision gateway and Unit assembly are
controlled test doubles; they do not represent production authority or a
human Grant.
"""
from contextlib import contextmanager
from threading import RLock

import pytest

from decision_runtime import DecisionAnswer, PolicyRef
from ordessa_engineering.adapters.execution_profiles import ProfileTaskInput
from ordessa_engineering.adapters.execution_profiles import (
    NativeProfileChoice,
    NativeProfileSelectionSource,
    NativeProfileUnitCreator,
)
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_execution_agents.profiles import (
    ProfileAccessRefused,
    ProfileNotFound,
    ProfileRevisionConflict,
    ProfileRevisionRef,
    ProfileService,
)
from ordessa_units.api import UnitManager


class _Policy:
    def __init__(self):
        self.denied_profiles = set()

    def admit_object_access(self, *_args):
        target = _args[1] if len(_args) > 1 else ""
        return not any(target.endswith(":" + profile_id) for profile_id in self.denied_profiles)

    def admit_invoke(self, *_args):
        return True


@contextmanager
def _profile_owner(tmp_path):
    from types import SimpleNamespace
    from apps.cli.tests.integration.profile_test_owner import profile_owner
    namespace = "phase2-profile-selection"
    policy = _Policy()
    pin = {"environmentNamespace": namespace, "definitionId": "synthetic", "revision": "1"}
    # Explicit independent Profile store/admission/validator fixture. No Unit
    # constructor, registry or native launch is borrowed by this owner.
    owner = profile_owner(tmp_path / 'profiles.sqlite', namespace,
        'synthetic-test-principal', policy, pin)
    try:
        yield owner.service, SimpleNamespace(definition_ref=pin), policy
    finally:
        owner.close()


def _content(descriptor, label):
    return {
        "schemaVersion": "1",
        "harnessDefinitionRef": dict(descriptor.definition_ref),
        "declarations": [],
        "metadata": {"fixture_label": label},
    }


def test_native_profile_source_keeps_exact_revision_and_refuses_incomplete_sets(tmp_path):
    with _profile_owner(tmp_path) as (profiles, descriptor, _policy):
        first = profiles.create(
            profile_id="profile-a", name="Synthetic A", content=_content(descriptor, "first"),
            request=profiles.request_key("create-a"),
        )
        profiles.revise(
            "profile-a", content=_content(descriptor, "second"), expected_version=1,
            base_revision=first.current_revision, request=profiles.request_key("revise-a"),
        )
        source = NativeProfileSelectionSource(profiles, allowed_revisions=(first.current_revision,))

        candidates = source.candidates(max_candidates=1)
        option_id, (selected_ref, description) = next(iter(candidates.items()))
        assert selected_ref is first.current_revision
        assert option_id.startswith("profile-a@1:")
        assert '"fixture_label":"first"' in description
        assert source.validate(selected_ref) is selected_ref

        second = profiles.create(
            profile_id="profile-b", name="Synthetic B", content=_content(descriptor, "third"),
            request=profiles.request_key("create-b"),
        )
        over_limit = NativeProfileSelectionSource(
            profiles, allowed_revisions=(first.current_revision, second.current_revision)
        )
        with pytest.raises(EngineeringError, match="over_limit"):
            over_limit.candidates(max_candidates=1)
        profiles.archive(
            "profile-b", expected_version=1, request=profiles.request_key("archive-b")
        )
        archived = NativeProfileSelectionSource(
            profiles, allowed_revisions=(second.current_revision,)
        )
        with pytest.raises(EngineeringError, match="candidate_set_unavailable"):
            archived.candidates(max_candidates=1)
        with pytest.raises(EngineeringError, match="not_method_allowed"):
            source.validate(profiles.get("profile-a").current_revision)


def test_native_profile_source_rechecks_original_acl_and_exact_digest(tmp_path):
    with _profile_owner(tmp_path) as (profiles, descriptor, policy):
        created = profiles.create(
            profile_id="profile-acl", name="Synthetic ACL", content=_content(descriptor, "acl"),
            request=profiles.request_key("create-acl"),
        )
        source = NativeProfileSelectionSource(profiles, allowed_revisions=(created.current_revision,))
        policy.denied_profiles.add("profile-acl")
        with pytest.raises(ProfileAccessRefused):
            source.candidates(max_candidates=1)

    digest_dir = tmp_path / "digest"
    digest_dir.mkdir()
    with _profile_owner(digest_dir) as (profiles, descriptor, _policy):
        created = profiles.create(
            profile_id="profile-digest", name="Synthetic Digest", content=_content(descriptor, "digest"),
            request=profiles.request_key("create-digest"),
        )
        bad_ref = ProfileRevisionRef(
            created.current_revision.environment_namespace,
            created.current_revision.profile_id,
            created.current_revision.revision,
            "sha256:" + "f" * 64,
        )
        stale = NativeProfileSelectionSource(profiles, allowed_revisions=(bad_ref,))
        with pytest.raises(ProfileRevisionConflict):
            stale.candidates(max_candidates=1)

        foreign = ProfileRevisionRef(
            "foreign-environment", created.current_revision.profile_id,
            created.current_revision.revision, created.current_revision.digest,
        )
        with pytest.raises(EngineeringError, match="environment_mismatch"):
            NativeProfileSelectionSource(profiles, allowed_revisions=(foreign,))
        snapshot = ProfileRevisionRef(
            created.current_revision.environment_namespace,
            "snap-" + "1" * 48,
            1,
            "sha256:" + "1" * 64,
        )
        snapshot_source = NativeProfileSelectionSource(profiles, allowed_revisions=(snapshot,))
        with pytest.raises(ProfileNotFound):
            snapshot_source.candidates(max_candidates=1)


class _Gateway:
    def __init__(self, answer):
        self.answer = answer
        self.questions = []

    async def decide(self, question):
        self.questions.append(question)
        return self.answer


@pytest.mark.asyncio
async def test_native_profile_choice_calls_injected_gateway_once_and_preserves_answer():
    policy_ref = PolicyRef("method-policy", "7", "sha256:" + "c" * 64)
    task = ProfileTaskInput("task-1", "r3", "Choose a permitted execution profile")
    answer = DecisionAnswer(
        "method.profile", "choice", "profile-a@1:sha256:" + "d" * 64,
        {"selection_status": "unique", "fixture": "synthetic"}, {"status": "reported"},
    )
    gateway = _Gateway(answer)
    choice = NativeProfileChoice(gateway, policy_ref)

    returned = await choice.choose(
        task,
        request_id="phase2-case-1",
        question_id="method.profile",
        question_text="Select an allowed Profile revision or decline.",
        options={"profile-a@1:sha256:" + "d" * 64: "Exact test revision", "decline": "Decline"},
    )

    assert returned is answer
    assert len(gateway.questions) == 1
    question = gateway.questions[0]
    assert question.policy_ref is policy_ref
    assert question.bounded_state["task"]["task_id"] == task.task_id
    assert question.allowed_answer_ids == tuple(question.options)


def test_native_profile_unit_creator_uses_public_unit_manager_and_fixed_ref():
    class _Assembly:
        def __init__(self):
            self.calls = []
            self.result = object()

        def create(self, spec, authorization):
            self.calls.append((spec, authorization))
            return self.result

    assembly = _Assembly()
    manager = UnitManager(assembly)
    environment_reference = {"environmentNamespace": "env-a", "instanceId": "instance-a"}
    creator = NativeProfileUnitCreator(
        manager,
        agent_id="agent-7",
        environment_reference=environment_reference,
    )
    # Construct a native immutable ref; the controlled public manager only
    # records the UnitSpec and does not assert production authorization.
    from ordessa_execution_agents.profiles import ProfileRevisionRef

    ref = ProfileRevisionRef("env-a", "profile-a", 2, "sha256:" + "e" * 64)
    authorization = object()
    environment_reference["instanceId"] = "mutated-after-construction"
    result = creator.create(ref, authorization)

    assert result is assembly.result
    spec, actual_authorization = assembly.calls[0]
    assert spec.agent_id == "agent-7"
    assert spec.profile_revision is ref
    assert spec.environment_reference["instanceId"] == "instance-a"
    assert actual_authorization is authorization
