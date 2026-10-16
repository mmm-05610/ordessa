"""Method-bounded selection of an original native execution Profile revision.

The frozen method supplies the finite question and decline option. Original
ports supply allowed revisions, a Decision answer, and (optionally) Unit
creation. This module owns no execution authority or durable selection state.
"""
from collections.abc import Mapping

from ..contracts.errors import ApplicationError

_POLICY_KEYS = frozenset({
    "schema_version",
    "question_id",
    "question_text",
    "candidate_limit",
    "decline_option_id",
    "decline_option_text",
})


def _fail(code):
    raise ApplicationError(code)


def _text(value):
    if type(value) is not str or not value:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def validate_profile_selection_policy(policy):
    """Validate the exact closed frozen-method profile-selection policy."""
    if (not isinstance(policy, Mapping)
            or set(policy) != _POLICY_KEYS
            or type(policy.get("schema_version")) is not int
            or policy["schema_version"] != 1
            or not _text(policy.get("question_id"))
            or not _text(policy.get("question_text"))
            or type(policy.get("candidate_limit")) is not int
            or not 1 <= policy["candidate_limit"] <= 64
            or not _text(policy.get("decline_option_id"))
            or not _text(policy.get("decline_option_text"))):
        _fail("PROFILE_SELECTION_POLICY_INVALID")
    return dict(policy)


def _candidate_rows(source, limit, decline_id):
    candidate_set = source.candidates(max_candidates=limit)
    if not isinstance(candidate_set, Mapping) or not candidate_set or len(candidate_set) > limit:
        _fail("PROFILE_SELECTION_CANDIDATES_UNAVAILABLE")

    rows = []
    for option_id, pair in candidate_set.items():
        if (not _text(option_id) or option_id == decline_id
                or type(pair) is not tuple or len(pair) != 2
                or pair[0] is None or not _text(pair[1])):
            _fail("PROFILE_SELECTION_CANDIDATES_INVALID")
        profile_ref, description = pair
        for prior_id, prior_ref, _ in rows:
            if prior_id == option_id:
                _fail("PROFILE_SELECTION_CANDIDATES_INVALID")
            try:
                duplicate_ref = prior_ref == profile_ref
            except Exception:
                _fail("PROFILE_SELECTION_CANDIDATES_INVALID")
            if type(duplicate_ref) is not bool or duplicate_ref:
                _fail("PROFILE_SELECTION_CANDIDATES_INVALID")
        rows.append((option_id, profile_ref, description))

    # Stable option order makes the exact method question reproducible. The
    # explicit decline option remains present even for a single permitted ref.
    rows.sort(key=lambda row: row[0])
    options = {option_id: description for option_id, _, description in rows}
    return rows, options


def _answer_fields(answer, question_id):
    # Avoid importing Execution DTOs here: the choice port owns that public
    # boundary and returns its original immutable DecisionAnswer unchanged.
    if (answer is None
            or getattr(answer, "question_id", None) != question_id
            or getattr(answer, "kind", None) != "choice"):
        _fail("PROFILE_SELECTION_ANSWER_INVALID")
    receipt = getattr(answer, "provider_receipt", None)
    if not isinstance(receipt, Mapping):
        _fail("PROFILE_SELECTION_ANSWER_INVALID")
    status = receipt.get("selection_status")
    if status == "tie":
        _fail("PROFILE_SELECTION_NOT_UNIQUE")
    if status == "missing":
        _fail("PROFILE_SELECTION_MISSING")
    if status != "unique":
        _fail("PROFILE_SELECTION_ANSWER_INVALID")
    value = getattr(answer, "value", None)
    if type(value) is not str:
        _fail("PROFILE_SELECTION_ANSWER_INVALID")
    return value


async def select_method_profile(task, *, policy, candidates, choice, request_id):
    """Return one revalidated original Profile ref and its native Decision answer.

    ``policy`` is the exact frozen method ``metadata.agent_profile_selection``
    mapping. Errors and cancellation from the original choice port propagate;
    no retries, synthetic answers, authorization, or fallback Profile are made.
    """
    policy = validate_profile_selection_policy(policy)
    if not _text(request_id):
        _fail("PROFILE_SELECTION_REQUEST_INVALID")
    if candidates is None or not callable(getattr(candidates, "candidates", None)) or not callable(
            getattr(candidates, "validate", None)):
        _fail("PROFILE_SELECTION_SOURCE_UNAVAILABLE")
    if not callable(getattr(choice, "choose", None)):
        _fail("PROFILE_SELECTION_CHOICE_UNAVAILABLE")

    rows, options = _candidate_rows(
        candidates, policy["candidate_limit"], policy["decline_option_id"])
    options[policy["decline_option_id"]] = policy["decline_option_text"]
    answer = await choice.choose(
        task,
        request_id=request_id,
        question_id=policy["question_id"],
        question_text=policy["question_text"],
        options=options,
    )
    selected_option = _answer_fields(answer, policy["question_id"])
    if selected_option == policy["decline_option_id"]:
        _fail("PROFILE_SELECTION_DECLINED")
    selected = [profile_ref for option_id, profile_ref, _ in rows
                if option_id == selected_option]
    if len(selected) != 1:
        _fail("PROFILE_SELECTION_OPTION_UNAVAILABLE")
    profile_ref = selected[0]
    validated = candidates.validate(profile_ref)
    if validated is not profile_ref:
        _fail("PROFILE_SELECTION_REVISION_CHANGED")
    return profile_ref, answer


async def select_and_create_method_unit(
    task, *, policy, candidates, choice, request_id, units, authorization
):
    """Select, revalidate the exact native ref again, then delegate Unit create."""
    profile_ref, answer = await select_method_profile(
        task, policy=policy, candidates=candidates, choice=choice,
        request_id=request_id)
    if units is None or not callable(getattr(units, "create", None)):
        _fail("PROFILE_SELECTION_UNIT_UNAVAILABLE")
    validated = candidates.validate(profile_ref)
    if validated is not profile_ref:
        _fail("PROFILE_SELECTION_REVISION_CHANGED")
    unit = units.create(profile_ref, authorization)
    return unit, answer


__all__ = ["validate_profile_selection_policy", "select_method_profile",
           "select_and_create_method_unit"]
