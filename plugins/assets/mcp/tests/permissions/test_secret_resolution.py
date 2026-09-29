"""V07 gate: plan-bound credential resolution, fail-closed and batch-or-nothing.

FR-08 / contracts §5 / verification counterexample 8: rotation or revocation
makes the plan stale (typed refusal, nothing partially injected); a
``secret_store=None`` host (non-NT) refuses resolution with
``SECRET_UNRESOLVED``; the glue never writes plaintext anywhere.
"""
from __future__ import annotations

import pytest

from backend.errors import SECRET_UNRESOLVED, McpError
from backend.secret import (
    PLAN_STALE,
    CredentialBinding,
    CredentialPort,
    LaunchPlan,
    host_credential_port,
    resolve_for_launch,
    snapshot_credential_bindings,
)

from perms_helpers import FakeCredentialPort, make_snapshot

ALPHA = "s3cr3t-alpha"
BETA = "s3cr3t-beta"
NOW = 150.0


def binding(slot="TOKEN", cred="cred-1", bound="rev-1", kind="env", **over):
    params = dict(definition_id="def1", revision=1, slot=slot,
                  credential_id=cred, bound_revision=bound, kind=kind)
    params.update(over)
    return CredentialBinding(**params)


def plan(*bindings_, expires_at=None):
    return LaunchPlan(principal="alice", bindings=tuple(bindings_),
                      session_ref="sess-1", expires_at=expires_at)


@pytest.fixture
def port():
    return FakeCredentialPort({"cred-1": (ALPHA, "rev-1"), "cred-2": (BETA, "rev-7")})


# -- happy path (L0/L1: fake ports, controlled) ---------------------------------------


def test_resolve_returns_transient_env_header_maps_with_proofs(port):
    result = resolve_for_launch(
        plan(binding(), binding(slot="Authorization", cred="cred-2", bound="rev-7", kind="header")),
        port, NOW)
    assert result.env == {"def1#1#env#TOKEN": ALPHA}
    assert result.headers == {"def1#1#header#Authorization": BETA}
    assert [p.resolved_revision for p in result.proofs] == ["rev-1", "rev-7"]
    assert [p.credential_id for p in result.proofs] == ["cred-1", "cred-2"]
    assert result.references()  # ref-only view exists for persistence/API


def test_fake_port_satisfies_the_credential_port_protocol(port):
    assert isinstance(port, CredentialPort)
    assert isinstance(host_credential_port(credential_records=None, secret_store=None),
                      CredentialPort)


# -- rotation / revocation / expiry: whole batch refuses --------------------------------


def test_rotation_makes_the_plan_stale(port):
    port.rotate("cred-1", "s3cr3t-alpha-v2", "rev-2")  # rotated after the plan froze rev-1
    with pytest.raises(McpError) as raised:
        resolve_for_launch(plan(binding()), port, NOW)
    assert raised.value.code == PLAN_STALE
    assert "stale plan" in raised.value.message
    assert "def1#1#env#TOKEN" in raised.value.message  # names the slot...
    assert ALPHA not in str(raised.value)             # ...never the value


def test_revocation_is_typed_unresolved(port):
    port.revoke("cred-1")
    with pytest.raises(McpError) as raised:
        resolve_for_launch(plan(binding()), port, NOW)
    assert raised.value.code == SECRET_UNRESOLVED


def test_one_stale_slot_refuses_the_whole_batch_no_partial_injection(port):
    port.rotate("cred-2", "s3cr3t-beta-v2", "rev-8")
    with pytest.raises(McpError) as raised:
        resolve_for_launch(
            plan(binding(), binding(slot="Authorization", cred="cred-2",
                                    bound="rev-7", kind="header")),
            port, NOW)
    assert raised.value.code == PLAN_STALE
    # the healthy slot was read transiently but released to nobody: the call
    # raised, so no env/header map exists for the good slot either.
    assert ALPHA not in str(raised.value)
    assert BETA not in str(raised.value)


def test_expired_plan_refuses_before_touching_the_store():
    port = FakeCredentialPort({"cred-1": (ALPHA, "rev-1")})
    with pytest.raises(McpError) as raised:
        resolve_for_launch(plan(binding(), expires_at=100.0), port, 101.0)
    assert raised.value.code == PLAN_STALE
    assert "expired" in raised.value.message
    assert port.has_calls == [] and port.read_calls == []


# -- plan binding aligns with the resolve snapshot ---------------------------------------


