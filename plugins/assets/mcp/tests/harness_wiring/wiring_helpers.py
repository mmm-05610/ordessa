"""T013 wiring fixtures: real API DTOs around the brand binding + the C4 chain.

Everything runs in-process: the "harness instance" of the controlled chain
is the REAL ``ordessa_harness.application.ConfigurationApplicationService``
over the REAL contribution carrier host and the REAL merge/materialization
authorities, with the same in-memory controlled-runtime pattern the
harness's own controlled test uses (fixtures/test_configuration_service_
controlled.py) — no CLI spawn, no network (the parent conftest holds the
seal), no HOME reads. The composition emulation lives HERE (tests), never
in backend/ (AGENTS import boundary).
"""
from dataclasses import dataclass, replace
from typing import Mapping, Optional

import native_helpers as nh
from ordessa_harness_api import (
    AdapterContext, ApplicationTarget, Assessment, Installation, Plan,
    TargetDescriptor, TargetHandle,
)
from server_plugin_api import (
    Contribution, ContributionBatch, ServerPluginDescriptor,
    ServerPluginRegistration,
)

from adapters import claude as claude_mod, codex as codex_mod
from backend import native_binding as nb

CANARY = nh.CANARY


# -- planned domain sets (via the real brand compiles) ---------------------------

def claude_planned(env=(("FOO", nh.Literal("bar")),), secrets=(),
                   destination=None, lanes=None, extra_managed=(),
                   catalog=None):
    """Compile one claude-lane plan through the REAL domain compile."""
    env_map = dict(env)
    for name, cid in secrets:
        env_map[name] = nh.SecretRef(cid)
    rev = nh.stdio_revision("d1", 1, "demo", "/bin/true", (), env_map)
    revisions = {("d1", 1): rev}
    snapshot_lanes = {"d1": {"lane": "native", "enforcement": "proven"}}
    for i, m in enumerate(extra_managed):
        revisions[(m[0], 1)] = nh.stdio_revision(m[0], 1, m[1], m[2])
        snapshot_lanes[m[0]] = {"lane": "managed", "enforcement": "proven"}
    snapshot = nh.build_snapshot(list(revisions.values()), snapshot_lanes)
    provenance = nh.DictProvenance({
        cid: nh.attestation(cid) for _, cid in secrets})
    planned = claude_mod.compile(
        snapshot, destination or nh.instance_target("claude"), provenance,
        revision_provider=nh.revision_provider(revisions.items()),
        expected_catalog_digests=catalog or {})
    return planned


def codex_planned(session=True, env=(("FOO", nh.Literal("bar")),),
                  destination=None):
    rev = nh.stdio_revision("d1", 1, "demo", "/bin/true", (), dict(env))
    snapshot = nh.build_snapshot([rev], {"d1": {"lane": "native",
                                                "enforcement": "proven"}})
    dest = destination or (nh.session_target("codex") if session
                           else nh.instance_target("codex"))
    return codex_mod.compile(snapshot, dest, nh.DictProvenance({}),
                             revision_provider=nh.revision_provider({("d1", 1): rev}))


# -- API contexts (server-supplied shapes) ---------------------------------------

def file_target(harness: str, scope: str, generation: int = 7):
    handle = TargetHandle(nb.instance_target_id(harness) if scope == "instance"
                          else nb.session_target_id(harness), generation)
    codec = "toml" if harness == "codex" else "json"
    key = "mcp_servers" if harness == "codex" else "mcpServers"
    return TargetDescriptor(handle, "file", codec, scope, ((key,),))


def environment_target(harness: str, scope: str, slots, generation: int = 7):
    handle = TargetHandle(f"assets.mcp.{harness}.instance-env", generation)
    return TargetDescriptor(handle, "environment", "environment", scope,
                            tuple((slot,) for slot in slots))


def api_context(brand, scope="instance", generation=7, harness_id=None,
                entry="acp", extra_targets=(), native_version=(1, 0, 0)):
    harness = brand.harness_type
    target = file_target(harness, scope, generation)
    targets = [target] + list(extra_targets)
    installation = Installation(harness_id or harness, native_version,
                                (1, 0, 0), "ev:installed")
    return AdapterContext(tuple(targets), installation, entry, scope,
                          "ev:capability")


# -- stub C4 port (the service-level refusals; NOT the real service) -------------

class StubConfigurationService:
    """Duck-typed ``ordessa_harness_api.ConfigurationService``: records the
    exact call args and answers with the next queued result."""

    def __init__(self, target=None, results=()):
        self.target = target
        self._results = list(results)
        self.calls = []

    def plan(self, target, desired_fragments, expected_revision):
        self.calls.append((target, desired_fragments, expected_revision))
        if self._results:
            return self._results.pop(0)
        return make_plan(target)

    def inspect(self, target):  # pragma: no cover - protocol shape only
        raise NotImplementedError

    def apply(self, plan_id, operation_key, submission_permit):
        self.calls.append(("apply", plan_id, operation_key, submission_permit))
        return self._results.pop(0) if self._results else None

    def query(self, operation_key):  # pragma: no cover - protocol shape only
        raise NotImplementedError

    def reconcile(self, operation_key):  # pragma: no cover - protocol shape only
        raise NotImplementedError


def make_plan(target, plan_id="plan-proof-1"):
    return Plan(plan_id, target, "sha256:desired", "base-1", "native-version-1",
                1, "auth-1", "secret-ref-1", "2026-09-29T00:00:00+00:00")


def refused(code, message="stub refusal"):
    from ordessa_harness_api import Refused
    return Refused(code, (message,), True)


def submission_unknown():
    from ordessa_harness_api import Unknown
    return Unknown("op-1", "verifying", ("effect-1",),
                   ("readback pending",), "reconcile")


def real_target():
    return ApplicationTarget("s1", "session-a", "channel-1", 7)


# -- contribution carrier (product-assembly emulation for the chain) -------------

CONFIGURATION_POINT = nb.CONFIGURATION_POINT_ID
POINT_API_VERSION = nb.POINT_API_VERSION


class AdapterContributionPlugin:
    """What the product composition does with a brand adapter: contribute it
    to the declared ``harness.configuration-adapters@v1`` point (the payload
    is the adapter; the harness registry validates the descriptor)."""

    def __init__(self, owner, adapter) -> None:
        self._owner = owner
        self._adapter = adapter

    def descriptor(self):
        return ServerPluginDescriptor(self._owner, "MCP adapter carrier", "1")

    def build(self, context):
        return ServerPluginRegistration(contributions=ContributionBatch((
            Contribution(CONFIGURATION_POINT, POINT_API_VERSION,
                         self._adapter, required=True),
        )))
