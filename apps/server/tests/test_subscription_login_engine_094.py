"""Work Order 094: the login engine against a fake device-code endpoint.

The mechanical path (begin -> pending x N -> authorized, and the terminal
cancel/expire paths) is fully exercised in-process with an injected transport, so
no real credential is touched. The gates that must actually bite:

* G1 a cancelled or expired session fires ZERO further outbound requests;
* G2 no token value appears in any client-facing view (and the tokens go only to
  the landing callback, which stores them in the secret store);
* G4 an unregistered family is refused with zero outbound (never a guessed
  endpoint), and a flow whose family declares no state file is refused too;
* G3 a successful device-code path lands the native auth.json bytes.
"""
from __future__ import annotations

import pytest

from ordessa_server_compat.accounts.login_engine import LoginEngine
from ordessa_server.errors import ServerError


class FakeTransport:
    """Scripts device-code responses and counts every outbound request."""

    def __init__(self, token_responses):
        self._token_responses = list(token_responses)
        self.outbound = 0
        self.landed = None

    def post(self, url, payload):
        self.outbound += 1
        if url.endswith("/usercode"):
            return {"device_auth_id": "da-1", "user_code": "ABCD-EFGH",
                    "verification_uri_complete": "https://auth.openai.com/codex/device",
                    "interval": 1, "expires_in": 900}
        if url.endswith("/token"):
            if not self._token_responses:
                return {"status": "authorization_pending"}
            return self._token_responses.pop(0)
        raise AssertionError(f"unexpected url {url}")


def _engine(token_responses, clock=None, declared=None):
    transport = FakeTransport(token_responses)
    now = {"t": 1000.0}
    clock_fn = clock or (lambda: now["t"])
    engine = LoginEngine(
        transport=transport, now=clock_fn,
        land_asset=lambda harness, files, account: setattr(
            transport, "landed", (harness, files, account)),
        **({"declared_files": declared} if declared is not None else {}))
    return engine, transport, now


def test_happy_path_lands_asset_and_view_has_no_token():
    engine, transport, _ = _engine([
        {"status": "authorization_pending"},
        {"status": "authorized", "authorization_code": {
            "access_token": "SECRET-ACCESS", "refresh_token": "SECRET-REFRESH",
            "account_id": "acct-77"}}])
    begun = engine.begin("codex")
    assert begun["userCode"] == "ABCD-EFGH" and begun["state"] == "pending"
    assert transport.outbound == 1                    # only the usercode call so far
    assert engine.poll(begun["loginId"])["state"] == "pending"
    done = engine.poll(begun["loginId"])
    assert done["state"] == "authorized" and done["accountId"] == "acct-77"
    # G2: no token value anywhere in the client view.
    assert "SECRET-ACCESS" not in repr(done) and "SECRET-REFRESH" not in repr(done)
    # G3: the native auth.json landed, holding the tokens for the secret store.
    harness, files, account = transport.landed
    assert harness == "codex" and account == "acct-77"
    assert "auth.json" in files and b"SECRET-ACCESS" in files["auth.json"]


def test_cancel_stops_all_further_outbound():
    engine, transport, _ = _engine([{"status": "authorization_pending"}])
    begun = engine.begin("codex")
    before = transport.outbound
    engine.cancel(begun["loginId"])
    for _ in range(5):
        view = engine.poll(begun["loginId"])
    assert view["state"] == "cancelled"
    assert transport.outbound == before               # zero outbound after cancel


def test_expiry_stops_outbound_without_a_token_call():
    now = {"t": 1000.0}
    engine, transport, _ = _engine([{"status": "authorized", "authorization_code": {
        "access_token": "X", "refresh_token": "Y", "account_id": "z"}}],
        clock=lambda: now["t"])
    begun = engine.begin("codex")                     # expires_at = 1000 + 900
    now["t"] = 2000.0                                 # past expiry
    view = engine.poll(begun["loginId"])
    assert view["state"] == "expired"
    assert transport.outbound == 1                     # only the initial usercode call


def test_unregistered_family_refused_with_zero_outbound():
    engine, transport, _ = _engine([])
    with pytest.raises(ServerError) as exc:
        engine.begin("hermes")
    assert exc.value.code == "LOGIN_FLOW_UNSUPPORTED"
    assert transport.outbound == 0                     # never guessed, never called


def test_flow_without_declared_state_files_is_refused():
    # codex has a flow but we drop it from the declared-files set -> refused.
    engine, transport, _ = _engine([], declared=set())
    with pytest.raises(ServerError) as exc:
        engine.begin("codex")
    assert exc.value.code == "LOGIN_STATE_FILES_UNDECLARED"
    assert transport.outbound == 0