def test_bindings_are_frozen_from_snapshot_credential_ref_revisions():
    snapshot = make_snapshot(credential_slots=(("TOKEN", "cred-1"),
                                               ("Authorization", "cred-2")))
    bindings = snapshot_credential_bindings(
        snapshot, {"cred-1": "rev-1", "cred-2": "rev-7"},
        kinds_by_slot={("def1", 1, "Authorization"): "header"})
    assert [(b.slot, b.credential_id, b.bound_revision, b.kind) for b in bindings] == [
        ("TOKEN", "cred-1", "rev-1", "env"),
        ("Authorization", "cred-2", "rev-7", "header"),
    ]
    result = resolve_for_launch(
        LaunchPlan(principal="alice", bindings=bindings), 
        FakeCredentialPort({"cred-1": (ALPHA, "rev-1"), "cred-2": (BETA, "rev-7")}), NOW)
    assert result.env == {"def1#1#env#TOKEN": ALPHA}


def test_unbound_slot_cannot_enter_a_plan():
    snapshot = make_snapshot()
    with pytest.raises(McpError) as raised:
        snapshot_credential_bindings(snapshot, {})  # no observed revision for cred-1
    assert raised.value.code == SECRET_UNRESOLVED


def test_plan_shape_is_validated():
    with pytest.raises(McpError):
        CredentialBinding("def1", 1, "TOKEN", "cred-1", "")          # unbound revision
    with pytest.raises(McpError):
        CredentialBinding("def1", 1, "TOKEN", "cred-1", "rev-1", kind="cookie")
    with pytest.raises(McpError):
        LaunchPlan(principal="")
    with pytest.raises(McpError):
        LaunchPlan(principal="alice", bindings=(binding(), binding()))  # duplicate slot
    with pytest.raises(McpError):
        resolve_for_launch("not a plan", FakeCredentialPort(), NOW)


# -- the host two-layer adapter (G7): injected records + secret_store --------------------


class _Records:
    def __init__(self, rows):
        self.rows = rows  # credential_id -> locator row

    def exists(self, credential_id):
        return credential_id in self.rows

    def get(self, credential_id):
        return dict(self.rows[credential_id])


class _Store:
    def __init__(self, values):
        self.values = values  # locator -> bytes

    def read(self, locator):
        return self.values[locator]


def test_host_adapter_reads_through_both_layers_and_digests_the_revision():
    records = _Records({"cred-1": {"id": "cred-1", "secret_locator": "cred-1.dpapi"}})
    store = _Store({"cred-1.dpapi": ALPHA.encode()})
    port = host_credential_port(credential_records=records, secret_store=store)
    assert port.has("cred-1") and not port.has("cred-x")
    plaintext, revision = port.read("cred-1")
    assert plaintext == ALPHA
    assert revision.startswith("sha256:") and ALPHA not in revision  # digest, never value
    # same bytes -> same revision; rotated bytes -> different revision (stale catches it)
    assert port.read("cred-1")[1] == revision
    store.values["cred-1.dpapi"] = b"rotated-value"
    assert port.read("cred-1")[1] != revision


def test_host_adapter_secret_store_none_fails_closed():
    """非 NT ``secret_store=None``: resolution is a typed SECRET_UNRESOLVED,
    and ``has`` is False so even planning refuses without pretending."""
    port = host_credential_port(credential_records=_Records(
        {"cred-1": {"id": "cred-1", "secret_locator": "x"}}), secret_store=None)
    assert port.has("cred-1") is False
    with pytest.raises(McpError) as raised:
        port.read("cred-1")
    assert raised.value.code == SECRET_UNRESOLVED
    with pytest.raises(McpError) as raised:
        resolve_for_launch(plan(binding()), port, NOW)
    assert raised.value.code == SECRET_UNRESOLVED


def test_host_adapter_unreadable_locator_is_typed_without_leaking_paths():
    records = _Records({"cred-1": {"id": "cred-1", "secret_locator": "/very/private/where"}})

    class _BoomStore:
        def read(self, locator):
            raise RuntimeError("DPAPI blob missing at /very/private/where")

    port = host_credential_port(credential_records=records, secret_store=_BoomStore())
    with pytest.raises(McpError) as raised:
        port.read("cred-1")
    assert raised.value.code == SECRET_UNRESOLVED
    assert "/very/private/where" not in str(raised.value)  # only the error type is quoted
