"""Work Order 094: the subscription login engine (device-code flow, Server-side).

The engine runs where the keys live (R-0012: the Windows control plane holds
secrets), so a *client* only ever sees a verification URL, a user code and a
status - never a token. This module owns the login *session* and the device-code
protocol; landing the resulting state reuses Order 56's asset path (`pack_asset`
+ the account record), never a second store.

Design boundaries that make it honest:

* only families whose device-code endpoints are first-hand pinned are in
  :data:`LOGIN_FLOWS`; anything else is a typed ``LOGIN_FLOW_UNSUPPORTED`` and
  fires **zero** outbound requests (never a guessed endpoint);
* a family that has a flow but no declared subscription state files is
  ``LOGIN_STATE_FILES_UNDECLARED`` (no landing target => write nothing);
* the HTTP transport is **injected**, so the engine is exercised against a fake
  endpoint in-process (the order's mechanical-path gate) and against the real
  device-code service only through the production transport (which reuses the
  probe's https/timeout/size discipline);
* a cancelled or expired session stops outbound immediately; the counter of
  outbound requests is the gate's witness.
* tokens are handed to the landing callback (which stores them in the secret
  store) and are never placed in any returned view.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping
from uuid import uuid4

from ordessa_server.errors import ServerError


@dataclass(frozen=True)
class LoginFlow:
    """One family's pinned device-code flow, first-hand (never guessed)."""
    harness: str
    user_code_endpoint: str
    token_endpoint: str
    verification_uri_complete_base: str
    client_id: str
    scope: str
    # The native file the resulting state is written to, guest-home-relative.
    # Set only for families that declare `subscriptionCredential.files`.
    state_file: str


# cc-switch's codex OAuth is a first-hand-documented device-code flow; the
# endpoints and the auth.json shape are copied from `codex_oauth.rs` /
# `subscription.rs`. No other family is pinned yet -> refused, not guessed.
LOGIN_FLOWS: dict[str, LoginFlow] = {
    "codex": LoginFlow(
        harness="codex",
        user_code_endpoint="https://auth.openai.com/api/accounts/deviceauth/usercode",
        token_endpoint="https://auth.openai.com/api/accounts/deviceauth/token",
        verification_uri_complete_base="https://auth.openai.com/codex/device",
        client_id="app_EMoamEEZ73f0CkXaXp7hrann",
        scope="openid profile email",
        state_file=".codex/auth.json",
    ),
}

# Families with a first-hand-declared subscription state file (from the seat's
# `subscriptionCredential.files`). A flow whose family is absent here has no
# landing target and must be refused (LOGIN_STATE_FILES_UNDECLARED).
FAMILIES_WITH_DECLARED_STATE_FILES = {"codex"}


@dataclass
class LoginSession:
    login_id: str
    harness: str
    verification_uri: str
    user_code: str
    interval_seconds: int
    device_auth_id: str
    state: str = "pending"          # pending | authorized | expired | cancelled
    expires_at: float = 0.0
    attempts: int = 0
    account_id: str | None = None

    def view(self) -> dict[str, object]:
        # The client-facing shape: no token, no device_auth_id beyond what the
        # flow exposed; state + actionable facts only.
        return {
            "loginId": self.login_id, "harness": self.harness,
            "verificationUri": self.verification_uri, "userCode": self.user_code,
            "intervalSeconds": self.interval_seconds, "expiresAt": self.expires_at,
            "state": self.state, "accountId": self.account_id,
        }


