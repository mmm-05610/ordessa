"""Controlled tests for method-bounded selection over original owner ports."""
import asyncio
from dataclasses import dataclass

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.profile_selection import (
    select_and_create_method_unit,
    select_method_profile,
    validate_profile_selection_policy,
)


@dataclass(frozen=True)
class Ref:
    profile_id: str
    revision: str


@dataclass(frozen=True)
class Answer:
    question_id: str
    kind: str
    value: object
    provider_receipt: dict


POLICY = {
    "schema_version": 1,
    "question_id": "choose_profile",
    "question_text": "Choose an allowed execution profile, or decline.",
    "candidate_limit": 4,
    "decline_option_id": "decline",
    "decline_option_text": "Do not create a Unit.",
}


class Source:
    def __init__(self, rows, *, validate_result=None, candidates_error=None):
        self.rows = rows
        self.validate_result = validate_result
        self.candidates_error = candidates_error
        self.candidates_calls = []
        self.validate_calls = []

    def candidates(self, *, max_candidates):
        self.candidates_calls.append(max_candidates)
        if self.candidates_error:
            raise self.candidates_error
        return self.rows

    def validate(self, profile_ref):
        self.validate_calls.append(profile_ref)
        if self.validate_result is not None:
            return self.validate_result
        if not any(profile_ref is ref for ref, _ in self.rows.values()):
            raise ApplicationError("PROFILE_REVISION_NOT_ALLOWED")
        return profile_ref


class Choice:
    def __init__(self, answer=None, *, error=None):
        self.answer = answer
        self.error = error
        self.calls = []

    async def choose(self, task, **kwargs):
        self.calls.append((task, kwargs))
        if self.error:
            raise self.error
        return self.answer


class Units:
    def __init__(self, unit="native-unit"):
        self.unit = unit
        self.calls = []

    def create(self, profile_ref, authorization):
        self.calls.append((profile_ref, authorization))
        return self.unit


def answer(value, *, status="unique", question_id="choose_profile", kind="choice"):
    return Answer(question_id, kind, value, {"selection_status": status})


def source(*, validate_result=None):
    first = Ref("profile-a", "rev-7")
    second = Ref("profile-b", "rev-3")
    return Source({
        "profile_a": (first, "Exact Profile A revision rev-7"),
        "profile_b": (second, "Exact Profile B revision rev-3"),
    }, validate_result=validate_result), first, second


def test_selection_uses_complete_bounded_set_decline_option_and_exact_ref():
    task = object()
    src, first, _ = source()
    native_answer = answer("profile_a")
    choice = Choice(native_answer)

    selected, returned_answer = asyncio.run(select_method_profile(
        task, policy=POLICY, candidates=src, choice=choice, request_id="request-1"))

    assert selected is first
    assert returned_answer is native_answer
    assert src.candidates_calls == [4]
    assert src.validate_calls == [first]
    observed_task, kwargs = choice.calls[0]
    assert observed_task is task
    assert kwargs == {
        "request_id": "request-1",
        "question_id": "choose_profile",
        "question_text": POLICY["question_text"],
        "options": {
            "profile_a": "Exact Profile A revision rev-7",
            "profile_b": "Exact Profile B revision rev-3",
            "decline": POLICY["decline_option_text"],
        },
    }


def test_singleton_candidate_still_has_decline_and_unit_revalidates_before_create():
    only = Ref("profile-a", "rev-7")
    src = Source({"profile_a": (only, "Exact revision")})
    choice = Choice(answer("profile_a"))
    units = Units()
    authorization = object()

    unit, native_answer = asyncio.run(select_and_create_method_unit(
        object(), policy=POLICY, candidates=src, choice=choice,
        request_id="request-2", units=units, authorization=authorization))

    options = choice.calls[0][1]["options"]
    assert set(options) == {"profile_a", "decline"}
    assert unit == "native-unit"
    assert native_answer is choice.answer
    assert src.validate_calls == [only, only]
    assert units.calls == [(only, authorization)]


def test_ref_revoked_on_second_validation_prevents_unit_creation():
    original = Ref("profile-a", "rev-7")

    class RevokeOnSecondValidation(Source):
        def validate(self, profile_ref):
            self.validate_calls.append(profile_ref)
            if len(self.validate_calls) == 1:
                return profile_ref
            raise ApplicationError("PROFILE_REVISION_REVOKED")

    src = RevokeOnSecondValidation({"profile_a": (original, "Exact revision")})
    units = Units()

    with pytest.raises(ApplicationError) as error:
        asyncio.run(select_and_create_method_unit(
            object(), policy=POLICY, candidates=src, choice=Choice(answer("profile_a")),
            request_id="request-second-revoke", units=units, authorization=object()))

    assert error.value.code == "PROFILE_REVISION_REVOKED"
    assert src.validate_calls == [original, original]
    assert units.calls == []


@pytest.mark.parametrize(("native_answer", "code"), [
    (answer(None, status="tie"), "PROFILE_SELECTION_NOT_UNIQUE"),
    (answer(None, status="missing"), "PROFILE_SELECTION_MISSING"),
    (answer("foreign-option"), "PROFILE_SELECTION_OPTION_UNAVAILABLE"),
    (answer("profile_a", question_id="another_question"), "PROFILE_SELECTION_ANSWER_INVALID"),
    (answer("profile_a", kind="score"), "PROFILE_SELECTION_ANSWER_INVALID"),
])
def test_nonunique_missing_foreign_or_mismatched_answer_never_creates_unit(native_answer, code):
    src, _, _ = source()
    units = Units()

    with pytest.raises(ApplicationError) as error:
        asyncio.run(select_and_create_method_unit(
            object(), policy=POLICY, candidates=src, choice=Choice(native_answer),
            request_id="request-3", units=units, authorization=object()))

    assert error.value.code == code
    assert units.calls == []
    assert src.validate_calls == []


