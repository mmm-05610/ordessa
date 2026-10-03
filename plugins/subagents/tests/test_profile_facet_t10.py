"""T10 — Profile facet/editor + next-submission effective set (G16).

Every test binds the *real* Profile v2 surface (``ordessa_profile`` — the
published Z1 seam) against this domain's ``profile_facet`` module; nothing
here imitates Z1's types (constitution IV: controlled fixtures are labelled
as such and never claim a real brand).

Coverage map (tasks.md T10 / contracts.md §C1 §C2 / verification.md row 16):

* facet descriptor, host-injected ownership ................ :func:`test_facet_descriptor_carries_references_and_readonly_diagnostics`, :func:`test_owner_is_host_injected_never_self_declared`
* effective set single-sourced (no substitution) ........... :func:`test_compile_refuses_a_smuggled_effective_set`, :func:`test_build_submission_refuses_a_caller_computed_set`, :func:`test_compile_follows_the_resolver_not_the_stored_choice`
* G16 positive (next submission, pins) ..................... :func:`test_build_submission_pins_revisions_and_generations`, :func:`test_mid_output_choice_change_leaves_the_inflight_snapshot`
* G16 negatives .............................................. :func:`test_choice_change_never_touches_the_application_port`, :func:`test_failed_apply_keeps_previous_coverage_and_pins`, :func:`test_unknown_apply_stays_queryable_and_never_success`
* unload hides, never deletes .............................. :func:`test_unload_hides_and_relaying_keeps_stored_bytes_identical`
* session overlay follows Profile v2 ....................... :func:`test_confirmed_overlay_cleanup_is_evidenced_by_receipt_and_journal`, :func:`test_absent_port_yields_their_typed_blocked_outcome_never_permissive`
* unknown-brand honesty .................................... :func:`test_default_capability_matrix_is_honest_for_every_pinned_brand`, :func:`test_facet_registrable_candidates_visible_apply_refused`
* fail-closed unknown fragments ............................ :func:`test_unknown_schema_fragment_is_quarantined_kept_and_refused`

Evidence level: L1 (pure + real-seam unit).  The end-to-end send gating at a
real Harness apply path stays blocked on C0 integration (SR-2/SR-3b) and is
not claimed here.
"""
from __future__ import annotations

import json

import pytest

from ordessa_profile import ProfileCore, ProfileError, StaticHarnessCatalog
from ordessa_profile import contracts as z1
from ordessa_profile.plugin import ProfilePluginServices

from ordessa_assets_subagents import ceiling as ceiling_mod
from ordessa_assets_subagents import dto, errors, profile_facet, resolution
from ordessa_assets_subagents.assignments import Assignment, AssignmentDecision
from ordessa_assets_subagents.references import ReferenceResolution
from ordessa_assets_subagents.resolution import (
    EffectiveSet,
    ResolvedDefinition,
    ResolutionRequest,
    build_snapshot,
    resolve_preview,
)
from ordessa_assets_subagents.scopes import (
    DefinitionOwnership,
    Principal,
    ScopeKind,
    ServerScope,
)

FACET = profile_facet.FACET_ID
OWNER = "assets.subagents"  # host-granted plugin id (contracts.md §C3)

U1 = Principal("u1")
SCOPE = ServerScope("s1")
DIGEST_D1 = "sha256:" + "a" * 64
DIGEST_D2 = "sha256:" + "b" * 64

APPROVED = {("d1", 1), ("d1", 2), ("d2", 1)}


class Approvals:
    def has_approved_revision(self, definition_id: str, revision: int) -> bool:
        return (definition_id, revision) in APPROVED


CAND_D1 = profile_facet.CandidateDefinition(
    definition_id="d1", slug="code-reviewer", display_name="Code reviewer",
    latest_revision=2, managed=True, approved_revisions=frozenset({1, 2}))
CAND_D2 = profile_facet.CandidateDefinition(
    definition_id="d2", slug="researcher", display_name="Researcher",
    latest_revision=1, managed=True, approved_revisions=frozenset({1}))
CAND_NATIVE = profile_facet.CandidateDefinition(
    definition_id="nat1", slug="native-found", display_name="Native found",
    latest_revision=1, managed=False)

API = profile_facet.ProfileV2Api.from_contracts(z1)

SUPPORTED_FIXTURE = profile_facet.BrandCapability(
    brand="fixture-brand", status=profile_facet.STATUS_SUPPORTED,
    evidence=("controlled-fixture: T10 apply-path test harness only — not a "
              "real brand claim (capability-matrix.md has no supported cell)",))


# --------------------------------------------------------------------------
# resolver wiring (the facet's effective set is OUR resolver, single source)
# --------------------------------------------------------------------------


def _definition(definition_id: str, slug: str) -> dto.AgentDefinition:
    return dto.AgentDefinition(
        server_scope="s1", definition_id=definition_id, slug=slug,
        display_name=slug, description="", origin_scope="public",
        origin_owner="u1", latest_revision=2,
    )


def _revision(definition_id: str, revision: int, digest: str) -> dto.DefinitionRevision:
    return dto.DefinitionRevision(definition_id=definition_id, revision=revision,
                                  content_digest=digest, role_body="body")


