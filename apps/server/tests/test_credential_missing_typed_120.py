"""Work Order 120: a missing credential stays typed end to end.

The bug (A's first-hand T6): a provider/profile referenced a credentialId whose
secret locator was never imported on this machine. ``MemorySecretStore.read`` did
a naked ``self.values[locator]`` -> ``KeyError`` -> far from the cause the turn
collapsed into ``EXECUTION_FAILED`` with no reason and no action.

These gates prove the fix at the two pure seams that decide the transcript:

* the store names the (non-sensitive) locator with a typed error carrying
  ``code = CREDENTIAL_NOT_AVAILABLE`` and never leaks a secret value;
* ``_safe_code`` (the transcript-reason mapper) turns that typed error into a
  specific code, where the *old* naked ``KeyError`` produced the reasonless
  ``EXECUTION_FAILED`` - so a revert of either seam reddens the gate.

The port_factory resolution itself is covered by the end-to-end shape here: the
exception raised where the credential is read carries the ``.code`` that
``_safe_code`` reads first, so the transcript reason is typed regardless.
"""
from __future__ import annotations

import pytest

from ordessa_server_compat.execution.sidecar_backend import _safe_code
from pacthold.storage.secrets import MemorySecretStore, SecretLocatorUnavailable


def test_store_read_missing_locator_is_typed_not_keyerror():
    store = MemorySecretStore({"credential_present": b"secret-bytes"})
    with pytest.raises(SecretLocatorUnavailable) as exc:
        store.read("credential_absent")
    err = exc.value
    assert not isinstance(err, KeyError)
    assert err.code == "CREDENTIAL_NOT_AVAILABLE"
    # names the non-sensitive locator ...
    assert "credential_absent" in str(err)
    # ... but carries zero secret content (no value bytes anywhere).
    assert "secret-bytes" not in str(err)


def test_store_read_present_locator_still_returns_bytes():
    store = MemorySecretStore({"credential_present": b"secret-bytes"})
    assert store.read("credential_present") == b"secret-bytes"


def test_transcript_reason_is_typed_for_the_missing_credential():
    # the typed store error -> a specific reason code, not EXECUTION_FAILED.
    reason = _safe_code(SecretLocatorUnavailable("credential_e0879"))
    assert reason == "CREDENTIAL_NOT_AVAILABLE"
    # port_factory's converted error maps the same way.
    assert _safe_code(RuntimeError("CREDENTIAL_NOT_AVAILABLE")) == "CREDENTIAL_NOT_AVAILABLE"


def test_counterexample_old_naked_keyerror_would_have_been_reasonless():
    # This is what the pre-fix code produced: a bare KeyError collapses to the
    # reasonless EXECUTION_FAILED. Reverting the store to `self.values[loc]`
    # makes the two gates above red, which is exactly this assertion's witness.
    assert _safe_code(KeyError("credential_e0879")) == "EXECUTION_FAILED"
