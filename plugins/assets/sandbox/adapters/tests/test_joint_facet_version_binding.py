"""T020 — joint Permissions+Sandbox facet version binding on one observed pin.

WHY THIS EXISTS (measurement, recorded before any code change; full evidence:
``specs/011-q5-safety/evidence/t020-red-joint-facet-version-binding.txt``):

* ``Installation.adapter_version`` is an *observed* fact supplied by
  ``RuntimeAdapter.describe_installation()``
  (``plugins/harness/api/src/ordessa_harness_api/contracts.py:385-388``,
  dataclass at ``contracts.py:56-68``).
* The C4 admission consults it exactly once per fragment:
  ``descriptor.adapter_versions.contains(installation.adapter_version)``
  (``plugins/harness/src/ordessa_harness/application/configuration_service.py:153``),
  with a harness-identity check on the line above it (``:151``).
* This tree ships **no production** ``describe_installation`` implementer:
  the only Installation ever observed in-tree is the controlled fixture
  ``Installation("test-external", (1, 0, 0), (1, 0, 0), "fixture:installed")``
  (``plugins/harness/tests/fixtures/external_adapter/src/ordessa_test_external_adapter/__init__.py:67-69``),
  whose harness id matches none of the codex/claude/pi descriptors. The
  ``harnesses.toml`` identity versions (``plugins/harness/src/ordessa_harness/harnesses.toml``,
  e.g. codex ``version = "2.0"``) are *native* pins; none is an observed
  runtime-adapter version.
* The Sandbox facet declared exactly ``(0, 1, 0)`` — its own release fact
  (``.../src/ordessa_sandbox_adapters/points.py:66`` backed by
  ``plugins/assets/sandbox/adapters/pyproject.toml:7 version = "0.1.0"``).
* The Permissions facet declared ``VersionRange((1, 0, 0))`` = ``[1.0.0, ∞)``
  (``.../ordessa_permissions_adapters/contribution.py:120``) — unbounded, not
  even its own release fact (``plugins/permissions/adapters/pyproject.toml:7``
  is ``0.1.0``). ``[1.0.0, ∞) ∩ {0.1.0} = ∅``: no single observed
  adapter_version can ever satisfy both facets, so a joint two-facet product
  admission was version-wise unsatisfiable for *any* observation.

Boundary: this package installs without Permissions (see
``test_sandbox_adapters_dependency_direction.py``), so the Permissions facet
is mirrored here as a locally built descriptor — never imported. The mirror
reads the live ``_ADAPTER_VERSION`` literal out of the Permissions source file
(text inspection, no import), so this test flips red/green with the real
declaration instead of freezing a copy.
"""
from __future__ import annotations

import ast
import re
import tomllib
from contextlib import contextmanager
from pathlib import Path
from ordessa_harness.application import (
    ConfigurationApplicationService, OperationJournal, RuntimeSnapshot,
)
from ordessa_harness.materialization import MergeAuthority, TargetAuthority
from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, ApplicationTarget, Assessment,
    ConfigurationAdapterDescriptor, DesiredFragment, ErrorCode, Installation,
    Refused, TargetDescriptor, TargetHandle, ValueSchema, VersionRange,
)
from server_plugin_api import (
    AbsentContribution, Contribution, ContributionBatch,
    ServerPluginDescriptor, ServerPluginRegistration,
)

from ordessa_sandbox_adapters import (
    SANDBOX_CONFIGURATION_POINT_ID, SANDBOX_POINT_API_VERSION,
    SandboxAdaptersServerPlugin, CodexSandboxAdapter,
)
from ordessa_sandbox_adapters.points import _ADAPTER_VERSIONS, build_configuration_descriptor

REPO = Path(__file__).resolve().parents[5]
PERM_SRC = REPO / "plugins/permissions/adapters/src/ordessa_permissions_adapters/contribution.py"
SANDBOX_PYPROJECT = REPO / "plugins/assets/sandbox/adapters/pyproject.toml"
TARGET = ApplicationTarget("q5.t020.server", "q5.t020.session", "q5.t020.channel", 7)
HANDLE = TargetHandle("codex-config-toml", 7)
RESOURCE = ("private", "codex-settings.json")
#: the one native entry both codex facets declare
#: (permissions: contribution.py:85; sandbox: codex.py:57-58 native_field_claims)
SHARED_ENTRY = "sandbox_mode"


def _release_version(path: Path) -> tuple[int, int, int]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    core = data["project"]["version"].split("-", 1)[0].split("+", 1)[0]
    parts = [int(segment) for segment in core.split(".") if segment != ""]
    parts += [0] * (3 - len(parts))
    return tuple(parts[:3])