def _assignment(definition_id: str, revision: int,
                row_version: int = 1) -> Assignment:
    return Assignment(
        server_scope=SCOPE, principal=U1, scope_kind=ScopeKind.USER_GLOBAL,
        scope_id=None, harness_id="any", definition_id=definition_id,
        decision=AssignmentDecision.ENABLE, revision=revision,
        row_version=row_version,
    )


def make_request(*, assignments=None, **overrides) -> ResolutionRequest:
    base = dict(
        server_scope=SCOPE, principal=U1, harness_id="claude",
        project_id=None, profile_id=None, session_id=None,
        session_profile_id=None, session_harness_id=None,
        definitions={"d1": _definition("d1", "code-reviewer"),
                     "d2": _definition("d2", "researcher")},
        ownership={"d1": DefinitionOwnership("d1", SCOPE, U1, "public", "u1"),
                   "d2": DefinitionOwnership("d2", SCOPE, U1, "public", "u1")},
        revisions={("d1", 1): _revision("d1", 1, DIGEST_D1),
                   ("d1", 2): _revision("d1", 2, DIGEST_D1),
                   ("d2", 1): _revision("d2", 1, DIGEST_D2)},
        assignments=[_assignment("d1", 1)],
        managed_definition_ids=frozenset({"d1", "d2"}),
        native_observations=None,
        ceiling=ceiling_mod.Ceiling(principal=U1, server_scope=SCOPE,
                                    harness_id="claude"),
    )
    if assignments is not None:
        base["assignments"] = list(assignments)
    base.update(overrides)
    return ResolutionRequest(**base)


def make_facet(*, request=None, capabilities=None, candidates=(CAND_D1, CAND_D2, CAND_NATIVE),
               schema_version=profile_facet.CHOICE_SCHEMA_VERSION,
               resolver=None):
    """Build the facet with its effective-set read bound to resolve_preview."""
    req = request if request is not None else make_request()
    approvals = Approvals()
    if resolver is None:
        def resolver():
            return resolve_preview(req, approvals=approvals)
    facet = profile_facet.NativeSubagentsFacet(
        API, candidates=lambda: tuple(candidates), approvals=approvals,
        resolve_effective=resolver, capabilities=capabilities,
        schema_version=schema_version)
    return facet, req, approvals


def enable_choice(revision: int = 1) -> dict:
    return profile_facet.encode_choice(AssignmentDecision.ENABLE, revision)


# --------------------------------------------------------------------------
# Z1 test doubles for this lane (controlled fixtures, labelled as such)
# --------------------------------------------------------------------------


class FixturePort:
    """Controlled HarnessConfigPort double over the real contract types.

    Mirrors the vocabulary of Profile's own scripted port: counters prove
    which flows never touch the seam; every receipt is explicitly labelled
    ``controlled-fixture`` evidence.
    """

    def __init__(self, *, apply_verdict: str = "confirmed") -> None:
        self.apply_verdict = apply_verdict
        self.counters = {"inspect": 0, "plan": 0, "apply": 0, "restart": 0,
                         "reconcile": 0}
        self.applied: list[tuple] = []

    def inspect(self, target):
        self.counters["inspect"] += 1
        return z1.InspectResult(
            target=z1.HarnessTargetFacts(session_ref=target,
                                         runtime_generation="fixture-gen-1"),
            evidence_kind="controlled-fixture",
            current_config_digest="sha256:fixture-current")

    def plan(self, target, desired, operation_key):
        self.counters["plan"] += 1
        return z1.PlanResult(
            session_ref=target, operation_key=operation_key,
            overall="live-update",
            items=tuple(z1.PlannedItem(facet_id=i.facet_id, item_id=i.item_id,
                                       op=i.op, status="live-update")
                        for i in desired),
            plan_digest=f"sha256:plan-{self.counters['plan']}",
            fence={"runtime_generation": "fixture-gen-1"})

    def apply(self, plan, desired):
        self.counters["apply"] += 1
        self.applied.append(tuple(desired))
        receipt = z1.AppliedReceipt(
            operation_id=plan.operation_key.split(":")[-1],
            session_ref=plan.session_ref,
            runtime_generation="fixture-gen-1",
            config_digest=f"sha256:apply-{len(self.applied)}",
            profile_id="fixture", profile_revision=1, overlay_revision=None,
            policy_revision=1, provider_generations={},
            evidence_kind="controlled-fixture",
            confirmed_at="2026-09-28T00:00:00+00:00",
            execution_id="fixture-exec")
        if self.apply_verdict == "confirmed":
            return z1.ApplyConfirmed(state="confirmed", receipt=receipt)
        if self.apply_verdict == "rejected":
            return z1.ApplyRejected(
                state="rejected-unchanged", reason="fixture rejection",
                items=tuple(z1.PlannedItem(facet_id=i.facet_id,
                                           item_id=i.item_id, op=i.op,
                                           status="blocked",
                                           reason="fixture rejection")
                            for i in desired))
        return z1.ApplyUnknown(state="unknown", reason="fixture unknown")

    def reconcile(self, operation_key, target):
        self.counters["reconcile"] += 1
        return z1.ReconcileOutcome(state="unknown", reason="not scripted")


HARNESSES = {
    "claude": frozenset(), "codex": frozenset(), "pi": frozenset(),
    "fixture-brand": frozenset(),
}


