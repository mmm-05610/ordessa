"""T05b — the PLATFORM is the composition authority; the private registry is gone.

Before the foundation checkpoint this package kept its own
``SandboxAdapterRegistry``/``stage_field_claims`` as a second admission
authority. The real point now provides that authority —
``HarnessContributionRegistry`` (behind ``stage_contributions``) refuses
duplicate adapter ids, facet/entry/version-range overlaps and cross-facet
native-field claim overlaps with the typed ``HarnessContributionError``, and
the batch transaction never publishes a half-staged batch. These tests move
the old semantics (no last-wins, order-insensitive pair refusal, nothing
admitted on refusal) onto the platform and prove the private authority was
demoted: the package exports no second registry any more.

The stub descriptors here are LOCAL — the Sandbox domain never imports
``ordessa_permissions_*`` (verification.md extra-gate 2); the stub only
plays the role "a second facet claiming one native field".
"""
from __future__ import annotations

import pytest
from _sandbox_adapters_helpers import pinned_versions
from ordessa_harness.contributions import (
    CONFIGURATION_POINT, HarnessContributionError, HarnessContributionRegistry,
)
from ordessa_harness_api import ConfigurationAdapterDescriptor, FieldClaim, ValueSchema, VersionRange
from server_plugin_api import AbsentContribution, Contribution, ContributionBatch, stage_contributions

import ordessa_sandbox_adapters
from ordessa_sandbox_adapters import (
    CodexSandboxAdapter,
    SANDBOX_FACET_ID,
    SANDBOX_POINT_API_VERSION,
    build_configuration_batch,
    build_configuration_descriptor,
    default_sandbox_adapters,
    HarnessSandboxConfigurationAdapter,
)

OWNER = "ordessa.sandbox-adapters"
CODEX_TARGET = next(claim.target_id for claim in
                    build_configuration_descriptor(CodexSandboxAdapter()).claims)
CODEX_MODE = FieldClaim("file", CODEX_TARGET, ("sandbox_mode",))
ADAPTER_VERSIONS = VersionRange((0, 1, 0), (0, 1, 0))

OPEN_BATCH = frozenset({CONFIGURATION_POINT})


def _semver(text: str) -> tuple[int, int, int]:
    core = text.split("-", 1)[0].split("+", 1)[0]
    parts = [int(p) for p in core.split(".")]
    parts += [0] * (3 - len(parts))
    return tuple(parts[:3])


def stub_descriptor(adapter_id: str, facet_id: str, *, harness_id: str = "codex",
                    entries: tuple[str, ...] = ("approval_policy",),
                    claims: tuple[FieldClaim, ...] = ()) -> ConfigurationAdapterDescriptor:
    """A LOCAL stand-in for another facet's codex contribution (e.g. the
    Permissions native projection). No Permissions import anywhere."""
    return ConfigurationAdapterDescriptor(
        adapter_id, "v1", facet_id, "1", harness_id,
        VersionRange(*[_semver(pinned_versions()[harness_id])] * 2),
        ADAPTER_VERSIONS, entries, ValueSchema("object"), claims)


def _codex_contribution() -> Contribution:
    return Contribution(CONFIGURATION_POINT, SANDBOX_POINT_API_VERSION,
                        HarnessSandboxConfigurationAdapter(
                            build_configuration_descriptor(CodexSandboxAdapter()), CodexSandboxAdapter()),
                        required=False)


def _payload(descriptor):
    return HarnessSandboxConfigurationAdapter(descriptor, object())


# ------------------------------------------------------------ demotion proof
def test_package_exports_no_second_admission_authority():
    for name in ("SandboxAdapterRegistry", "stage_field_claims",
                 "NativeConfigAdapterDescriptor", "NativeConfigContribution",
                 "build_native_configuration_contribution",
                 "default_sandbox_registry", "RegistryConflictError",
                 "DuplicateAdapterIdError", "OverlappingRangeError"):
        assert not hasattr(ordessa_sandbox_adapters, name), name