def _permissions_declared_adapter_versions() -> VersionRange:
    """Parse the live `_ADAPTER_VERSION = VersionRange(...)` literal from the
    Permissions source text — data inspection, no import, no folklore."""
    text = PERM_SRC.read_text(encoding="utf-8")
    match = re.search(r"^_ADAPTER_VERSION = VersionRange\((.*)\)$", text, re.M)
    assert match, "Permissions contribution.py no longer declares _ADAPTER_VERSION"
    tuples = [ast.literal_eval(part.strip())
              for part in re.findall(r"\([^()]+\)", match.group(1))]
    minimum, maximum = (tuples + [None])[:2]
    return VersionRange(minimum, maximum)


def _permissions_codex_descriptor() -> ConfigurationAdapterDescriptor:
    """Permissions-shaped mirror of `contribution.configuration_descriptor(
    CodexAdapter())`, values measured from contribution.py lines 70-71, 78,
    85, 101, 111 (facet id/schema, codex pin "2.0" -> (2, 0, 0), entries,
    claim, closed payload schema). Only the adapter range is parsed live so
    this mirror tracks the real declaration."""
    schema = ValueSchema(
        "object",
        properties=(
            ("sandbox_mode", ValueSchema("string", enum=("read-only", "workspace-write"))),
            ("approval_policy", ValueSchema("string", enum=("untrusted", "on-request"))),
        ),
        required=())
    from ordessa_harness_api import FieldClaim
    return ConfigurationAdapterDescriptor(
        "permissions.policy-adapter.codex", "v1", "permissions.policy-adapters",
        "v1", "codex", VersionRange((2, 0, 0), (2, 0, 0)),
        _permissions_declared_adapter_versions(),
        ("sandbox_mode", "approval_policy"), schema,
        (FieldClaim("file", ".codex/config.toml", ("approval_policy",)),))


class _FacetAdapter:
    """Adapter surface around one real descriptor. `assess` says supported so
    the platform's own version/identity gate (configuration_service.py:150-153)
    is the only filter left; `compile` stops deterministically at a code the
    version gate never produces, proving the gate was passed."""

    def __init__(self, descriptor: ConfigurationAdapterDescriptor) -> None:
        self.descriptor = descriptor

    def assess(self, context, request):
        return Assessment("supported", evidence_ref="q5:t020:controlled")

    def compile(self, context, before, desired):
        return AdapterRefusal(ErrorCode.TARGET_CONFLICT,
                              "t020 controlled stop past the version gate; no effect")

    def verify(self, context, observed):  # pragma: no cover - plan() never reaches it
        raise AssertionError("t020 joint test stops before verification")


class _JointRuntime:
    """Controlled runtime whose snapshot carries exactly one observed
    Installation; all fragments of both facets see the same installation."""

    def __init__(self, root: Path, installation: Installation) -> None:
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        self.private_root = root
        self.installation = installation
        self.descriptor = TargetDescriptor(HANDLE, "file", "json", "instance",
                                           ((SHARED_ENTRY,),))

    def capture(self, target):
        context = AdapterContext((self.descriptor,), self.installation,
                                 SHARED_ENTRY, "instance", "q5:t020:capability")
        return RuntimeSnapshot(target, context,
                               MergeAuthority((TargetAuthority(self.descriptor, RESOURCE),)),
                               {}, {}, self.private_root, {}, "rev-1",
                               "q5:t020:native-version", 1, "auth-1", "secret-ref-1")

    def activate_generation(self, target, lease):  # pragma: no cover
        raise AssertionError("t020 joint test applies nothing")

    def observe(self, target):  # pragma: no cover
        raise AssertionError("t020 joint test observes nothing")


class _SingleFacetCarrier:
    """Exposes exactly one facet, standing in for the point view the service
    reads; the real multi-owner product composition is exercised separately
    in `test_real_two_fragment_joint_plan_refuses...`."""

    def __init__(self, adapter: _FacetAdapter, owner: str) -> None:
        self._adapter = adapter
        self._owner = owner

    @contextmanager
    def use_contribution(self, point_id, *, consumer=None):
        class _View:
            payload = self._adapter
            owner = self._owner
            publication_token = "q5:t020:publication"
        yield _View()


class _AlwaysPermit:
    def verify(self, principal, target, plan, operation_key, permit):
        return True