def make_core(tmp_path, *, port=None):
    return ProfileCore(
        tmp_path / "profile-store.sqlite",
        harnesses=StaticHarnessCatalog(HARNESSES),
        config_port=port,
    )


def register(core, facet, *, owner=OWNER):
    services = ProfilePluginServices(core)
    return services.register_v2_facet(facet, owner)


def create_profile(core, key, harness_id, name):
    return core.profiles.create(key, harness_id=harness_id, display_name=name)


# ==========================================================================
# 1. facet descriptor (references + tri-state + pin + read-only diagnostics)
# ==========================================================================


def test_facet_descriptor_carries_references_and_readonly_diagnostics():
    facet, _, _ = make_facet(capabilities=profile_facet.default_capability_matrix())
    descriptor = facet.descriptor()
    assert descriptor.facet_id == "assets.native-subagents"
    assert descriptor.api_major == 2
    assert descriptor.schema_version == "1.0.0"
    assert descriptor.category == "capabilities"
    diagnostics = descriptor.item(profile_facet.DIAGNOSTICS_ITEM_ID)
    assert diagnostics is not None
    # read-only: the Z1 vocabulary for "editor may not patch this"
    assert diagnostics.override_supported is False
    assert diagnostics.effect == "capability-selection"
    for candidate in (CAND_D1, CAND_D2, CAND_NATIVE):
        item = descriptor.item(profile_facet.choice_item_id(candidate.definition_id))
        assert item is not None, "candidate definition reference missing"
        assert item.effect == "capability-selection"
        # the item title may name the definition; the VALUE never carries
        # the body — only decision + pinned revision (§C2)
        assert item.title == candidate.display_name
    # no self-declared ownership on the provider (host grants it)
    assert not hasattr(facet, "owner_plugin_id")


def test_descriptor_value_shape_holds_reference_choice_pin_only():
    value = enable_choice(2)
    assert set(value) == {"provider", "schema_version", "decision", "revision"}
    assert value["decision"] == "enable" and value["revision"] == 2
    json.dumps(value)  # Profile stores exactly these bytes
    with pytest.raises(errors.DomainError):
        profile_facet.encode_choice(AssignmentDecision.ENABLE, None)
    with pytest.raises(errors.DomainError):
        profile_facet.encode_choice(AssignmentDecision.DISABLE, 3)
    with pytest.raises(errors.DomainError):
        profile_facet.decode_choice({"provider": "someone.else",
                                     "schema_version": "1.0.0",
                                     "decision": "enable", "revision": 1})


def test_owner_is_host_injected_never_self_declared(tmp_path):
    core = make_core(tmp_path)
    facet, _, _ = make_facet()
    with pytest.raises(ProfileError) as exc:
        core.register_v2_provider(facet, owner_plugin_id="")
    assert exc.value.code == "FACET_INVALID_PROVIDER"
    register(core, facet)
    assert core.registry.owner_of(FACET) == OWNER
    # the facet id may be claimed by exactly one owner (no last-wins)
    impostor, _, _ = make_facet()
    with pytest.raises(ProfileError) as conflict:
        register(core, impostor, owner="another.plugin")
    assert conflict.value.code == "FACET_ID_CONFLICT"


def test_missing_profile_surface_is_typed_absence_not_lookalike():
    class Partial:  # a seam that lost a symbol
        FacetDescriptor = object

    with pytest.raises(errors.DomainError) as exc:
        profile_facet.ProfileV2Api.from_contracts(Partial())
    assert exc.value.code == errors.ADAPTER_MISSING


# ==========================================================================
# 2. effective set is the resolver's — substitution is refused
# ==========================================================================


def _fake_effective(definition_id="d2", revision=1):
    row = ResolvedDefinition(
        definition_id=definition_id, revision=revision,
        native_name=definition_id, selected_by=ScopeKind.USER_GLOBAL,
        effective_references=ReferenceResolution(references=(), diagnostics=()),
        capability_evidence=(), diagnostics=())
    return EffectiveSet(resolved=(row,), excluded=())


def test_compile_refuses_a_smuggled_effective_set():
    facet, _, _ = make_facet(
        capabilities={"fixture-brand": SUPPORTED_FIXTURE})
    result = facet.compile(
        {profile_facet.choice_item_id("d1"): enable_choice(1)},
        {"harness_id": "fixture-brand", "effective_set": _fake_effective("d2")})
    assert result.intents == ()
    assert [v.code for v in result.violations] == [profile_facet.VIOLATION_SUBSTITUTION]
    # the smuggled object is not merely ignored — nothing at all compiles
    assert not any(v.item_id == profile_facet.choice_item_id("d2")
                   for v in result.violations)


def test_build_submission_refuses_a_caller_computed_set():
    facet, req, approvals = make_facet(
        capabilities={"fixture-brand": SUPPORTED_FIXTURE})
    with pytest.raises(errors.DomainError) as exc:
        profile_facet.build_submission(
            facet, req, approvals=approvals, runtime_generation="g1",
            profile_revision=1, adapter_generation="a1",
            effective_set=_fake_effective("d2"))
    assert exc.value.code == errors.DEFINITION_INVALID
    # and the legitimate path still produces exactly the resolver's truth
    snapshot = profile_facet.build_submission(
        facet, req, approvals=approvals, runtime_generation="g1",
        profile_revision=1, adapter_generation="a1")
    assert snapshot.definition_digests == (("d1", 1, DIGEST_D1),)