def test_decline_and_profile_revision_change_never_create_unit():
    src, _, _ = source()
    units = Units()
    with pytest.raises(ApplicationError, match="PROFILE_SELECTION_DECLINED"):
        asyncio.run(select_and_create_method_unit(
            object(), policy=POLICY, candidates=src, choice=Choice(answer("decline")),
            request_id="request-4", units=units, authorization=object()))
    assert units.calls == []
    assert src.validate_calls == []

    original = Ref("profile-a", "rev-7")
    substituted = Ref("profile-a", "rev-8")
    changed = Source({"profile_a": (original, "Exact revision")}, validate_result=substituted)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(select_and_create_method_unit(
            object(), policy=POLICY, candidates=changed, choice=Choice(answer("profile_a")),
            request_id="request-5", units=units, authorization=object()))
    assert error.value.code == "PROFILE_SELECTION_REVISION_CHANGED"
    assert units.calls == []
    assert changed.validate_calls == [original]


@pytest.mark.parametrize("mutation", [
    {**POLICY, "unexpected": True},
    {**POLICY, "candidate_limit": True},
    {**POLICY, "candidate_limit": 0},
])
def test_closed_method_policy_refuses_invalid_or_colliding_configuration(mutation):
    src, _, _ = source()
    choice = Choice(answer("profile_a"))
    with pytest.raises(ApplicationError):
        asyncio.run(select_method_profile(
            object(), policy=mutation, candidates=src, choice=choice,
            request_id="request-6"))
    assert src.candidates_calls == []
    assert choice.calls == []


def test_decline_option_collision_is_detected_after_complete_candidate_read():
    src, _, _ = source()
    choice = Choice(answer("profile_a"))
    units = Units()
    policy = {**POLICY, "decline_option_id": "profile_a"}

    with pytest.raises(ApplicationError) as error:
        asyncio.run(select_and_create_method_unit(
            object(), policy=policy, candidates=src, choice=choice,
            request_id="request-collision", units=units, authorization=object()))

    assert error.value.code == "PROFILE_SELECTION_CANDIDATES_INVALID"
    assert src.candidates_calls == [4]
    assert choice.calls == []
    assert units.calls == []


def test_public_policy_validator_returns_closed_plain_mapping():
    from types import MappingProxyType

    validated = validate_profile_selection_policy(MappingProxyType(POLICY))
    assert type(validated) is dict
    assert validated == POLICY


def test_over_limit_set_is_refused_without_truncation_and_port_failure_propagates():
    many = {f"p{i}": (Ref(f"p{i}", "r1"), f"revision {i}") for i in range(5)}
    src = Source(many)
    choice = Choice(answer("p0"))
    with pytest.raises(ApplicationError) as error:
        asyncio.run(select_method_profile(
            object(), policy=POLICY, candidates=src, choice=choice,
            request_id="request-7"))
    assert error.value.code == "PROFILE_SELECTION_CANDIDATES_UNAVAILABLE"
    assert choice.calls == []

    unavailable = RuntimeError("source unavailable")
    src = Source({}, candidates_error=unavailable)
    with pytest.raises(RuntimeError) as error:
        asyncio.run(select_and_create_method_unit(
            object(), policy=POLICY, candidates=src, choice=choice,
            request_id="request-8", units=Units(), authorization=object()))
    assert error.value is unavailable


def test_choice_failure_or_cancellation_propagates_without_unit_create():
    src, _, _ = source()
    units = Units()
    failure = RuntimeError("choice unavailable")
    with pytest.raises(RuntimeError) as error:
        asyncio.run(select_and_create_method_unit(
            object(), policy=POLICY, candidates=src,
            choice=Choice(error=failure), request_id="request-9",
            units=units, authorization=object()))
    assert error.value is failure
    assert units.calls == []

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(select_and_create_method_unit(
            object(), policy=POLICY, candidates=src,
            choice=Choice(error=asyncio.CancelledError()), request_id="request-10",
            units=units, authorization=object()))
    assert units.calls == []


def test_revoked_selected_revision_refuses_before_unit_create():
    original = Ref("profile-a", "rev-7")

    class RevokedSource(Source):
        def validate(self, profile_ref):
            self.validate_calls.append(profile_ref)
            raise ApplicationError("PROFILE_REVISION_REVOKED")

    src = RevokedSource({"profile_a": (original, "Exact revision")})
    units = Units()
    with pytest.raises(ApplicationError) as error:
        asyncio.run(select_and_create_method_unit(
            object(), policy=POLICY, candidates=src, choice=Choice(answer("profile_a")),
            request_id="request-revoked", units=units, authorization=object()))
    assert error.value.code == "PROFILE_REVISION_REVOKED"
    assert src.validate_calls == [original]
    assert units.calls == []


def test_duplicate_native_refs_are_ambiguous_and_refuse():
    duplicate = Ref("same", "rev-1")
    src = Source({
        "option_a": (duplicate, "same revision"),
        "option_b": (duplicate, "same revision again"),
    })
    choice = Choice(answer("option_a"))
    with pytest.raises(ApplicationError) as error:
        asyncio.run(select_method_profile(
            object(), policy=POLICY, candidates=src, choice=choice,
            request_id="request-11"))
    assert error.value.code == "PROFILE_SELECTION_CANDIDATES_INVALID"
    assert choice.calls == []