def _plan_one(tmp_path: Path, descriptor: ConfigurationAdapterDescriptor,
              fragment: DesiredFragment, installation: Installation) -> Refused:
    service = ConfigurationApplicationService(
        principal="q5:t020", target=TARGET,
        carrier=_SingleFacetCarrier(_FacetAdapter(descriptor), "q5:t020.facet"),
        runtime=_JointRuntime(tmp_path / "private", installation),
        permits=_AlwaysPermit(),
        journal=OperationJournal(tmp_path / "journal.sqlite"))
    return service.plan(TARGET, (fragment,), "rev-1")


SANDBOX_CODEX = build_configuration_descriptor(CodexSandboxAdapter())
SANDBOX_FRAGMENT = DesiredFragment(
    "sandbox.native-configuration", "t020-item-sandbox", "1",
    "q5:t020:sandbox-ref", "rev-1", "set", {"sandbox_mode": "workspace-write"})
PERMISSIONS_FRAGMENT = DesiredFragment(
    "permissions.policy-adapters", "t020-item-policy", "v1",
    "q5:t020:policy-ref", "rev-1", "set",
    {"sandbox_mode": "workspace-write", "approval_policy": "on-request"})

#: the version facts this tree actually publishes/observes; no invented
#: candidates — (1,0,0) is the only Installation ever observed in-tree (the
#: fixture), the release pins are each facet's own measured build fact.
OBSERVED_CANDIDATES = (
    (1, 0, 0),   # plugins/harness/tests/fixtures/external_adapter/.../__init__.py:69
    _release_version(SANDBOX_PYPROJECT),  # sandbox release fact (pyproject.toml:7)
)


def test_the_pair_is_jointly_satisfiable_at_one_observed_candidate(tmp_path):
    """RED before the fix: `adapter_versions` ranges
    `[1.0.0, ∞)` (permissions) ∩ `{0.1.0}` (sandbox) = ∅, so every candidate
    observation fails at least one facet's version gate. GREEN after the fix:
    both facets declare their own exact release pin and the shared candidate
    (0, 1, 0) clears both gates — the platform advances past the version gate
    to the deterministic stub code, for one and the same Installation."""
    installation_versions_that_pass_both = []
    for adapter_version in OBSERVED_CANDIDATES:
        installation = Installation("codex", (2, 0, 0), adapter_version,
                                    "q5:t020:candidate")
        sandbox = _plan_one(tmp_path / "sb" / str(adapter_version), SANDBOX_CODEX,
                            SANDBOX_FRAGMENT, installation)
        permissions = _plan_one(tmp_path / "pm" / str(adapter_version),
                                _permissions_codex_descriptor(),
                                PERMISSIONS_FRAGMENT, installation)
        passed = []
        for label, result in (("sandbox", sandbox), ("permissions", permissions)):
            assert isinstance(result, Refused), result
            if result.code in (ErrorCode.CAPABILITY_UNSUPPORTED,
                               ErrorCode.VERSION_UNVERIFIED):
                passed.append((label, "version-gate-refused"))
            else:
                passed.append((label, "past-version-gate"))
        if all(outcome == "past-version-gate" for _, outcome in passed):
            installation_versions_that_pass_both.append(adapter_version)
    assert installation_versions_that_pass_both, (
        "no version fact this tree publishes satisfies BOTH facets' declared "
        "adapter_versions — the pair is jointly unsatisfiable (C0 finding, "
        "specs/011-c0-foundation-harness/api-requests.md); the declarations "
        "must be pinned to backed facts, not widened")


def test_sandbox_pin_is_its_own_release_fact_not_a_copied_range(tmp_path):
    """The Sandbox declaration must equal the sandbox distribution's own
    release version, exact on both bounds — a drift here is either an
    unbacked widening or a silent re-key."""
    pin = _release_version(SANDBOX_PYPROJECT)
    assert _ADAPTER_VERSIONS.minimum == pin
    assert _ADAPTER_VERSIONS.maximum == pin, (
        "sandbox adapter_versions must stay an exact measured pin")
    assert SANDBOX_CODEX.adapter_versions == _ADAPTER_VERSIONS


def test_permissions_declaration_is_parsed_not_copied():
    range_now = _permissions_declared_adapter_versions()
    assert range_now.maximum is not None, (
        "permissions adapter_versions declared an unbounded maximum: "
        "no observation in this tree backs an open-ended support claim")
    perm_pin = _release_version(REPO / "plugins/permissions/adapters/pyproject.toml")
    assert range_now.minimum == perm_pin and range_now.maximum == perm_pin, (
        "permissions facet must pin adapter_versions to its own release fact "
        f"{perm_pin}, the only version it can back (pyproject.toml:7)")