def test_compile_follows_the_resolver_not_the_stored_choice():
    """A stored choice the resolver does not admit compiles NO intent."""
    facet, _, _ = make_facet(
        capabilities={"fixture-brand": SUPPORTED_FIXTURE})
    # resolver (request) admits d1@1; the Profile choice asks for d2@1
    result = facet.compile(
        {profile_facet.choice_item_id("d2"): enable_choice(1)},
        {"harness_id": "fixture-brand"})
    assert result.intents == ()
    assert [v.code for v in result.violations] == [profile_facet.VIOLATION_NOT_ADMITTED]


def test_compile_fails_closed_when_the_resolver_refuses():
    # approved pin whose revision row is gone: REVISION_STALE before any intent
    stale = make_request(
        assignments=[_assignment("d1", 2)],
        revisions={("d1", 1): _revision("d1", 1, DIGEST_D1)})
    facet, _, _ = make_facet(
        request=stale, capabilities={"fixture-brand": SUPPORTED_FIXTURE})
    result = facet.compile(
        {profile_facet.choice_item_id("d1"): enable_choice(1)},
        {"harness_id": "fixture-brand"})
    assert result.intents == ()
    assert result.violations[0].code == profile_facet.VIOLATION_NOT_ADMITTED
    assert errors.REVISION_STALE in result.violations[0].message


def test_validate_tristate_semantics():
    facet, _, _ = make_facet(capabilities=profile_facet.default_capability_matrix())
    ok = facet.validate({profile_facet.choice_item_id("d1"): enable_choice(2)}, {})
    assert ok == ()
    bad_pin = facet.validate({profile_facet.choice_item_id("d1"): enable_choice(3)}, {})
    assert bad_pin and bad_pin[0].code == profile_facet.VIOLATION_VALUE_INVALID
    native_disable = facet.validate(
        {profile_facet.choice_item_id("nat1"):
             profile_facet.encode_choice(AssignmentDecision.DISABLE)}, {})
    assert native_disable[0].code == errors.NATIVE_DISCOVERY_UNCONTROLLED
    inherited = facet.validate(
        {profile_facet.choice_item_id("d1"):
             profile_facet.encode_choice(AssignmentDecision.INHERIT)}, {})
    assert inherited == ()
    unknown_item = facet.validate({"some-other-item": enable_choice(1)}, {})
    assert unknown_item and unknown_item[0].code == profile_facet.VIOLATION_VALUE_INVALID
    diagnostics = facet.validate(
        {profile_facet.DIAGNOSTICS_ITEM_ID: []}, {})
    assert diagnostics[0].code == profile_facet.VIOLATION_VALUE_INVALID
    assert "read-only" in diagnostics[0].message


# ==========================================================================
# 3./4. next-submission snapshot and G16 negatives (pure part)
# ==========================================================================


def test_build_submission_pins_revisions_and_generations():
    facet, req, approvals = make_facet()
    snapshot = profile_facet.build_submission(
        facet, req, approvals=approvals, runtime_generation="gen-77",
        profile_revision=3, adapter_generation="adapter-5")
    assert snapshot.definition_digests == (("d1", 1, DIGEST_D1),)
    assert snapshot.assignment_revisions == (("user_global::d1", 1),)
    assert snapshot.runtime_generation == "gen-77"
    assert snapshot.adapter_generation == "adapter-5"
    assert snapshot.profile_revision == 3
    again = profile_facet.build_submission(
        facet, req, approvals=approvals, runtime_generation="gen-77",
        profile_revision=3, adapter_generation="adapter-5")
    assert again.snapshot_digest == snapshot.snapshot_digest  # deterministic


def test_mid_output_choice_change_leaves_the_inflight_snapshot():
    """The snapshot a submission froze is that submission's, forever."""
    facet1, req1, approvals = make_facet()
    in_flight = profile_facet.build_submission(
        facet1, req1, approvals=approvals, runtime_generation="gen-A",
        profile_revision=1, adapter_generation="adapter-A")
    # user changes the choice mid-output: enable moves to revision 2, the
    # assignment row bumps — none of this may reach the in-flight snapshot
    req2 = make_request(assignments=[_assignment("d1", 2, row_version=2)])
    facet2, _, _ = make_facet(request=req2)
    next_up = profile_facet.build_submission(
        facet2, req2, approvals=approvals, runtime_generation="gen-B",
        profile_revision=2, adapter_generation="adapter-B")
    assert in_flight.definition_digests == (("d1", 1, DIGEST_D1),)
    assert in_flight.assignment_revisions == (("user_global::d1", 1),)
    assert in_flight.snapshot_digest != next_up.snapshot_digest
    assert next_up.definition_digests == (("d1", 2, DIGEST_D1),)
    # the in-flight digest is stable under re-derivation from its own facts
    resolved = resolve_preview(req1, approvals=approvals)
    rebuilt = build_snapshot(req1, resolved, approvals=approvals,
                             runtime_generation="gen-A", profile_revision=1,
                             adapter_generation="adapter-A")
    assert rebuilt.snapshot_digest == in_flight.snapshot_digest


