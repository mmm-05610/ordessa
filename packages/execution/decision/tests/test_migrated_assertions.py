"""Assertions rescued from the retired decision_runtime suite (same semantics)."""
import pytest

from decision_runtime import (
    DecisionError, DecisionQuestion, DecisionRunner, FilesystemEvidenceStore,
    RulesOutcome, canonical_bytes, decode_json, validate_job)


def test_canonical_bytes_are_sorted_compact_utf8_and_round_trip():
    # From contracts/test_canonical_vectors: canonical stability, not a rewrite.
    raw = canonical_bytes({"b": 1, "a": "文"})
    assert raw == '{"a":"文","b":1}'.encode("utf-8")
    assert decode_json(raw) == {"a": "文", "b": 1}
    assert canonical_bytes(decode_json(raw)) == raw


@pytest.mark.parametrize("raw", [b'{"a": 1}', b'{"b":1,"a":2}', b'{"a":NaN}'])
def test_noncanonical_or_nonfinite_bytes_are_refused(raw):
    # Evidence attacks keep rejecting uncanonical input instead of re-encoding.
    with pytest.raises(DecisionError):
        decode_json(raw)


def test_question_bounds_survive_as_contract_assertions():
    choice = {"kind": "choice", "question_text": "Pick",
              "bounded_state": {}, "options": {"a": "A", "b": "B"}}
    with pytest.raises(DecisionError):
        DecisionQuestion("q", "1", **dict(choice, options={"a": "A"}))
    with pytest.raises(DecisionError):
        DecisionQuestion("q", "1", **dict(choice, options={"a": "A", "b": "B"},
                                          allowed_answer_ids=("a",)))
    with pytest.raises(DecisionError):
        DecisionQuestion("q", "1", **dict(choice, question_text=""))
    with pytest.raises(DecisionError):
        DecisionQuestion("q", "1", kind="score", question_text="x",
                         bounded_state={}, scale=("only",))


def test_evidence_never_accepts_prompt_or_raw_response(tmp_path):
    store = FilesystemEvidenceStore(tmp_path / "evidence")
    base = {"job_digest": "a" * 64}
    for key in ("prompt", "response", "text", "secret"):
        with pytest.raises(DecisionError):
            store.put(dict(base, **{key: "x"}))
    ref = store.put(base)
    assert store.get(ref)["job_digest"] == "a" * 64


def test_retired_manager_graph_is_not_registered_as_a_fallback():
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("decision_runtime.runtime.manager")