class _PermissionsShapedStubPlugin:
    """Publishes Permissions-shaped codex/claude/pi descriptors on the real
    point (values mirrored from contribution.py, adapter range parsed live)
    without importing the Permissions package."""

    PLUGIN_ID = "q5.t020.permissions-stub"

    def descriptor(self):
        return ServerPluginDescriptor(self.PLUGIN_ID, "t020 permissions mirror", "0.1.0")

    def build(self, context):
        from ordessa_harness_api import FieldClaim
        perm_range = _permissions_declared_adapter_versions()
        claude = ConfigurationAdapterDescriptor(
            "permissions.policy-adapter.claude-code", "v1", "permissions.policy-adapters",
            "v1", "claude-code", VersionRange((0, 81, 2), (0, 81, 2)), perm_range,
            ("permissions.ask", "permissions.deny"),
            ValueSchema("object", properties=(
                ("permissions.ask", ValueSchema("array", items=ValueSchema("string"))),
                ("permissions.deny", ValueSchema("array", items=ValueSchema("string"))),
            ), required=()),
            (FieldClaim("file", ".claude/settings.json", ("permissions", "ask")),
             FieldClaim("file", ".claude/settings.json", ("permissions", "deny"))))
        pi = ConfigurationAdapterDescriptor(
            "permissions.policy-adapter.pi", "v1", "permissions.policy-adapters",
            "v1", "pi", VersionRange((2, 0, 0), (2, 0, 0)), perm_range,
            ("toolCallGate.extensionId", "toolCallGate.ask", "toolCallGate.deny"),
            ValueSchema("object"), ())
        batch = ContributionBatch(
            tuple(Contribution(SANDBOX_CONFIGURATION_POINT_ID, SANDBOX_POINT_API_VERSION, d)
                  for d in (_permissions_codex_descriptor(), claude, pi)),
            open_points=frozenset({SANDBOX_CONFIGURATION_POINT_ID}))
        return ServerPluginRegistration(contributions=batch)


def test_composition_admits_both_facet_sets_jointly(tmp_path):
    """The declared pins must NOT split composition admission: with both
    facets published on the real point (same codex native+adapter pin), the
    platform's conflict gate admits them — facets differ and native field
    claims live under distinct target ids (contribution.py:101 vs points.py:149)."""
    from ordessa_server.bootstrap import build_runtime
    runtime = build_runtime(tmp_path / "data")
    host = runtime.plugin_host
    try:
        host.activate(SandboxAdaptersServerPlugin())
        host.activate(_PermissionsShapedStubPlugin())
        views = host.contributions(SANDBOX_CONFIGURATION_POINT_ID)
        assert len(views) == 6, [view.payload.adapter_id for view in views]
        assert len({view.owner for view in views}) == 2
    finally:
        runtime.stop()


def test_real_two_fragment_joint_plan_refuses_pending_trusted_observation(tmp_path):
    """Honest refusal leg: even with both facet sets published and a
    version-satisfiable pair, ONE two-fragment plan through the real C4
    service on the real host is refused by the platform with
    `ErrorCode.ADAPTER_MISSING` — this tree's `use_contribution` has no
    per-fragment facet selection (an open multi-owner point resolves to an
    observable absence, plugin_host/contribution_points.py:150-162), and no
    production `RuntimeAdapter.describe_installation()` publishes a trusted
    observed Installation for codex. Missing evidence named: (1) a production
    installation observer for the harness runtime, (2) C4 per-fragment facet
    selection (C0 branch commits 6eeba5b284/080396ecaf, not this tree)."""
    from ordessa_server.bootstrap import build_runtime
    runtime = build_runtime(tmp_path / "data")
    host = runtime.plugin_host
    try:
        host.activate(SandboxAdaptersServerPlugin())
        host.activate(_PermissionsShapedStubPlugin())
        with host.use_contribution(SANDBOX_CONFIGURATION_POINT_ID,
                                   consumer=None) as view:
            assert isinstance(view, AbsentContribution)
            assert not hasattr(view, "payload")
        service = ConfigurationApplicationService(
            principal="q5:t020", target=TARGET, carrier=host,
            runtime=_JointRuntime(tmp_path / "private",
                                  Installation("codex", (2, 0, 0),
                                               _release_version(SANDBOX_PYPROJECT),
                                               "q5:t020:controlled-candidate")),
            permits=_AlwaysPermit(),
            journal=OperationJournal(tmp_path / "journal.sqlite"))
        result = service.plan(TARGET, (SANDBOX_FRAGMENT, PERMISSIONS_FRAGMENT), "rev-1")
        assert isinstance(result, Refused)
        assert result.code is ErrorCode.ADAPTER_MISSING
    finally:
        runtime.stop()