# ------------------------------------------------- stage / commit lifecycle
def test_staged_but_uncommitted_facet_is_not_resolvable():
    registry = HarnessContributionRegistry()
    staged = stage_contributions(registry.configuration_handler, OWNER,
                                 build_configuration_batch())
    # staged only: neither the registry's published view nor the batch's own
    # resolve exposes the facet before commit.
    assert registry.configuration_descriptors() == ()
    resolved = staged.resolve(CONFIGURATION_POINT)
    assert isinstance(resolved, AbsentContribution)
    staged.commit()
    published = registry.configuration_descriptors()
    assert len(published) == 3
    assert {d.adapter_id for d in published} == {
        "sandbox.native-config.codex", "sandbox.native-config.claude-code",
        "sandbox.native-config.pi"}
    # the owner is the host-injected identity, never author-declared
    assert all(d.facet_id == SANDBOX_FACET_ID for d in published)


def test_rollback_of_a_staged_batch_publishes_nothing():
    registry = HarnessContributionRegistry()
    staged = stage_contributions(registry.configuration_handler, OWNER,
                                 build_configuration_batch())
    staged.rollback()
    assert registry.configuration_descriptors() == ()


# ------------------------------------------------ platform conflict refusals
@pytest.mark.parametrize("sandbox_first", (True, False))
def test_two_facets_claiming_one_native_field_are_refused_neither_admitted(sandbox_first):
    """The platform exception raised is ``HarnessContributionError``
    ("native field claims overlap") — not a package-private one — and the
    refusal is order-insensitive with NOTHING admitted afterwards."""
    stub = stub_descriptor("permissions.stub.native-projection",
                           "permissions.native-projection",
                           claims=(CODEX_MODE,))
    pair = [_codex_contribution(), Contribution(CONFIGURATION_POINT, "v1", _payload(stub),
                                                required=False)]
    if not sandbox_first:
        pair = [pair[1], pair[0]]
    registry = HarnessContributionRegistry()
    batch = ContributionBatch(tuple(pair), open_points=OPEN_BATCH)
    with pytest.raises(HarnessContributionError) as excinfo:
        stage_contributions(registry.configuration_handler, OWNER, batch)
    assert "claims overlap" in str(excinfo.value)
    # neither the sandbox codex facet nor the stub ended up admitted
    assert registry.configuration_descriptors() == ()


@pytest.mark.parametrize("first", (True, False))
def test_duplicate_adapter_id_refused_by_the_platform(first):
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, OWNER,
                        build_configuration_batch()).commit()
    assert len(registry.configuration_descriptors()) == 3
    dupes = [Contribution(CONFIGURATION_POINT, "v1",
                          _payload(build_configuration_descriptor(adapter)), required=False)
             for adapter in default_sandbox_adapters()[:2]]
    if not first:
        dupes = dupes[::-1]
    with pytest.raises(HarnessContributionError) as excinfo:
        stage_contributions(registry.configuration_handler, "second.owner",
                            ContributionBatch(tuple(dupes), open_points=OPEN_BATCH))
    assert "adapter_id already registered" in str(excinfo.value)
    # no last-wins: the committed set is untouched and the dupe pair is absent
    assert len(registry.configuration_descriptors()) == 3


def test_same_facet_shared_entry_refused_by_the_platform():
    registry = HarnessContributionRegistry()
    twin = stub_descriptor("sandbox.native-config.codex-twin", SANDBOX_FACET_ID,
                           entries=("sandbox_mode",))
    with pytest.raises(HarnessContributionError) as excinfo:
        stage_contributions(
            registry.configuration_handler, OWNER,
            ContributionBatch((_codex_contribution(),
                               Contribution(CONFIGURATION_POINT, "v1", _payload(twin),
                                            required=False)),
                              open_points=OPEN_BATCH))
    assert "facet/entry/version range overlap" in str(excinfo.value)
    assert registry.configuration_descriptors() == ()


def test_disjoint_facets_admit_side_by_side():
    registry = HarnessContributionRegistry()
    stub = stub_descriptor("permissions.stub.native-projection",
                           "permissions.native-projection",
                           claims=(FieldClaim("file", CODEX_TARGET,
                                              ("approval_policy",)),))
    staged = stage_contributions(
        registry.configuration_handler, OWNER,
        ContributionBatch((_codex_contribution(),
                           Contribution(CONFIGURATION_POINT, "v1", _payload(stub),
                                        required=False)),
                          open_points=OPEN_BATCH))
    staged.commit()
    published = registry.configuration_descriptors()
    assert len(published) == 2  # the proof pair only; sandbox defaults separate
    assert {d.facet_id for d in published} == {SANDBOX_FACET_ID,
                                               "permissions.native-projection"}
