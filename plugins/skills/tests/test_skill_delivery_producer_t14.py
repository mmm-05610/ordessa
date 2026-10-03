"""T14/G19 — the Q1 delivery producer and its composition-level proof.

Covers, in order:
* the producer emits REAL ``agent-box.skill@1`` contract objects (the
  published ``AgentSkillV1``, never redeclared) from the frozen snapshot +
  store facts, and the set is shaped exactly the way the harness
  consumption leg reads it (``generic_cli.py:20-38``: ``item.contract_id``,
  ``item.value.contract``, ``item.value.source.projection_source()``);
* every fail-closed preflight refusal is real (unapproved / not installed
  / digest drift / managed-set collision / native-discovery collision /
  brand+version unknown-or-mismatched / registry limit exceeded, missing
  or undeclared / symlinked store-root escape), and a refusal hands out
  ZERO delivery objects;
* the registry Skill cardinality is READ from the published harness
  registry (``load_builtin_registry`` → the same ``InputSpec``/
  ``ProfileSpec`` surface ``registry/schema.py:140`` guards), never
  hardcoded in the producer;
* the L1/L2 composition proof drives the PUBLISHED runtime-composition
  fakes (``FakeHost``/``FakeSandbox``/``FakeTerminal`` + the generic
  ``assemble_runtime_composition`` coordinator) through
  dispatch → preflight → start(execution_id, dispatch_id) →
  projection_receipt and pins the evidence ladder at ``projected`` — the
  receipt never reads as loaded/used, a refused preflight leaves the
  composition untouched (zero registrations, zero submissions), and guest
  paths appear ONLY in the fake's records, never on the host filesystem.

The missing L3 seam (recorded for C0): no PUBLISHED harness symbol accepts
these resources — ``ordessa_harness_api`` exports no skill contract and
the only consumer is the harness-internal
``ordessa_harness.adapters.generic_cli`` plus the execution providers'
``request.resolved_inputs`` handoff (core dispatch, api-requests.md §G2);
nothing here imports them.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from assignments_support import make_database, make_skill
from ordessa_harness.registry.loader import load_builtin_registry
from pacthold_runtime_compat.runtime_composition import (
    FakeHost, FakeSandbox, FakeTerminal, HarnessCommandSpec, RuntimeHostRef,
    RuntimeHostV1, SandboxRef, SandboxV1, TerminalSessionRef,
    TerminalSessionV1, assemble_runtime_composition, content_digest, digest,
)

from ordessa_skills.api.evidence import (
    LOADED, PROJECTED, USED, attest,
)
from ordessa_skills.assignments.model import DECISION_ENABLE, SCOPE_USER_GLOBAL
from ordessa_skills.assignments.resolver import ResolutionTarget
from ordessa_skills.assignments.snapshot import SkillSnapshot, SnapshotError
from ordessa_skills.harness_adapters.conflict import NameConflictError
from ordessa_skills.harness_adapters.producer import (
    CONTRACT_ID, SkillDeliveryError, build_skill_delivery, skill_input_limits,
)
from ordessa_skills.service import SkillsService

GUEST_TEMPLATE = "/runtime/home/skills/{skill_id}"


# --------------------------------------------------------------------------
# environment
# --------------------------------------------------------------------------

@dataclass
class Env:
    service: SkillsService
    store: object
    approvals: object
    facts: dict = field(default_factory=dict)


def make_env(tmp_path, assets=("t14-one", "t14-two"), revisions=(1,),
             *, approve=True, name=None):
    database = make_database(tmp_path)
    service = SkillsService(database=database, assets_root=tmp_path / "assets",
                            server_scope="srv-test", principal="user-1")
    service.ensure_schema()
    facts = {}
    for asset in assets:
        for revision in revisions:
            facts[(asset, revision)] = make_skill(
                tmp_path, database=database, asset_id=asset,
                revision=revision, approve=approve,
                name=(name or {}).get(asset))
    return Env(service=service, store=service.store,
               approvals=service.approvals, facts=facts)


def codex_definition():
    return load_builtin_registry().get("codex")


def enable(env, asset, revision=1):
    env.service.assignments.upsert(scope_kind=SCOPE_USER_GLOBAL,
                                   asset_id=asset, decision=DECISION_ENABLE,
                                   revision=revision)


def snapshot_of(env, *pins, runtime_generation=3, project_id=None):
    resolved = tuple(
        {"assetId": asset, "revision": revision,
         "treeDigest": env.store.revision_digest(asset_id=asset,
                                                 revision=revision)}
        for asset, revision in pins)
    return SkillSnapshot(
        target_session="s-1", runtime_generation=runtime_generation,
        project_id=project_id, profile_revision=None,
        assignment_revisions={"k|1": 1}, resolved_skills=resolved,
        snapshot_digest="sha256:" + "0" * 64)


def build(env, *pins, harness_id="codex", definition=None, **kwargs):
    return build_skill_delivery(
        snapshot=snapshot_of(env, *pins), store=env.store,
        approvals=env.approvals, harness_id=harness_id,
        harness_definition=definition if definition is not None
        else codex_definition(), **kwargs)


# --------------------------------------------------------------------------
# the producer: real contract facts, consumer-compatible shape
# --------------------------------------------------------------------------

def test_producer_emits_the_published_contract_from_real_facts(tmp_path):
    env = make_env(tmp_path)
    delivery = build(env, ("t14-one", 1), ("t14-two", 1))
    assert len(delivery.items) == 2
    for item in delivery.items:
        contract = item.value.contract
        # the published type itself — not a redeclaration
        assert contract.__class__.__name__ == "AgentSkillV1"
        assert item.contract_id == CONTRACT_ID == "agent-box.skill@1"
        assert contract.digest.startswith("sha256:")
        facts = env.facts[(contract.skill_id, contract.revision)]
        assert contract.digest == facts["facts"]["tree_digest"]
        assert contract.name == facts["facts"]["name"]
        assert contract.description == "A demo skill."
        assert contract.format == "agent-skills"
        assert contract.manifest_name == "SKILL.md"
        # provenance tuple the design requires, from the frozen face
        for key in ("runtimeGeneration", "projectId", "profileRevision",
                    "assignmentRevision", "snapshotDigest"):
            assert key in contract.provenance
        assert contract.provenance["runtimeGeneration"] == "3"
        assert contract.provenance["snapshotDigest"] == delivery.snapshot_digest
        # ephemeral source capability: the real revision directory
        directory = env.store.revision_dir(contract.skill_id,
                                           contract.revision)
        assert item.value.source.projection_source() == directory
        assert (directory / "SKILL.md").is_file()
        assert item.value.size_bytes > 0
    # the serializable view never carries a host path (AgentSkillV1
    # docstring rule: a Ref never contains a host path)
    rendered = json.dumps(delivery.view())
    assert str(tmp_path) not in rendered


def test_consumer_leg_shape_generic_cli_can_read(tmp_path):
    env = make_env(tmp_path)
    delivery = build(env, ("t14-one", 1), ("t14-two", 1))
    # exact read pattern of generic_cli.py:20-35
    skills = [x.value for x in delivery.resolved_inputs()
              if x.contract_id == "agent-box.skill@1"]
    assert len(skills) == 2
    seen = set()
    for skill in skills:
        contract = getattr(skill, "contract", skill)
        source = getattr(skill, "source", None)
        assert source is not None and hasattr(source, "projection_source")
        target = GUEST_TEMPLATE.format(skill_id=contract.skill_id)
        assert target not in seen          # no SKILL_TARGET_COLLISION
        seen.add(target)


def test_service_delivery_set_freezes_and_delivers(tmp_path):
    env = make_env(tmp_path)
    enable(env, "t14-one")
    enable(env, "t14-two")
    delivery = env.service.delivery_set(
        harness_id="codex", project_id=None, session_ref="s-1",
        runtime_generation=3, harness_definition=codex_definition())
    assert len(delivery.items) == 2
    assert {i.value.contract.skill_id for i in delivery.items} == \
        {"t14-one", "t14-two"}


# --------------------------------------------------------------------------
# fail-closed preflight refusals — each raises, none returns a partial set
# --------------------------------------------------------------------------

def test_refuses_not_installed(tmp_path):
    env = make_env(tmp_path, assets=("t14-one",))
    # the pin names a revision that was never installed — the snapshot
    # carries a digest fact for it, delivery must refuse on the filesystem
    snap = SkillSnapshot(
        target_session="s-1", runtime_generation=3, project_id=None,
        profile_revision=None, assignment_revisions={},
        resolved_skills=({"assetId": "t14-one", "revision": 99,
                          "treeDigest": "sha256:" + "a" * 64},),
        snapshot_digest="sha256:" + "0" * 64)
    with pytest.raises(SkillDeliveryError) as refused:
        build_skill_delivery(snapshot=snap, store=env.store,
                             approvals=env.approvals, harness_id="codex",
                             harness_definition=codex_definition())
    assert refused.value.code == "SKILL_DELIVERY_NOT_INSTALLED"


def test_refuses_a_stale_snapshot_before_anything_else(tmp_path):
    # G18 freeze rule on the delivery side: a moved assignment layer is
    # refused with SNAPSHOT_STALE before the rest of the preflight runs.
    env = make_env(tmp_path, revisions=(1, 2))
    enable(env, "t14-one", 1)
    snap = env.service.freeze_snapshot(
        project_id=None, harness_id="codex", profile_id=None,
        session_ref="s-1", runtime_generation=3, session_overrides=())
    enable(env, "t14-one", 2)  # the frozen face moved after the freeze
    with pytest.raises(SnapshotError) as refused:
        build_skill_delivery(
            snapshot=snap, store=env.store, approvals=env.approvals,
            harness_id="codex", harness_definition=codex_definition(),
            resolution_service=env.service.resolution,
            target=ResolutionTarget(project_id=None, harness_id="codex",
                                    profile_id=None, session_ref="s-1",
                                    runtime_generation=3))
    assert refused.value.code == "SNAPSHOT_STALE"


def test_refuses_unapproved_and_yields_no_objects(tmp_path):
    env = make_env(tmp_path, approve=False)
    with pytest.raises(SkillDeliveryError) as refused:
        build(env, ("t14-one", 1), ("t14-two", 1))
    assert refused.value.code == "SKILL_DELIVERY_UNAPPROVED"


def test_refuses_digest_drift_against_the_frozen_pin(tmp_path):
    env = make_env(tmp_path)
    frozen = snapshot_of(env, ("t14-one", 1), ("t14-two", 1))
    extra = env.store.revision_dir("t14-two", 1) / "tampered.md"
    extra.write_text("drift\n", encoding="utf-8")
    with pytest.raises(SkillDeliveryError) as refused:
        build_skill_delivery(snapshot=frozen, store=env.store,
                             approvals=env.approvals, harness_id="codex",
                             harness_definition=codex_definition())
    assert refused.value.code == "SKILL_DELIVERY_DIGEST_MISMATCH"


def test_refuses_digest_drift_against_the_approval_fact(tmp_path):
    env = make_env(tmp_path, assets=("t14-one",))
    (env.store.revision_dir("t14-one", 1) / "late.md").write_text(
        "drift\n", encoding="utf-8")
    # the snapshot is taken AFTER the drift (pin == current tree), so the
    # refusal can only come from the mismatch against the approval fact
    with pytest.raises(SkillDeliveryError) as refused:
        build(env, ("t14-one", 1))
    assert refused.value.code == "SKILL_DELIVERY_DIGEST_MISMATCH"


def test_refuses_frontmatter_beyond_published_contract_bounds(tmp_path):
    database = make_database(tmp_path)
    made = make_skill(tmp_path, database=database, asset_id="t14-one",
                      revision=1, description="d" * 600)
    store, approvals = made["store"], made["approvals"]
    pin = {"assetId": "t14-one", "revision": 1,
           "treeDigest": store.revision_digest(asset_id="t14-one", revision=1)}
    snap = SkillSnapshot(target_session="s", runtime_generation=1,
                         project_id=None, profile_revision=None,
                         assignment_revisions={}, resolved_skills=(pin,),
                         snapshot_digest="sha256:" + "0" * 64)
    with pytest.raises(SkillDeliveryError) as refused:
        build_skill_delivery(snapshot=snap, store=store, approvals=approvals,
                             harness_id="codex",
                             harness_definition=codex_definition())
    assert refused.value.code == "SKILL_DELIVERY_FRONTMATTER_INVALID"


def test_refuses_managed_set_native_name_collision(tmp_path):
    env = make_env(tmp_path, assets=("coll-a", "coll-b"), name={"coll-a": "dup",
                                                                 "coll-b": "dup"})
    with pytest.raises(NameConflictError) as refused:
        build(env, ("coll-a", 1), ("coll-b", 1))
    assert refused.value.code == "SKILL_NAME_COLLISION"


def test_refuses_collision_with_observed_native_discovery(tmp_path):
    env = make_env(tmp_path, assets=("t14-one",))
    with pytest.raises(NameConflictError) as refused:
        build(env, ("t14-one", 1), observed_native_names=("t14-one",))
    assert refused.value.code == "SKILL_NAME_COLLISION"


def test_refuses_unregistered_brand_unknown_never_supported(tmp_path):
    env = make_env(tmp_path, assets=("t14-one",))
    with pytest.raises(SkillDeliveryError) as refused:
        build(env, ("t14-one", 1), harness_id="gemini-cli")
    assert refused.value.code == "SKILL_DELIVERY_BRAND_UNSUPPORTED"
    # the refusal names the ACTUAL reason (unregistered), not the later
    # pin-cell branch — a mutation that deletes the registry check shifts
    # the message even though the code is shared
    assert "not registered" in refused.value.message


def test_refuses_a_pin_digest_that_is_not_the_stored_tree(tmp_path):
    # isolates the pin-vs-store digest guard: here the store and the
    # approval record AGREE with each other; only the frozen pin lies.
    env = make_env(tmp_path, assets=("t14-one",))
    snap = SkillSnapshot(
        target_session="s-1", runtime_generation=3, project_id=None,
        profile_revision=None, assignment_revisions={},
        resolved_skills=({"assetId": "t14-one", "revision": 1,
                          "treeDigest": "sha256:" + "b" * 64},),
        snapshot_digest="sha256:" + "0" * 64)
    with pytest.raises(SkillDeliveryError) as refused:
        build_skill_delivery(snapshot=snap, store=env.store,
                             approvals=env.approvals, harness_id="codex",
                             harness_definition=codex_definition())
    assert refused.value.code == "SKILL_DELIVERY_DIGEST_MISMATCH"


def test_refuses_observed_version_mismatch(tmp_path):
    env = make_env(tmp_path, assets=("t14-one",))
    with pytest.raises(SkillDeliveryError) as refused:
        build(env, ("t14-one", 1), observed_native_version="9.9.9")
    assert refused.value.code == "SKILL_DELIVERY_BRAND_UNSUPPORTED"


def test_unpinned_brand_only_delivers_on_the_exact_observed_version(tmp_path):
    env = make_env(tmp_path, assets=("t14-one",))
    # claude-code's native pin cell is UNKNOWN (comment-grade evidence):
    # without an observed version the delivery refuses...
    with pytest.raises(SkillDeliveryError):
        build(env, ("t14-one", 1), harness_id="claude-code")
    # ...and with the exact pinned version it is the honest yes.
    delivery = build(env, ("t14-one", 1), harness_id="claude-code",
                     observed_native_version="2.1.274")
    assert len(delivery.items) == 1


def test_registry_limit_is_read_from_the_published_definition(tmp_path):
    env = make_env(tmp_path, assets=("t14-one",))
    definition = codex_definition()
    # the published 0..32 cardinality (registry/schema.py:140 guards it;
    # this test READS it, the producer never hardcodes it)
    assert skill_input_limits(definition) == (0, 32)
    delivery = build(env, ("t14-one", 1), definition=definition)
    assert (delivery.skill_input_minimum, delivery.skill_input_maximum) == \
        (0, 32)


def test_refuses_when_count_exceeds_the_declared_maximum(tmp_path):
    env = make_env(tmp_path, assets=("t14-one", "t14-two"))

    @dataclass
    class Decl:
        contract_id: str
        minimum: int
        maximum: int | None

    @dataclass
    class Prof:
        skill_target: str

    @dataclass
    class Definition:
        inputs: tuple
        profile: Prof
        harness_type: str = "duck"

    cramped = Definition(inputs=(Decl(CONTRACT_ID, 0, 1),),
                        profile=Prof(GUEST_TEMPLATE))
    with pytest.raises(SkillDeliveryError) as refused:
        build(env, ("t14-one", 1), ("t14-two", 1), definition=cramped)
    assert refused.value.code == "SKILL_DELIVERY_LIMIT_EXCEEDED"


def test_refuses_missing_limit_and_undeclared_input_and_target(tmp_path):
    env = make_env(tmp_path, assets=("t14-one",))
    with pytest.raises(SkillDeliveryError) as refused:
        build_skill_delivery(snapshot=snapshot_of(env, ("t14-one", 1)),
                             store=env.store, approvals=env.approvals,
                             harness_id="codex")
    assert refused.value.code == "SKILL_DELIVERY_LIMIT_MISSING"

    @dataclass
    class Definition:
        inputs: tuple
        profile: object
        harness_type: str = "duck"

    no_input = Definition(inputs=(), profile=SimpleNamespace(skill_target=None))
    with pytest.raises(SkillDeliveryError) as refused:
        build(env, ("t14-one", 1), definition=no_input)
    assert refused.value.code == "SKILL_DELIVERY_UNDECLARED"

    @dataclass
    class Decl:
        contract_id: str
        minimum: int
        maximum: int | None

    flat_target = Definition(
        inputs=(Decl(CONTRACT_ID, 0, 32),),
        profile=SimpleNamespace(skill_target="/runtime/home/skills"))
    with pytest.raises(SkillDeliveryError) as refused:
        build(env, ("t14-one", 1), definition=flat_target)
    assert refused.value.code == "SKILL_DELIVERY_UNDECLARED"


def test_refuses_store_root_escape_via_symlink(tmp_path):
    import shutil
    env = make_env(tmp_path, assets=("t14-one",))
    frozen = snapshot_of(env, ("t14-one", 1))   # pinned while real
    outside = tmp_path / "elsewhere"
    directory = env.store.revision_dir("t14-one", 1)
    shutil.move(str(directory), str(outside))
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SkillDeliveryError) as refused:
        build_skill_delivery(snapshot=frozen, store=env.store,
                             approvals=env.approvals, harness_id="codex",
                             harness_definition=codex_definition())
    assert refused.value.code == "SKILL_DELIVERY_PATH_ESCAPE"
    assert (outside / "SKILL.md").is_file()   # the tree lives OUTSIDE the store


def test_refuses_parent_symlink_store_root_escape(tmp_path):
    # the revision directory ITSELF is a real directory; the escape hides
    # in a symlinked parent, so only the containment check can catch it
    import shutil
    env = make_env(tmp_path, assets=("t14-one",))
    frozen = snapshot_of(env, ("t14-one", 1))
    outside = tmp_path / "outside-root"
    asset_dir = Path(env.store.root) / "skill" / "t14-one"
    shutil.move(str(asset_dir), str(outside))
    asset_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SkillDeliveryError) as refused:
        build_skill_delivery(snapshot=frozen, store=env.store,
                             approvals=env.approvals, harness_id="codex",
                             harness_definition=codex_definition())
    assert refused.value.code == "SKILL_DELIVERY_PATH_ESCAPE"


# --------------------------------------------------------------------------
# L1/L2 composition proof on the published fakes
# --------------------------------------------------------------------------

class RecordingProvider:
    """The prepared-source registry the generic assembler requires;
    records exactly what a real Sandbox provider would stage."""

    def __init__(self):
        self.registered: list[tuple[str, Path, str]] = []

    def register_prepared_source(self, token, path, *, authorized_scope):
        self.registered.append((token, Path(path), authorized_scope))


class ProviderSandbox(FakeSandbox):
    def __init__(self, ref, provider):
        super().__init__(ref)
        self.provider = provider


def composition_env(tmp_path, delivery):
    affinity = "local"
    host_ref = RuntimeHostRef("fake", "host-1", digest("host-1"), affinity)
    sandbox_ref = SandboxRef("fake", "sandbox-1", digest("sandbox-1"), affinity)
    terminal_ref = TerminalSessionRef("fake", "term-1", digest("term-1"),
                                      affinity)
    sentinel = FakeHostSentinel()
    host = FakeHost(host_ref, sentinel)
    provider = RecordingProvider()
    sandbox = ProviderSandbox(sandbox_ref, provider)
    terminal = FakeTerminal(terminal_ref, host)
    inputs = [
        SimpleNamespace(contract_id=RuntimeHostV1.contract_id,
                        value=RuntimeHostV1(host_ref, host)),
        SimpleNamespace(contract_id=SandboxV1.contract_id,
                        value=SandboxV1(sandbox_ref, sandbox)),
        SimpleNamespace(contract_id=TerminalSessionV1.contract_id,
                        value=TerminalSessionV1(terminal_ref, terminal)),
        *delivery.items,
    ]
    request = SimpleNamespace(resolved_inputs=tuple(inputs))
    first = delivery.items[0].value.contract.skill_id
    command = HarnessCommandSpec(
        argv=("codex",), cwd_token=GUEST_TEMPLATE.format(skill_id=first),
        runtime_sources=delivery.runtime_sources(skill_target=GUEST_TEMPLATE),
        projector_id="skills-t14")
    return host, sentinel, provider, request, command


class FakeHostSentinel:
    def __init__(self):
        self.count = 0


def test_composition_projects_every_skill_read_only_at_its_guest_target(tmp_path):
    env = make_env(tmp_path)
    delivery = build(env, ("t14-one", 1), ("t14-two", 1))
    _, sentinel, provider, request, command = composition_env(tmp_path, delivery)

    runtime_present_before = Path("/runtime").exists()

    binding, coordinator = assemble_runtime_composition(request, command)
    preflight = coordinator.preflight(binding)
    assert preflight.accepted is True

    handle = coordinator.start(binding, command, execution_id="exec-t14",
                               dispatch_id="dispatch-1")
    receipt = coordinator.projection_receipt(handle.attempt_key)

    # THE evidence level: a digest-matched projection receipt proves
    # `projected` and NOTHING stronger (contracts.md 证据阶梯, G16).
    assert receipt["status"] == "PROJECTED"
    assert attest(PROJECTED, proofs=("projection_digest",)) == PROJECTED
    assert attest(LOADED, proofs=("projection_digest",)) == "unknown"
    assert attest(USED, proofs=("projection_digest",)) == "unknown"

    sources = {row["guest_target"]: row for row in receipt["sources"]}
    for item in delivery.items:
        contract = item.value.contract
        target = GUEST_TEMPLATE.format(skill_id=contract.skill_id)
        assert target in sources
        row = sources[target]
        assert row["access"] == "ro"          # read-only mount, as declared
        assert row["kind"] == "skill-tree"
        assert row["provenance"] == f"skill:{contract.skill_id}:{contract.revision}"
        directory = item.value.source.projection_source()
        assert row["expected_digest"] == content_digest(directory)
    # the provider staged exactly the delivered trees, all under tmp_path
    assert len(provider.registered) == len(delivery.items)
    for _token, path, scope in provider.registered:
        assert str(path).startswith(str(tmp_path))
        assert scope == "execution"
    # one submission through the fake transport; attempt RUNNING
    assert sentinel.count == 1
    assert coordinator.ledger[handle.attempt_key].state == "RUNNING"
    # guest paths exist ONLY in the fake's records — nothing was created
    # on the host filesystem, nothing was written outside the tmp roots
    assert not any(Path(row["guest_target"]).exists()
                   for row in receipt["sources"])
    assert Path("/runtime").exists() is runtime_present_before


def test_refused_preflight_leaves_the_composition_untouched(tmp_path):
    env = make_env(tmp_path)
    good = build(env, ("t14-one", 1), ("t14-two", 1))
    _, sentinel, provider, _request, _command = composition_env(tmp_path, good)

    # the producer-side refusal: after drift the SECOND build raises and
    # hands out zero delivery objects (no partial set escapes).
    frozen = snapshot_of(env, ("t14-one", 1), ("t14-two", 1))
    (env.store.revision_dir("t14-two", 1) / "late.md").write_text(
        "drift\n", encoding="utf-8")
    with pytest.raises(SkillDeliveryError):
        build_skill_delivery(snapshot=frozen, store=env.store,
                             approvals=env.approvals, harness_id="codex",
                             harness_definition=codex_definition())
    assert provider.registered == []
    assert sentinel.count == 0

    # even if a stale declaration slipped past Q1, the assembler's own
    # pre-start validation refuses before ANY attempt: zero registrations
    # added, zero submissions.
    from pacthold_runtime_compat.runtime_composition import (
        RuntimeSourceDeclaration,
    )
    stale = RuntimeSourceDeclaration(
        kind="skill-tree",
        source_path=str(env.store.revision_dir("t14-one", 1)),
        guest_target=GUEST_TEMPLATE.format(skill_id="t14-one"),
        access="ro", expected_digest="sha256:" + "e" * 64,
        provenance="skill:t14-one:1")
    command = HarnessCommandSpec(
        argv=("codex",), cwd_token=GUEST_TEMPLATE.format(skill_id="t14-one"),
        runtime_sources=(stale,), projector_id="skills-t14")
    drifted = SimpleNamespace(
        resolved_inputs=_request.resolved_inputs[:3])
    with pytest.raises(ValueError, match="digest drift"):
        assemble_runtime_composition(drifted, command)
    assert provider.registered == []
    assert sentinel.count == 0