def test_apply_outcome_projection_honest_states():
    receipt = {"operation_id": "op-1", "config_digest": "sha256:cfg",
               "evidence_kind": "port-confirmed"}
    legacy = {**receipt, "evidence_kind": "legacy-unverified"}
    assert profile_facet.apply_outcome_projection(
        journal_entry={"state": "confirmed"}, receipt=receipt)["success"] is True
    for state, expected_success in (("planned", False), ("applying", False),
                                    ("rejected", False), ("unknown", False)):
        projection = profile_facet.apply_outcome_projection(
            journal_entry={"state": state}, receipt=receipt)
        assert projection["success"] is expected_success, state
        assert projection["queryable"] is True, state
    unknown = profile_facet.apply_outcome_projection(
        journal_entry={"state": "unknown"}, receipt=None)
    assert unknown["success"] is False and unknown["queryable"] is True
    # confirmed WITHOUT a receipt proves nothing
    assert profile_facet.apply_outcome_projection(
        journal_entry={"state": "confirmed"}, receipt=None)["success"] is False
    # legacy-unverified can never be upgraded (PV-04)
    assert profile_facet.apply_outcome_projection(
        journal_entry={"state": "confirmed"}, receipt=legacy)["success"] is False


def test_overlay_cleanup_requires_confirmed_evidence():
    receipt = {"operation_id": "op-9", "config_digest": "sha256:x",
               "evidence_kind": "controlled-fixture"}
    assert profile_facet.overlay_cleanup_evidence(
        journal_entry={"state": "confirmed"}, receipt=receipt)["cleaned"] is True
    assert profile_facet.overlay_cleanup_evidence(
        journal_entry={"state": "unknown"}, receipt=receipt)["cleaned"] is False
    assert profile_facet.overlay_cleanup_evidence(
        journal_entry={"state": "confirmed"}, receipt=None)["cleaned"] is False
    assert profile_facet.overlay_cleanup_evidence(
        journal_entry=None, receipt=None)["cleaned"] is False


# ==========================================================================
# 5./7. capability honesty (pure part)
# ==========================================================================


def test_default_capability_matrix_is_honest_for_every_pinned_brand():
    matrix = profile_facet.default_capability_matrix()
    assert matrix["claude"].status == profile_facet.STATUS_UNKNOWN
    assert matrix["codex"].status == profile_facet.STATUS_UNSUPPORTED
    assert matrix["pi"].status == profile_facet.STATUS_UNSUPPORTED
    for cell in matrix.values():
        assert cell.evidence  # every verdict names its source
        assert all("capability-matrix" in entry or "pi-extension-audit" in entry
                   or "contracts" in entry for entry in cell.evidence)
    facet, _, _ = make_facet(capabilities=matrix)
    assert facet.applicability({"harness_id": "claude"}) is z1.Applicability.UNKNOWN
    assert facet.applicability({"harness_id": "codex"}) is z1.Applicability.UNSUPPORTED
    assert facet.applicability({"harness_id": "pi"}) is z1.Applicability.UNSUPPORTED
    # an unknown brand never promotes (no fact, no evidence ⇒ no claim)
    assert facet.applicability({"harness_id": "who-knows"}) is z1.Applicability.UNKNOWN
    assert facet.applicability({}) is z1.Applicability.UNKNOWN
    empty = facet.compile({profile_facet.choice_item_id("d1"): enable_choice(1)},
                          {"harness_id": "claude"})
    assert empty.intents == ()  # apply refused without supported evidence
    assert empty.violations[0].code == profile_facet.VIOLATION_APPLY_REFUSED


def test_supported_status_requires_evidence():
    with pytest.raises(errors.DomainError):
        profile_facet.BrandCapability(brand="x", status="supported", evidence=())


# ==========================================================================
# core integration: storage, projection, unload
# ==========================================================================


