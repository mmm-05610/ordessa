"""Registration-surface pins for `SkillsServerPlugin` on the real host.

Everything is observed through `build_runtime(...)`'s live plugin host and
method registry (the composition with the storage provider the default
product injects, started), never a private table:

* the descriptor facts (id, requires, api version);
* every declared method id is in the registry with owner `ordessa.skills`
  and a bounded declared shape;
* availability is truthful: `supported` only for what the composed domain
  serves, `unknown` for the two §G2/brand-matrix-blocked rows;
* no collision with the frozen `assets.*` compat surface — the disjointness
  is pinned against `FROZEN_COMPAT_METHODS` itself (loaded from
  apps/server/tests/test_server_compat_boundary.py, that list's home);
* the host refuses a duplicate registration of the same family;
* the foundation contribution seam: the registration carries its
  `wire.error-families` batch through the published C2 API, and the host's
  per-composition aggregate — driven by the host-injected owner — answers
  this domain's codes with the published families.
"""
from __future__ import annotations

import pytest

from server_plugin_api import (
    WIRE_ERROR_FAMILIES_API_VERSION,
    WIRE_ERROR_FAMILIES_POINT_ID,
    ContributionDeclarationError,
)

from ordessa_skills.error_families import SKILLS_ERROR_FAMILIES
from ordessa_skills.plugin import PLUGIN_ID, SkillsServerPlugin
from ordessa_skills.wire import SKILLS_METHOD_IDS

from skills_wire_support import frozen_compat_methods, runtime  # noqa: F401


def test_descriptor_states_the_plugin_identity_and_edge():
    descriptor = SkillsServerPlugin().descriptor()
    assert descriptor.id == "ordessa.skills" == PLUGIN_ID
    assert descriptor.requires == ("ordessa.workspace",)
    assert descriptor.api_version == 1


def test_every_declared_method_is_on_the_real_registry(runtime):  # noqa: F811
    registry = runtime.plugin_host.methods
    registered = set(registry.method_ids())
    missing = set(SKILLS_METHOD_IDS) - registered
    assert not missing, f"the host did not register: {sorted(missing)}"
    for descriptor in registry.descriptors():
        if not descriptor.method_id.startswith("skills."):
            continue
        assert descriptor.owner == PLUGIN_ID
        assert "requestId" in descriptor.required_params
        assert not (descriptor.required_params & descriptor.optional_params)
        # every optional/required name is a lowerCamel word — bounded shapes
        for name in descriptor.required_params | descriptor.optional_params:
            assert name[0].islower() and " " not in name


def test_availability_is_truthful_per_family(runtime):  # noqa: F811
    registry = runtime.plugin_host.methods
    answers = {
        descriptor.method_id: descriptor.availability()
        for descriptor in registry.descriptors()
        if descriptor.method_id.startswith("skills.")
    }
    blocked = {
        "skills.discoverNative": "G2",
        "skills.invokeDescriptor": "brand-matrix",
    }
    for method_id, (supported, reason) in answers.items():
        if method_id in blocked:
            assert supported is False, (
                f"{method_id} must not claim supported while its blocker "
                f"({blocked[method_id]}) is open")
            assert blocked[method_id] in (reason or ""), (
                f"{method_id} availability reason must cite the blocker: "
                f"{reason!r}")
        else:
            assert supported is True, f"{method_id}: {reason!r}"
    # the invoke family is unknown for ALL THREE controlled brands today;
    # the predicate is brand-independent, the handler answers per brand.
    assert answers["skills.invokeDescriptor"][0] is False


def test_the_family_is_disjoint_from_the_frozen_compat_surface(runtime):  # noqa: F811
    """Compat `assets.*` retirement is C0's; our rows may not shadow it."""
    frozen = frozen_compat_methods()
    assert set(SKILLS_METHOD_IDS) & frozen == set()
    # historical names are untouched: none of our ids even starts with the
    # compat namespace.
    assert all(not method_id.startswith("assets.") for method_id in SKILLS_METHOD_IDS)
    registered = set(runtime.plugin_host.methods.method_ids())
    # the host's own hello row still answers, skills rode in beside it:
    assert "server.hello" in registered
    assert "workspaces.open" in registered  # the declared dependency composes


def test_duplicate_registration_is_refused_by_the_host(runtime):  # noqa: F811
    """The host owns the one dispatch truth: a second plugin declaring the
    same method ids is a startup refusal, never a silent shadow."""
    with pytest.raises(Exception) as info:
        runtime.plugin_host.activate(
            SkillsServerPlugin(contribute_harness_adapters=False))
    text = str(info.value)
    assert "skills." in text or PLUGIN_ID in text


# -- the foundation contribution seam -----------------------------------------


def test_the_error_families_contribution_publishes_through_the_host(runtime):  # noqa: F811
    """The registration's `ContributionBatch` rode the C2 transaction: the
    host staged it with the injected owner `ordessa.skills` and committed
    it, so THIS composition's family aggregate answers our codes with the
    families we published — not the generic class-name fall-through."""
    aggregate = runtime.plugin_host.wire_error_families
    assert aggregate is not None
    for code, family in SKILLS_ERROR_FAMILIES.items():
        assert aggregate.family_for(code) == family, code
    # a code no contributor published keeps the honest documented
    # fall-through (the contribution is a table, not a catch-all):
    assert aggregate.family_for("SKILLS_CODE_NOT_CONTRIBUTED_ANYWHERE") == \
        "UNAVAILABLE"


def test_the_contributed_families_are_only_wire1_family_names():
    """Closed-vocabulary pin: the payload may name families from
    `server_plugin_api.FAMILIES` only — a new family is a wire/1 contract
    change, never a plugin-side invention."""
    from server_plugin_api import FAMILIES

    assert set(SKILLS_ERROR_FAMILIES.values()) <= FAMILIES
    # the point identity we declare is the published one, atomically one row
    assert WIRE_ERROR_FAMILIES_POINT_ID == "wire.error-families"
    assert WIRE_ERROR_FAMILIES_API_VERSION == "v1"


def test_the_registration_shape_carries_the_batch():
    """The batch is declared at registration-build time (the host never
    reads a module table): one Contribution for the point, payload attached."""
    from server_plugin_api import Contribution, ContributionBatch

    batch = ContributionBatch((
        Contribution(
            point_id=WIRE_ERROR_FAMILIES_POINT_ID,
            api_version=WIRE_ERROR_FAMILIES_API_VERSION,
            payload=SKILLS_ERROR_FAMILIES,
        ),
    ))
    resolved = batch.resolve(WIRE_ERROR_FAMILIES_POINT_ID)
    assert resolved.payload is SKILLS_ERROR_FAMILIES
    # and the batch-level refusal grammar the host relies on stays intact:
    with pytest.raises(ContributionDeclarationError):
        Contribution(point_id="Skills.Errors", api_version="v1")
