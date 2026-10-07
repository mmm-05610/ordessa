"""T06-wiring proof fixtures: the REAL Q5 permissions backend, no mocks.

Everything here composes ``ordessa_permissions_backend`` exactly the way the
published proof script does (``specs/011-q5-safety/proof/permissions_api_proof.py``
importing ``plugins/permissions/backend/tests/support``): the real
``pacthold.storage.Database`` in a pytest tmp dir, the real ``ApprovalFacts`` /
``PolicyRepository`` / ``Authorizer``. Q5 is never mocked - where a test needs
the authority to *raise*, it breaks the real store (drops the table) so the
exception travels through the real service.

The package-level socket/spawn lockdown (``tests/conftest.py``) already
applies; this directory adds its own autouse seal, so even a moved parent
cannot let a proof test open a socket or spawn - SQLite and pure computation
remain (contracts §4: 拒绝先于副作用).
"""
from __future__ import annotations

import datetime as dt
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
_S_SUPPORT = REPO_ROOT / "plugins" / "permissions" / "backend" / "tests"
if str(_S_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_S_SUPPORT))

import ordessa_permissions_api as q5                      # noqa: E402
import ordessa_permissions_backend as q5_backend          # noqa: E402

# T009 relocation: the product ``Database`` facade now ships in
# ``pacthold_runtime_compat.storage`` (``pacthold.storage`` keeps only the
# neutral object/secret primitives). Q5's lane support still imports it from
# the old spelling, so bind the shipped class onto the old path BEFORE
# ``import support``. This is an import-path adaptation to the current tree -
# the class, schema and semantics are the real ones; nothing is mocked.
import pacthold.storage                                   # noqa: E402
if not hasattr(pacthold.storage, "Database"):
    from pacthold_runtime_compat.storage import Database as _ProductDatabase
    pacthold.storage.Database = _ProductDatabase

import support                                            # noqa: E402 (real DB helpers)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)


class _Blocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_side_effect_primitives(monkeypatch):
    def _blocked_socket(*args, **kwargs):
        raise _Blocked("T06 wiring must not open sockets")

    def _blocked_popen(*args, **kwargs):
        raise _Blocked("T06 wiring must not spawn processes")

    monkeypatch.setattr(socket, "socket", _blocked_socket)
    monkeypatch.setattr(subprocess, "Popen", _blocked_popen)
    monkeypatch.setattr(subprocess, "run", _blocked_popen)
    monkeypatch.setattr(subprocess, "call", _blocked_popen)


class MutableClock:
    """The Authorizer's injectable clock, moved by expiry tests."""

    def __init__(self, moment: dt.datetime) -> None:
        self.moment = moment

    def __call__(self) -> dt.datetime:
        return self.moment

    def advance(self, delta: dt.timedelta) -> None:
        self.moment = self.moment + delta


