"""L2 helpers: real HTTP client factory wiring + credential fakes + scans.

The witness for every "the server never saw it" claim is the fake's own
request ledger (:mod:`fake_http_mcp`), read server-side - never the
client's self-report.
"""
from __future__ import annotations

from backend.managed.client_http import HttpClientPolicy, make_http_client_factory
from backend.secret import CredentialBinding, LaunchPlan
from managed_helpers import SERVER_SCOPE, ManagedHarness

#: the only value the fake credential layer ever hands out; every
#: plaintext-scan test asserts this string appears NOWHERE in events,
#: facts, exception texts, return values or client state (FR-08).
SENTINEL = "s3ntin3l-authorization-8cf2"

#: generous for functional tests; BRIEF drives the honest timeout path.
FAST = HttpClientPolicy(request_timeout=5.0, initialize_timeout=5.0, connect_timeout=5.0)
BRIEF = HttpClientPolicy(request_timeout=0.3, initialize_timeout=0.3, connect_timeout=5.0)

CRED_ID = "cred-1"
HEADER_SLOT = "Authorization"


class FakeCredentialPort:
    """CredentialPort double: serves the sentinel under a movable revision.

    ``rotate()`` changes what the store hands out WITHOUT touching the plan,
    i.e. exactly the FR-08 rotation that must make a frozen plan stale.
    """

    def __init__(self, *, present: bool = True, revision: str = "rev-1") -> None:
        self.present = present
        self.revision = revision
        self.reads = 0

    def has(self, credential_id: str) -> bool:
        return self.present and credential_id == CRED_ID

    def read(self, credential_id: str):
        self.reads += 1
        if not self.present:
            raise KeyError(credential_id)
        return SENTINEL, self.revision

    def rotate(self) -> None:
        self.revision = "rev-2-rotated"

    def revoke(self) -> None:
        self.present = False


def make_plan(*, definition_id: str, revision: int, principal: str = "u-a",
              bound_revision: str = "rev-1", slot: str = HEADER_SLOT,
              expires_at: float | None = None, with_binding: bool = True) -> LaunchPlan:
    bindings = ()
    if with_binding:
        bindings = (CredentialBinding(
            definition_id=definition_id, revision=revision, slot=slot,
            credential_id=CRED_ID, bound_revision=bound_revision, kind="header"),)
    return LaunchPlan(principal=principal, bindings=bindings,
                      session_ref="sess-a", expires_at=expires_at)


class HttpRealFactory:
    """Wraps the production http factory; ``produced`` is the no-pooling witness."""

    def __init__(self, definitions, *, policy=FAST, launch_plan=None, credential_port=None):
        self._inner = make_http_client_factory(
            definitions, policy=policy, launch_plan=launch_plan,
            credential_port=credential_port)
        self.policy = policy
        self.produced: list = []

    def __call__(self, lease):
        client = self._inner(lease)
        self.produced.append(client)
        return client


def secret_remote(harness: ManagedHarness, endpoint_url: str, *,
                  definition_id: str = "srv-http",
                  headers: dict | None = None) -> int:
    """Store + approve a remote revision pointed at the fake endpoint."""
    return harness.install_remote(
        definition_id=definition_id,
        url=f"{endpoint_url}/mcp",
        headers=headers if headers is not None
        else {HEADER_SLOT: {"secretRef": CRED_ID}})


def plaintext_hits(node, needle: str = SENTINEL) -> list:
    """Deep-scan any structure (dicts/lists/str/bytes/objects via repr) for
    the sentinel; returns the paths where it leaked."""
    hits: list = []

    def walk(current, path: str):
        if isinstance(current, str):
            if needle in current:
                hits.append(path)
        elif isinstance(current, (bytes, bytearray)):
            if needle.encode() in bytes(current):
                hits.append(path)
        elif isinstance(current, dict):
            for key, value in current.items():
                walk(key, f"{path}.<key>")
                walk(value, f"{path}.{key}")
        elif isinstance(current, (list, tuple, set, frozenset)):
            for index, item in enumerate(current):
                walk(item, f"{path}[{index}]")
        elif current is not None:
            if needle in repr(current):
                hits.append(path + ".__repr__")

    walk(node, "$")
    return hits


def bring_up(mgr, harness: ManagedHarness, caller, definition_id: str, revision: int, *,
             credential_revision: str | None = None):
    """open -> plan -> start -> observe over the http factory (returns lease)."""
    lease = mgr.open_lease(
        caller=caller, server_scope=SERVER_SCOPE,
        definition_id=definition_id, revision=revision,
        credential_revision=credential_revision)
    mgr.plan_connection(caller=caller, lease_id=lease.lease_id, submission_id="sub-1")
    mgr.start_connection(caller=caller, lease_id=lease.lease_id)
    catalog = mgr.observe_catalog(caller=caller, lease_id=lease.lease_id)
    return lease, catalog