def test_choice_saves_are_desired_only_and_never_touch_the_port(tmp_path):
    port = FixturePort()
    core = make_core(tmp_path, port=port)
    facet, _, _ = make_facet(capabilities=profile_facet.default_capability_matrix())
    register(core, facet)
    profile = create_profile(core, "k1", "claude", "Work")
    updated = core.profiles.set_facet_values(
        "k2", profile_id=profile["profile_id"], expected_version=1,
        values=[{"facet_id": FACET,
                 "item_id": profile_facet.choice_item_id("d1"),
                 "value": enable_choice(1)}])
    assert updated["current_revision"] == 2
    core.sessions.open_session("ks", session_id="S", harness_id="claude",
                               profile_id=profile["profile_id"])
    ticket = core.sessions.begin_turn("t0", session_id="S")
    # a turn on the CURRENT configuration records and applies nothing
    assert ticket["applied_switch"] is False
    assert port.counters == {"inspect": 0, "plan": 0, "apply": 0,
                             "restart": 0, "reconcile": 0}
    # unknown applicability still BLOCKS a switch (save ≠ load)
    other = create_profile(core, "k3", "claude", "Other")
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=other["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SWITCH_BLOCKED"
    assert {"facet_id": FACET,
            "item_id": profile_facet.choice_item_id("d1"),
            "reason": "facet_applicability_unknown"} in exc.value.blockers
    # and selecting/turning never invoked the port either way
    assert port.counters["plan"] == 0 and port.counters["apply"] == 0


def test_unsupported_brand_refuses_even_the_save(tmp_path):
    core = make_core(tmp_path)
    facet, _, _ = make_facet(capabilities=profile_facet.default_capability_matrix())
    register(core, facet)
    codex_profile = create_profile(core, "k1", "codex", "Codex preset")
    with pytest.raises(ProfileError) as exc:
        core.profiles.set_facet_values(
            "k2", profile_id=codex_profile["profile_id"], expected_version=1,
            values=[{"facet_id": FACET,
                     "item_id": profile_facet.choice_item_id("d1"),
                     "value": enable_choice(1)}])
    assert exc.value.code == "FACET_NOT_APPLICABLE"


def test_describe_facets_exposes_candidates_and_readonly_diagnostics(tmp_path):
    core = make_core(tmp_path)
    facet, _, _ = make_facet(capabilities=profile_facet.default_capability_matrix())
    register(core, facet)
    entries = core.describe_facets("claude")
    entry = next(e for e in entries if e["facet_id"] == FACET)
    assert entry["owner_plugin_id"] == OWNER
    assert entry["applicability"] == "unknown"
    assert entry["category"] == "capabilities"
    diagnostics = next(i for i in entry["items"]
                       if i["item_id"] == profile_facet.DIAGNOSTICS_ITEM_ID)
    assert diagnostics["override_supported"] is False
    assert profile_facet.choice_item_id("d1") in {i["item_id"] for i in entry["items"]}
    # a foreign brand with no fact still renders, applicability honestly unknown
    entry_pi = next(e for e in core.describe_facets("pi") if e["facet_id"] == FACET)
    assert entry_pi["applicability"] == "unsupported"


def test_unload_hides_and_relaying_keeps_stored_bytes_identical(tmp_path):
    core = make_core(tmp_path)
    facet, _, _ = make_facet(capabilities=profile_facet.default_capability_matrix())
    register(core, facet)
    profile = create_profile(core, "k1", "claude", "Work")
    value = enable_choice(1)
    core.profiles.set_facet_values(
        "k2", profile_id=profile["profile_id"], expected_version=1,
        values=[{"facet_id": FACET,
                 "item_id": profile_facet.choice_item_id("d1"), "value": value}])
    before = core.profiles.facet_values(profile["profile_id"])
    ours = [v for v in before if v["facet_id"] == FACET]
    assert len(ours) == 1

    services = ProfilePluginServices(core)
    services.unregister_facet(facet)
    # hidden from the catalog, never applied, never deleted
    assert [e for e in core.describe_facets("claude") if e["facet_id"] == FACET] == []
    during = [v for v in core.profiles.facet_values(profile["profile_id"])
              if v["facet_id"] == FACET]
    assert during == ours  # bytes-unchanged while absent
    preview = core.profiles.resolution_preview(profile["profile_id"])
    assert {"facet_id": FACET, "item_id": profile_facet.choice_item_id("d1"),
            "reason": "provider_absent"} in preview["unavailable"]
    assert all(i["facet_id"] != FACET for i in preview["items"])

    register(core, facet)  # re-registering restores the SAME data
    after = [v for v in core.profiles.facet_values(profile["profile_id"])
             if v["facet_id"] == FACET]
    assert after == ours  # incl. updated_at: the row was never rewritten
    restored = core.profiles.resolution_preview(profile["profile_id"])
    assert restored["items"][0]["value"] == value


def test_editor_projection_is_references_only_with_readonly_diagnostics():
    facet, _, _ = make_facet(capabilities=profile_facet.default_capability_matrix())
    projection = profile_facet.editor_projection(
        facet,
        stored_items={profile_facet.choice_item_id("d1"): enable_choice(1),
                      profile_facet.choice_item_id("d2"):
                          {"provider": FACET, "schema_version": "9",
                           "decision": "enable", "revision": 1}},
        harness_id="claude")
    assert projection["applicability"] == "unknown"
    body = json.dumps(projection)
    assert "body" not in body  # no definition text ever reaches the facet read
    refs = {item["definition_ref"] for item in projection["items"]}
    assert {"d1", "d2", "nat1"} <= refs
    for cell in projection["capabilityDiagnostics"]:
        assert cell["status"] in ("supported", "unsupported", "unknown")
        assert cell["evidence"] and cell["readOnlyReason"]
    entry = next(i for i in projection["items"] if i["definition_ref"] == "d2")
    assert entry["uncompilable_fragment"] is not None  # kept, honestly refused
    assert projection["effectiveSet"]["resolved"] == [
        {"definition_id": "d1", "revision": 1, "selected_by": "user_global"}]


def test_editor_projection_survives_a_refusing_resolver():
    stale = make_request(
        assignments=[_assignment("d1", 2)],
        revisions={("d1", 1): _revision("d1", 1, DIGEST_D1)})
    facet, _, _ = make_facet(request=stale)
    projection = profile_facet.editor_projection(facet, harness_id="claude")
    assert projection["effectiveSet"].get("unavailable") is True
    assert projection["effectiveSet"]["code"] == errors.REVISION_STALE


# ==========================================================================
# 8. unknown stored fragments: kept, never compiled (real reload)
# ==========================================================================


def test_unknown_schema_fragment_is_quarantined_kept_and_refused(tmp_path):
    core = make_core(tmp_path)
    facet, _, _ = make_facet(capabilities=profile_facet.default_capability_matrix())
    register(core, facet)
    profile = create_profile(core, "k1", "claude", "Work")
    value = enable_choice(1)
    item_id = profile_facet.choice_item_id("d1")
    core.profiles.set_facet_values(
        "k2", profile_id=profile["profile_id"], expected_version=1,
        values=[{"facet_id": FACET, "item_id": item_id, "value": value}])
    services = ProfilePluginServices(core)
    services.unregister_facet(facet)
    # the SAME facet id re-registers with a newer schema version: the stored
    # fragment (schema 1.0.0) is a version this provider cannot compile
    bumped, _, _ = make_facet(schema_version="2.0.0")
    report = register(core, bumped)
    assert report.quarantined == 1
    stored = [v for v in core.profiles.facet_values(profile["profile_id"])
              if v["facet_id"] == FACET]
    assert stored[0]["value"] == value          # data kept
    assert stored[0]["quarantined"] is True      # ... and flagged
    preview = core.profiles.resolution_preview(profile["profile_id"])
    assert {"facet_id": FACET, "item_id": item_id,
            "reason": "value_quarantined"} in preview["unavailable"]
    assert all(i["facet_id"] != FACET for i in preview["items"])
    # pure side: a well-formed fragment of ANOTHER provider is also refused,
    # never rewritten (fail-closed, §C2)
    ruling = bumped.migrate("2.0.0", {
        profile_facet.choice_item_id("d1"): {
            "provider": "some.other.domain", "schema_version": "2.0.0",
            "decision": "enable", "revision": 1}})
    assert isinstance(ruling, z1.MigrationUnsupported)
    clean = bumped.migrate("2.0.0", {item_id: enable_choice(1)})
    assert isinstance(clean, z1.MigratedItems) and clean.items == ()


# ==========================================================================
# 6. session overlay follows Profile v2 (real receipts/journal/port)
# ==========================================================================


def supported_facet(**kw):
    return make_facet(capabilities={"fixture-brand": SUPPORTED_FIXTURE}, **kw)


def test_confirmed_overlay_cleanup_is_evidenced_by_receipt_and_journal(tmp_path):
    port = FixturePort()
    core = make_core(tmp_path, port=port)
    facet, _, _ = supported_facet()
    register(core, facet)
    a = create_profile(core, "ka", "fixture-brand", "A")
    b = create_profile(core, "kb", "fixture-brand", "B")
    item_id = profile_facet.choice_item_id("d1")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": FACET, "item_id": item_id,
                 "value": enable_choice(1)}])
    core.sessions.open_session("ks", session_id="S", harness_id="fixture-brand",
                               profile_id=a["profile_id"])
    core.sessions.set_overlay(
        "o1", session_id="S", facet_id=FACET, item_id=item_id,
        value=profile_facet.encode_choice(AssignmentDecision.INHERIT))
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b["profile_id"])
    ticket = core.sessions.begin_turn("t1", session_id="S")
    assert ticket["applied_switch"] is True
    applied_keys = {(i.facet_id, i.item_id, i.op) for batch in port.applied
                    for i in batch}
    assert (FACET, item_id, "reset") in applied_keys  # our compile reached the port
    config = core.sessions.session_config("S")
    assert config["switch_state"] == "settled"
    assert config["evidence"]["receipt"] is not None
    assert config["evidence"]["journal"]["state"] == "confirmed"
    # the overlay is gone from the effective view (success cleared it)
    sources = {i["item_id"]: i["source"] for i in config["items"]}
    assert sources.get(item_id) != "session_only"
    evidence = profile_facet.overlay_cleanup_evidence(
        journal_entry=config["evidence"]["journal"],
        receipt=config["evidence"]["receipt"])
    assert evidence["cleaned"] is True
    assert evidence["success"] is True
    assert evidence["state"] == "confirmed"