class RecordingAuthorizer(q5_backend.Authorizer):
    """The REAL backend Authorizer, calling the real ``super().evaluate`` and
    keeping every (inputs, outcome) pair so tests assert on the genuine Q5
    outcome objects (``AllowedOnce`` / ``PendingApproval`` / ``Denied`` with
    ``RefusalCode`` / ``PolicyDenyCode`` members), not on strings.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.consultations: list = []

    def evaluate(self, **kwargs):
        outcome = super().evaluate(**kwargs)
        self.consultations.append((dict(kwargs), outcome))
        return outcome


def default_binding(*, session_id: str = "session-1", execution_id: str = "turn-1",
                    native_request_id: str = "native-req-1", target=None):
    """A Q5RequestBinding mirroring ``support.make_operation``'s field defaults,
    so an expected ``OperationRequest`` recomputed via support matches."""
    from backend.permission_adapter import Q5RequestBinding

    return Q5RequestBinding(
        server_instance_id="srv-1", session_id=session_id,
        native_session_id=f"native-session-{session_id}", execution_id=execution_id,
        native_generation="gen-1", native_request_id=native_request_id, target=target)


def table_provider(table):
    """A binding_provider over a {session_ref: Q5RequestBinding} table."""

    def provider(*, session_ref, lease_id, tool_name, args_digest):
        del lease_id, tool_name, args_digest
        return table.get(session_ref)

    return provider


def map_tool_key(mapping):
    def provider(tool_name):
        return mapping.get(tool_name, tool_name)

    return provider


def expected_operation(*, ceilings, intent, tool_key, target=None,
                       argument_digest: str, principal: str = "user-1",
                       session_id: str = "session-1", execution_id: str = "turn-1",
                       native_request_id: str = "native-req-1") -> q5.OperationRequest:
    """The Q5 operation the adapter must have built, via the SAME support
    builders the published proof uses (digests must match symbol-for-symbol)."""
    return support.make_operation(
        ceilings=list(ceilings), intent=intent, tool_key=tool_key, target=target,
        argument_digest=argument_digest, principal=principal, session_id=session_id,
        execution_id=execution_id, native_request_id=native_request_id)


@dataclass
class Q5World:
    """The real backend composed on a throwaway database."""

    root: Path
    database: object = None
    facts: object = None
    policies: object = None
    clock: MutableClock = field(default_factory=lambda: MutableClock(NOW))

    @classmethod
    def build(cls, root: Path) -> "Q5World":
        world = cls(root=root)
        world.database = support.seeded_database(root / "q5-data")
        support.seed_session(world.database, session_id="session-1", execution_id="turn-1")
        support.seed_session(world.database, session_id="session-2", execution_id="turn-2")
        world.facts = q5_backend.ApprovalFacts(world.database)
        world.facts.ensure_schema()
        world.policies = q5_backend.PolicyRepository(world.database)
        world.policies.ensure_schema()
        world.policies.store_ceiling(support.admin_ceiling())
        return world

    def store_ceiling_record(self, raw: dict) -> q5.PolicyCeiling:
        return self.policies.store_ceiling_record(raw)

    def make_authorizer(self, *, intent=None) -> RecordingAuthorizer:
        provider = (lambda: intent) if intent is not None else None
        return RecordingAuthorizer(
            facts=self.facts, policies=self.policies, clock=self.clock,
            **({} if provider is None else {"intent_provider": provider}))

    def make_adapter(self, *, authorizer, intent=None, tool_key_map=None,
                     bindings=None):
        """Compose the adapter under proof against real Q5 pieces."""
        from backend.permission_adapter import Q5PermissionAuthority

        return Q5PermissionAuthority(
            authorizer=authorizer,
            binding_provider=table_provider(
                bindings if bindings is not None else {"session-1": default_binding()}),
            ceiling_provider=self.policies.ceilings_current,
            intent_provider=None if intent is None else (lambda: intent),
            tool_key_provider=None if tool_key_map is None else map_tool_key(tool_key_map))


@pytest.fixture
def world(tmp_path) -> Q5World:
    return Q5World.build(tmp_path)


def intent_allowing(*, rules, intent_id="intent-q4", revision=1) -> q5.PermissionIntent:
    return q5.PermissionIntent.of(intent_id=intent_id, revision=revision,
                                  harness_id="codex", scope=q5.Scope.SESSION, rules=rules)


def snapshot_with(allowed_tool_names, *, definition_id="def1", lane="managed",
                  enforcement="proven"):
    """A real ``backend/resolve.McpEffectiveSnapshot`` carrying the frozen
    tool subset the catalog gate reads."""
    from backend.resolve import McpEffectiveSnapshot

    return McpEffectiveSnapshot(
        target_session="sess-1", runtime_generation=3, project_id="proj-1",
        profile_revision="profile-rev-1",
        definition_revisions=({
            "definition_id": definition_id, "revision": 1,
            "canonical_digest": "sha256:def1-r1", "canonical_shape": "v2",},),
        assignment_revisions=(), credential_ref_revisions=(),
        allowed_tool_names=tuple(allowed_tool_names),
        lane_by_definition={definition_id: {"lane": lane, "enforcement": enforcement}},
        needs_revalidation=(), snapshot_digest="sha256:snapshot")
