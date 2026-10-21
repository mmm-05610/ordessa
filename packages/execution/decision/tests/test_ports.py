"""Single-use permit and call context (review items: replay/expiry/mismatch)."""
import time

import pytest

from ordessa_decision import CallPermit, DecisionError, ModelCallContext


def context(deadline=None):
    deadline = time.monotonic() + 10 if deadline is None else deadline
    permit = CallPermit("run", "qdigest", "sdigest", deadline)
    return ModelCallContext("run", "call", 1, "qdigest", "sdigest", deadline, permit)


class FakeQuestion:
    question_digest = "qdigest"


def test_permit_claims_once_and_refuses_replay_or_mismatch():
    value = context()
    value.claim(FakeQuestion(), "sdigest")
    with pytest.raises(DecisionError) as refused:
        value.claim(FakeQuestion(), "sdigest")
    assert refused.value.code == "permit_refused"
    with pytest.raises(DecisionError):
        context().claim(FakeQuestion(), "other")
    with pytest.raises(DecisionError):
        context(deadline=time.monotonic() - 1).claim(FakeQuestion(), "sdigest")


def test_attempt_no_is_positive_and_never_a_retry_token():
    with pytest.raises(DecisionError):
        ModelCallContext("run", "call", 0, "q", "s", time.monotonic() + 1,
                         CallPermit("run", "qdigest", "s", time.monotonic() + 1))
    second = ModelCallContext("run", "call-2", 2, "q", "s", time.monotonic() + 1,
                              CallPermit("run", "qdigest", "s", time.monotonic() + 1))
    second.claim(FakeQuestion(), "s")