def test_absent_port_yields_their_typed_blocked_outcome_never_permissive(tmp_path):
    core = make_core(tmp_path)  # no application port composed at all
    facet, _, _ = supported_facet()
    register(core, facet)
    a = create_profile(core, "ka", "fixture-brand", "A")
    b = create_profile(core, "kb", "fixture-brand", "B")
    item_id = profile_facet.choice_item_id("d1")
    same = enable_choice(1)
    for profile, key in ((a, "ka1"), (b, "kb1")):
        core.profiles.set_facet_values(
            key, profile_id=profile["profile_id"], expected_version=1,
            values=[{"facet_id": FACET, "item_id": item_id, "value": same}])
    # identical values ⇒ the switch has no facet difference: the ONLY reason
    # can be the typed absence of the application port — never a fake success
    core.sessions.open_session("ks", session_id="S", harness_id="fixture-brand",
                               profile_id=a["profile_id"])
    core.sessions.set_overlay(
        "o1", session_id="S", facet_id=FACET, item_id=item_id,
        value=profile_facet.encode_choice(AssignmentDecision.INHERIT))
    core.sessions.select_profile("s1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "APPLICATION_PORT_ABSENT"
    config = core.sessions.session_config("S")
    assert config["switch_state"] == "pending"          # nothing applied
    assert config["current"]["profile_id"] == a["profile_id"]
    assert config["evidence"]["receipt"] is None         # nothing claimed
    assert config["evidence"]["journal"]["state"] == "planned"
    sources = {i["item_id"]: i["source"] for i in config["items"]}
    assert sources[item_id] == "session_only"            # overlay survived
    evidence = profile_facet.overlay_cleanup_evidence(
        journal_entry=config["evidence"]["journal"],
        receipt=config["evidence"]["receipt"])
    assert evidence["cleaned"] is False


def test_failed_apply_keeps_previous_coverage_and_pins(tmp_path):
    port = FixturePort(apply_verdict="confirmed")
    core = make_core(tmp_path, port=port)
    facet, _, _ = supported_facet()
    register(core, facet)
    a = create_profile(core, "ka", "fixture-brand", "A")
    b = create_profile(core, "kb", "fixture-brand", "B")
    item_id = profile_facet.choice_item_id("d1")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": FACET, "item_id": item_id,
                 "value": enable_choice(1)}])
    core.sessions.open_session("ks", session_id="S", harness_id="fixture-brand",
                               profile_id=a["profile_id"])
    core.sessions.select_profile("s1", session_id="S", profile_id=b["profile_id"])
    first = core.sessions.begin_turn("t1", session_id="S")
    assert first["applied_switch"] is True
    applied_config = core.sessions.session_config("S")
    first_receipt = applied_config["evidence"]["receipt"]
    assert first_receipt is not None

    # now a switch that the port REJECTS: the previous coverage and the
    # stored pin must survive untouched — no silent rollback to "nothing"
    core.config_port = FixturePort(apply_verdict="rejected")
    core.sessions.select_profile("s2", session_id="S", profile_id=a["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t2", session_id="S")
    assert exc.value.code == "SWITCH_BLOCKED"
    config = core.sessions.session_config("S")
    assert config["current"]["profile_id"] == b["profile_id"]  # coverage kept
    assert config["switch_state"] == "pending"
    assert config["evidence"]["receipt"]["operation_id"] == first_receipt["operation_id"]
    assert config["evidence"]["journal"]["state"] == "rejected"
    stored = [v for v in core.profiles.facet_values(a["profile_id"])
              if v["facet_id"] == FACET]
    assert stored[0]["value"] == enable_choice(1)  # pin kept, not cleared


def test_unknown_apply_stays_queryable_and_is_never_reported_success(tmp_path):
    port = FixturePort(apply_verdict="confirmed")
    core = make_core(tmp_path, port=port)
    facet, _, _ = supported_facet()
    register(core, facet)
    a = create_profile(core, "ka", "fixture-brand", "A")
    b = create_profile(core, "kb", "fixture-brand", "B")
    item_id = profile_facet.choice_item_id("d1")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": FACET, "item_id": item_id,
                 "value": enable_choice(1)}])
    core.sessions.open_session("ks", session_id="S", harness_id="fixture-brand",
                               profile_id=a["profile_id"])
    core.sessions.set_overlay(
        "o1", session_id="S", facet_id=FACET, item_id=item_id,
        value=profile_facet.encode_choice(AssignmentDecision.INHERIT))
    core.config_port = FixturePort(apply_verdict="unknown")
    core.sessions.select_profile("s1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SESSION_NEEDS_RECOVERY"
    config = core.sessions.session_config("S")
    assert config["switch_state"] == "needs_recovery"
    assert config["evidence"]["journal"]["state"] == "unknown"   # queryable
    assert config["evidence"]["receipt"] is None                  # never success
    sources = {i["item_id"]: i["source"] for i in config["items"]}
    assert sources[item_id] == "session_only"   # overlays NOT cleared
    projection = profile_facet.apply_outcome_projection(
        journal_entry=config["evidence"]["journal"],
        receipt=config["evidence"]["receipt"])
    assert projection["success"] is False and projection["queryable"] is True
    # the next turn is still blocked — the unknown is never folded into green
    with pytest.raises(ProfileError) as again:
        core.sessions.begin_turn("t2", session_id="S")
    assert again.value.code == "SESSION_NEEDS_RECOVERY"


# ==========================================================================
# overlay vocabulary helpers (pure)
# ==========================================================================


def test_overlay_intent_carries_their_source_vocabulary():
    facet, _, _ = supported_facet()
    intent = facet.overlay_intent(profile_facet.choice_item_id("d1"),
                                  enable_choice(1), overlay_revision=4)
    assert intent.source == "session-overlay@4"
    assert intent.op == "set" and intent.native_key == f"{FACET}.definition.d1"
    inherit = facet.overlay_intent(
        profile_facet.choice_item_id("d1"),
        profile_facet.encode_choice(AssignmentDecision.INHERIT),
        overlay_revision=5)
    assert inherit.op == "reset" and inherit.value is z1.UNSET


def test_choice_item_roundtrip_names_the_reference_only():
    assert profile_facet.choice_item_id("d1") == "definition.d1"
    assert profile_facet.definition_id_from_item("definition.d1") == "d1"
    assert profile_facet.definition_id_from_item(
        profile_facet.DIAGNOSTICS_ITEM_ID) is None
    with pytest.raises(errors.DomainError):
        profile_facet.decode_choice(
            {"provider": FACET, "schema_version": "1.0.0",
             "decision": "enable", "revision": True})
    with pytest.raises(errors.DomainError):
        profile_facet.decode_choice({"provider": FACET, "schema_version": "1.0.0",
                                     "decision": "shuffle", "revision": None})
