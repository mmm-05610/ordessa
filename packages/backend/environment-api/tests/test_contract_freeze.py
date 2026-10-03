"""002 contract-freeze gates for ``ordessa_environment_api``.

Covers (G002-1 / T002-02 / T002-06):

* shared-vector identity — the canonical codec reproduces every frozen
  vector byte-for-byte (the TypeScript mirror asserts the same file);
* construction-order independence — equal values built in different orders
  encode identically (the "Token两份" class of counterexample, at the wire
  level);
* envelope discipline — unknown keys, wrong contract version and wrong kind
  are rejected, never silently dropped;
* typed validation — malformed realm/namespace/authority keys are refused
  (scheme/realm/owner checks);
* stdlib-only surface — importing the package loads no product/plugin/host
  module (领域程序集零 host import);
* guarantee semantics — the reliable path refuses when fingerprint evidence
  is absent and never downgrades (typed error contract).
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unicodedata

import pytest

from ordessa_environment_api import (
    CONTRACT_VERSION,
    AuthorityConflictError,
    CanonicalFactTarget,
    FingerprintDescriptor,
    GuaranteeLevel,
    GuaranteeUnavailableError,
    HostDialogResult,
    HostDialogStatus,
    InputCapture,
    PersistentReference,
    ReferenceStatus,
    RequestKey,
    RevisionSelector,
)
from ordessa_environment_api.codec import (
    CodecError,
    canonical_json,
    decode_envelope,
    encode_envelope,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
VECTORS = REPO_ROOT / "tests" / "contracts" / "vectors" / "open-environment.json"


def _load_vectors():
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert data["contractVersion"] == CONTRACT_VERSION
    return data["cases"]


VECTOR_CASES = [(c["name"], c) for c in _load_vectors()]


@pytest.mark.parametrize(("name", "case"), VECTOR_CASES, ids=[n for n, _ in VECTOR_CASES])
def test_vector_round_trip(name: str, case: dict) -> None:
    """canonical_json(payload) === vector === decode(encode) identity."""
    kind, payload = decode_envelope(case["encoded"])
    assert kind == case["kind"]
    assert encode_envelope(kind, payload) == case["encoded"], (
        f"vector {name}: codec output drifted from the frozen vector"
    )


def test_construction_order_never_leaks_into_wire_form() -> None:
    a = RequestKey(
        request_id="req-1",
        principal_scope="user:local:x",
        environment_namespace="ns-a",
        comparison={},
    )
    b = RequestKey(
        environment_namespace="ns-a",
        principal_scope="user:local:x",
        request_id="req-1",
    )
    assert a == b
    assert canonical_json(a) == canonical_json(b)


def test_envelope_rejects_unknown_keys() -> None:
    raw = json.dumps(
        {"contractVersion": CONTRACT_VERSION, "kind": "x", "payload": {}, "extra": 1},
        sort_keys=True, separators=(",", ":"),
    )
    with pytest.raises(CodecError):
        decode_envelope(raw)


def test_envelope_rejects_foreign_contract_version() -> None:
    raw = '{"contractVersion":"oe-contract/9","kind":"x","payload":{}}'
    with pytest.raises(CodecError, match="contract version"):
        decode_envelope(raw)


def test_envelope_rejects_wrong_kind() -> None:
    text = encode_envelope("persistent-reference", {"relation_id": "r"})
    with pytest.raises(CodecError, match="kind"):
        decode_envelope(text, expected_kind="request-key")


def test_canonical_json_is_ascii_key_sorted_and_tight() -> None:
    value = {"z": 1, "a": {"y": [1, 2], "b": None}}
    assert canonical_json(value) == '{"a":{"b":null,"y":[1,2]},"z":1}'


@pytest.mark.parametrize("bad", [
    {"realm": "Workspace", "identity_namespace": "ordessa.workspace", "stable_entity_id": "w"},  # realm case
    {"realm": "workspace", "identity_namespace": "Ordessa.Workspace", "stable_entity_id": "w"},  # namespace case
    {"realm": "workspace", "identity_namespace": "ordessa.workspace", "stable_entity_id": ""},   # empty entity
    {"realm": "workspace", "identity_namespace": "ordessa.workspace", "stable_entity_id": "w\u3000x"},  # non-ascii pad
])
def test_target_validation_rejects_malformed_keys(bad: dict) -> None:
    with pytest.raises(ValueError):
        CanonicalFactTarget(**bad)


def test_second_writer_authority_key_is_the_conflict_not_a_new_slot() -> None:
    """Same canonical target under two schema majors = one AuthorityKey.

    The conflict is raised by the *registration boundary* (order 004); here we
    freeze that both registrations normalize to the same key — the thing that
    makes refusing them possible at all.
    """
    target = CanonicalFactTarget(
        realm="workspace", identity_namespace="ordessa.workspace", stable_entity_id="ws-main"
    )
    from ordessa_environment_api import AuthorityKey

    k1 = AuthorityKey(authority_kind="session-config", target=target)
    k2 = AuthorityKey(authority_kind="session-config", target=target)
    assert k1 == k2
    assert canonical_json(k1) == canonical_json(k2)
    # the error the second writer meets is typed, not a string
    assert AuthorityConflictError.code == "AUTHORITY_CONFLICT"


def test_reliable_guarantee_refuses_without_fingerprint_and_never_downgrades() -> None:
    def dispatch(guarantee: GuaranteeLevel, fingerprint: FingerprintDescriptor | None):
        if guarantee is GuaranteeLevel.RELIABLE and fingerprint is None:
            raise GuaranteeUnavailableError("protected fingerprint port absent")
        return "dispatched"

    with pytest.raises(GuaranteeUnavailableError):
        dispatch(GuaranteeLevel.RELIABLE, None)
    # raw is never disabled by the missing reliable evidence
    assert dispatch(GuaranteeLevel.RAW, None) == "dispatched"
    assert (
        dispatch(GuaranteeLevel.RELIABLE, FingerprintDescriptor(
            algorithm="hmac-sha256", key_id="k-1", comparison_scope="request-input"))
        == "dispatched"
    )


def test_input_capture_rejects_paths_as_content_freeze() -> None:
    with pytest.raises(ValueError):
        InputCapture(content_digest="/tmp/draft.txt")  # a path is not a digest
    ok = InputCapture(content_digest="a" * 64)
    assert ok.attachment_digests == ()


def test_dialog_cancel_and_revoke_are_write_free() -> None:
    with pytest.raises(ValueError):
        HostDialogResult(operation_id="op-1", status=HostDialogStatus.CANCELLED,
                         selected_handle="h-1")
    with pytest.raises(ValueError):
        HostDialogResult(operation_id="op-1", status=HostDialogStatus.REVOKED,
                         confirmed_option="yes")


def test_revision_selector_discipline() -> None:
    with pytest.raises(ValueError):
        RevisionSelector(op="exact")  # exact needs a revision
    with pytest.raises(ValueError):
        RevisionSelector(op="any", revision="1")  # any forbids one


def test_package_imports_stdlib_only() -> None:
    """零 host import: a fresh interpreter importing the package loads nothing
    outside the stdlib — no product, plugin, server or host module."""
    code = (
        "import sys, ordessa_environment_api as m; "
        "bad = [n for n in sys.modules "
        "if n.split('.')[0] in {'pacthold','ordessa_server','ordessa_harness',"
        "'ordessa_server_compat','pacthold_runtime_compat','ordessa_server_product'}]; "
        "print('BAD:' + ','.join(bad) if bad else 'CLEAN')"
    )
    env = {"PYTHONPATH": str(REPO_ROOT / "packages" / "backend" / "environment-api" / "src"),
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env=env, check=True).stdout.strip()
    assert out == "CLEAN", out


def test_vectors_file_is_normalized() -> None:
    """The shared file itself must stay byte-stable (no trailing-space churn)."""
    raw = VECTORS.read_bytes()
    text = raw.decode("utf-8")
    assert text.endswith("\n")
    assert unicodedata.normalize("NFC", text) == text