class LoginEngine:
    """Drives device-code sessions. `transport` performs the outbound calls."""

    def __init__(self, *, transport, now: Callable[[], float], land_asset,
                 flows: Mapping[str, LoginFlow] = LOGIN_FLOWS,
                 declared_files: set[str] = FAMILIES_WITH_DECLARED_STATE_FILES,
                 max_attempts: int = 20) -> None:
        self._transport = transport        # transport.post(url, json=..)->dict / get(url)->dict
        self._now = now
        self._land = land_asset            # land_asset(harness, {filename: bytes}, account_id)
        self._flows = dict(flows)
        self._declared_files = set(declared_files)
        self._max_attempts = max_attempts
        self._sessions: dict[str, LoginSession] = {}

    def begin(self, harness: str) -> dict[str, object]:
        flow = self._flows.get(harness)
        if flow is None:
            # Refuse before any outbound call: never invent an endpoint.
            raise ServerError(
                "LOGIN_FLOW_UNSUPPORTED",
                f"{harness} has no first-hand-pinned login flow; use accounts.importAsset",
                status=422,
            )
        if harness not in self._declared_files:
            raise ServerError(
                "LOGIN_STATE_FILES_UNDECLARED",
                f"{harness} has a login flow but no declared subscription state file",
                status=422,
            )
        started = self._transport.post(flow.user_code_endpoint, {
            "client_id": flow.client_id, "scope": flow.scope,
        })
        device_auth_id = str(started["device_auth_id"])
        session = LoginSession(
            login_id=opaque_login_id(), harness=harness,
            verification_uri=str(started.get("verification_uri_complete")
                                 or flow.verification_uri_complete_base),
            user_code=str(started["user_code"]),
            interval_seconds=int(started.get("interval", 5)),
            device_auth_id=device_auth_id,
            expires_at=self._now() + float(started.get("expires_in", 900)),
        )
        self._sessions[session.login_id] = session
        return session.view()

    def poll(self, login_id: str) -> dict[str, object]:
        session = self._require(login_id)
        if session.state in ("authorized", "cancelled"):
            return session.view()                       # terminal, idempotent, no outbound
        if session.state == "expired":
            return session.view()
        if self._now() >= session.expires_at:
            session.state = "expired"
            return session.view()                        # expiry stops outbound too
        session.attempts += 1
        if session.attempts > self._max_attempts:
            session.state = "expired"
            return session.view()
        poll = self._transport.post(session_flow(self._flows, session).token_endpoint, {
            "device_auth_id": session.device_auth_id,
        })
        status = str(poll.get("status", "pending")).lower()
        if status in ("pending", "authorization_pending", "slow_down"):
            return session.view()
        if status == "denied":
            session.state = "expired"                    # a refused code is terminal
            return session.view()
        # authorized: exchange is embedded in the poll response for this flow.
        tokens = poll.get("authorization_code") or poll
        access = str(tokens["access_token"])
        refresh = str(tokens["refresh_token"])
        account = str(tokens.get("account_id") or poll.get("account_id") or "")
        session.account_id = account
        self._land(session.harness, _codex_auth_bytes(access, refresh, account), account)
        session.state = "authorized"
        return session.view()

    def cancel(self, login_id: str) -> dict[str, object]:
        session = self._require(login_id)
        if session.state not in ("authorized",):
            session.state = "cancelled"                  # further poll fires zero outbound
        return session.view()

    def _require(self, login_id: str) -> LoginSession:
        session = self._sessions.get(login_id)
        if session is None:
            raise ServerError("LOGIN_SESSION_NOT_FOUND", "no such login session", status=404)
        return session


def session_flow(flows: Mapping[str, LoginFlow], session: LoginSession) -> LoginFlow:
    return flows[session.harness]


def opaque_login_id() -> str:
    return f"login_{uuid4().hex}"


def _codex_auth_bytes(access: str, refresh: str, account: str) -> dict[str, bytes]:
    """The Codex-native auth.json body holding the tokens (secret-bearing)."""
    import json
    document = {
        "OPENAI_API_KEY": None,
        "auth_mode": "chatgpt",
        "last_refresh": None,
        "tokens": {
            "access_token": access, "refresh_token": refresh,
            "id_token": None, "account_id": account,
        },
    }
    return {"auth.json": json.dumps(document).encode("utf-8")}
