"""T022 — the controlled C4 apply chain through the REAL platform service.

Upgrades this lane's isolation evidence from "intents compiled" to "the
platform's own ``ConfigurationApplicationService`` planned AND applied the
sandbox facet against an observed installation" — the strongest proof this
tree can honestly give — and registers every remaining production gap as
UNKNOWN in ``matrix.py``.

MEASURED FACTS this file relies on (all re-verified in-tree, 011-q5-safety):

* the C4 port: ``ConfigurationService`` Protocol + ``Plan``/``PlanResult``,
  ``ApplicationTarget``/``ApplicationResult``, ``Confirmed``/``Refused``/
  ``Unknown``, ``OperationRecord``, ``DesiredFragment``,
  ``ConfigurationCapabilit*`` —
  ``plugins/harness/api/src/ordessa_harness_api/application.py:211`` (protocol),
  ``:29-40`` (ApplicationTarget), ``:42-61`` (DesiredFragment), ``:129-181``
  (Plan/Refused/Confirmed/Unknown + aliases), ``:184-199`` (OperationRecord).
* the REAL implementation this file drives (never a re-implementation):
  ``plugins/harness/src/ordessa_harness/application/configuration_service.py``
  — plan ``:202``, apply ``:239``, query ``:330``, reconcile ``:333``;
  the joint admission gate (entry + harness id + native + ADAPTER version of
  the OBSERVED installation) at ``:150-153``; the unobserved-native refusal
  ``:148-149``; the absent-contribution refusal ``:212-213``; the claim
  ceiling ``:196-197`` ("intent exceeds registered claims"); the readback
  identity/manifest gate ``:301-302``; the match-only confirmation
  ``:303-305``; the post-reservation failure -> ``Unknown`` (never
  ``Confirmed``) path ``:312-320``.
* the durable ledger is the platform's own SQLite journal
  (``application/operation_journal.py`` reserve ``:183``, query ``:227``,
  one-active-operation fence ``:133-136``); the publication is the platform's
  own ``materialize_generation`` writing ONE private ``gen-*`` directory and
  handing back an fd-bound lease with sha256 manifests
  (``materialization/private_generation.py:447-488``, ``read_bytes :60-79``).
* observation provenance: this tree ships NO production
  ``RuntimeAdapter.describe_installation()`` implementer. The only in-tree one
  is the harness's controlled fixture
  ``plugins/harness/tests/fixtures/external_adapter/src/ordessa_test_external_adapter/__init__.py:69``,
  which observes ``Installation("test-external", (1,0,0), (1,0,0), ...)``.
  This facet's descriptors pin adapter_version EXACTLY (0,1,0)
  (``src/.../points.py:72`` backed by ``pyproject.toml:7``), so that (1,0,0)
  observation and this facet deliberately do NOT match — the mismatch is
  proven as a platform refusal below
  (``test_observed_adapter_version_mismatch_is_refused_by_the_platform``).
  The positive apply chain therefore runs against a locally defined
  observation provider (``_ControlledRuntimeAdapter`` in this file) at
  (0,1,0); no harness fixture or harness package file is edited.
* the (1,0,0) fixture values are spelled as constants here because the
  fixture dist is not installed in this venv (measured:
  ``importlib.util.find_spec("ordessa_test_external_adapter") -> None``);
  they are copied from the cited source line, not invented.

Boundary (kept honest): every write below is performed BY THE PLATFORM
through the injected controlled target in a temp dir. ``ordessa_sandbox_adapters``
itself performs zero I/O during plan/apply — asserted behaviourally by
``test_my_package_performs_no_io_during_the_plan_and_apply_chain`` on top of
the standing static purity gates (``test_purity_no_fake_apply.py``).
"""
from __future__ import annotations

import builtins
import hashlib
import json
import os
import socket
import subprocess
import tomllib
import traceback
from contextlib import contextmanager
from pathlib import Path

from ordessa_harness.application import (
    ConfigurationApplicationService, NativeReadback, OperationJournal,
    RuntimeSnapshot,
)
from ordessa_harness.materialization import MergeAuthority, TargetAuthority
from ordessa_harness_api import (
    AdapterContext, ApplicationTarget, Assessment, ConfigurationCapabilities,
    ConfigurationAdapterDescriptor, Confirmed, DesiredFragment, ErrorCode,
    FieldClaim, FieldPath, Installation, IntentSet, IntentSource, NotFound,
    OperationRecord, Plan, Refused, RuntimeAdapterDescriptor, SetField,
    TargetDescriptor, TargetHandle, Unknown, ValueSchema, VersionRange,
)
from server_plugin_api import (
    Contribution, ContributionBatch, ServerPluginDescriptor,
    ServerPluginRegistration,
)

import ordessa_sandbox_adapters as adapters_package
from ordessa_sandbox_adapters import (
    SANDBOX_CONFIGURATION_POINT_ID,
    SANDBOX_FACET_ID,
    SANDBOX_FACET_SCHEMA_VERSION,
    SANDBOX_POINT_API_VERSION,
    ClaudeSandboxAdapter,
    CodexSandboxAdapter,
    SandboxAdaptersServerPlugin,
    SandboxConfigurationSurface,
    sandbox_code_of,
    sandbox_item_id,
)
from ordessa_sandbox_api import SandboxErrorCode, ToolCategory

from _sandbox_adapters_helpers import (
    authorized_facts,
    claude_intent,
    codex_intent,
    platform_facts,
)

PRINCIPAL = "q5.t022.principal"
TARGET = ApplicationTarget("q5.t022.server", "q5.t022.session",
                           "q5.t022.channel", 7)

#: the ONLY Installation ever observed in-tree, copied from the cited
#: fixture source line (adapter_version (1,0,0)); used solely to prove the
#: platform REFUSES it against this facet's (0,1,0) pin.
FIXTURE_OBSERVED_ADAPTER_VERSION = (1, 0, 0)

# --------------------------------------------------------------- brand specs
# Values measured from the published descriptors themselves
# (src/ordessa_sandbox_adapters/points.py: codex claims target
# "codex-config-toml", claude claims target "claude-settings-json"); the
# codecs match the matrix entry claims (toml / json).
_CODEX_BRAND = {
    "harness": "codex", "native": (2, 0, 0),
    "handle_id": "codex-config-toml", "codec": "toml",
    "resource": ("private", "codex-settings.toml"),
    "entry": "sandbox_mode",
    "allowed_fields": (("sandbox_mode",), ("sandbox_workspace_write",)),
    "fragment_value": {"sandbox_mode": "workspace-write"},
    "expected_document": {"sandbox_mode": "workspace-write"},
}
_CLAUDE_BRAND = {
    "harness": "claude-code", "native": (0, 81, 2),
    "handle_id": "claude-settings-json", "codec": "json",
    "resource": ("private", "claude-settings.json"),
    "entry": "bashSandbox",
    "allowed_fields": (("bashSandbox",), ("powerShellSandbox",),
                       ("monitorSandbox",)),
    "fragment_value": {"bashSandbox": True},
    "expected_document": {"bashSandbox": True},
}


# ------------------------------------------------- locally defined observer
class _ControlledRuntimeAdapter:
    """In-test ``describe_installation`` provider — the shape the platform's
    gate (configuration_service.py:150-153) consumes.

    Not a production claim: this tree has no trusted production observer
    (module docstring), so the positive chain observes (0,1,0) here and the
    production-observation absence stays UNKNOWN in the matrix.
    """

    def __init__(self, harness_id: str, native_version, adapter_version):
        self.descriptor = RuntimeAdapterDescriptor(
            f"q5.t022.observed-{harness_id}", "v1", harness_id, (),
            VersionRange(adapter_version, adapter_version))
        self._installation = Installation(
            harness_id, native_version, adapter_version,
            "q5:t022:in-test-observation")

    def describe_installation(self):
        return self._installation


class _ControlledTargetRuntime:
    """The injected controlled target: capture/activate/observe only.

    All publication is done by the platform (``materialize_generation``);
    this class never writes — it reads back through the platform's own
    fd-bound lease (``read_bytes``), hashing the bytes it saw.
    """

    def __init__(self, root: Path, observer: _ControlledRuntimeAdapter,
                 brand: dict, *, tamper: str | None = None):
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        self.private_root = root
        self.observer = observer
        self.brand = brand
        self.tamper = tamper
        self.target_descriptor = TargetDescriptor(
            TargetHandle(brand["handle_id"], 7), "file", brand["codec"],
            "instance", brand["allowed_fields"])
        self.activated: list[str] = []
        self.read_back: bytes | None = None
        self._lease_files: tuple = ()

    def capture(self, target: ApplicationTarget) -> RuntimeSnapshot:
        context = AdapterContext(
            (self.target_descriptor,), self.observer.describe_installation(),
            self.brand["entry"], "instance", "q5:t022:capability-evidence")
        return RuntimeSnapshot(
            target, context,
            MergeAuthority((TargetAuthority(self.target_descriptor,
                                            self.brand["resource"]),)),
            {}, {}, self.private_root, {}, "rev-1",
            "q5:t022:native-version", 1, "auth-1", "secret-ref-1")

    def activate_generation(self, target, lease) -> None:
        data = lease.read_bytes(self.brand["resource"])
        digests = dict(lease.files)
        # the receipt the service will confirm against is the bytes actually
        # published by the platform, verified by digest through the lease fd
        assert hashlib.sha256(data).hexdigest() == digests[self.brand["resource"]]
        self.read_back = data
        self._lease_files = lease.files
        self.activated.append(lease.generation_name)

    def observe(self, target) -> NativeReadback:
        text = self.read_back.decode("utf-8")
        document = (tomllib.loads(text) if self.brand["codec"] == "toml"
                    else json.loads(text))
        files = self._lease_files
        if self.tamper == "files":
            files = tuple((resource, "0" * 64) for resource, _ in files)
        elif self.tamper == "value":
            document = {"sandbox_mode": "read-only"} if "sandbox_mode" in document \
                else {key: False for key in document}
        return NativeReadback(target, "q5:t022:native-session-1", "rev-2",
                              document, files, "q5:t022:readback-evidence",
                              ("/".join(self.brand["resource"]),))


class _GrantingPermits:
    """Permit verifier spy: the platform asks it exactly once per apply with
    its own Plan object (configuration_service.py:272-273)."""

    def __init__(self):
        self.calls: list[tuple] = []

    def verify(self, principal, target, plan, operation_key, permit) -> bool:
        self.calls.append((principal, target, type(plan).__name__,
                           operation_key, permit))
        return True


# ------------------------------------------------------------------ carrier
class _FacetPlugin:
    """Publishes exactly ONE surface on the real point, so the host's
    single-record resolution (apps/server/.../contribution_points.py
    ``resolve``) yields a view with payload + host-issued publication_token."""

    PLUGIN_ID = "q5.t022.controlled-facet"

    def __init__(self, surface: SandboxConfigurationSurface) -> None:
        self._surface = surface

    def descriptor(self):
        return ServerPluginDescriptor(self.PLUGIN_ID,
                                      "T022 controlled C4 facet", "0.1.0")

    def build(self, context):
        return ServerPluginRegistration(contributions=ContributionBatch(
            (Contribution(SANDBOX_CONFIGURATION_POINT_ID,
                          SANDBOX_POINT_API_VERSION, self._surface),),
            open_points=frozenset({SANDBOX_CONFIGURATION_POINT_ID})))


class _SingleViewCarrier:
    """Controlled stand-in for an ABSENT facet view (payload-less, like the
    host's ``AbsentContribution``) or a locally built payload."""

    def __init__(self, payload=None, owner: str = "q5.t022.local-facet",
                 token: str | None = "q5:t022:publication") -> None:
        self._payload = payload
        self._owner = owner
        self._token = token

    @contextmanager
    def use_contribution(self, point_id, *, consumer=None):
        payload, owner, token = self._payload, self._owner, self._token

        class _View:
            pass

        view = _View()
        if payload is not None:
            view.payload = payload
            view.owner = owner
            view.publication_token = token
        yield view


class _AbsentViewCarrier(_SingleViewCarrier):
    def __init__(self):
        super().__init__(payload=None, owner=None, token=None)


def _codex_surface(**intent_overrides) -> SandboxConfigurationSurface:
    return SandboxConfigurationSurface(
        CodexSandboxAdapter(), intent=codex_intent(**intent_overrides),
        platform_facts=platform_facts(), authorized=authorized_facts())


def _claude_surface(**intent_overrides) -> SandboxConfigurationSurface:
    return SandboxConfigurationSurface(
        ClaudeSandboxAdapter(), intent=claude_intent(**intent_overrides),
        platform_facts=platform_facts(), authorized=authorized_facts())


def _fragment(brand: str, value) -> DesiredFragment:
    return DesiredFragment(SANDBOX_FACET_ID, sandbox_item_id(brand),
                           SANDBOX_FACET_SCHEMA_VERSION, f"q5:t022:{brand}",
                           "rev-1", "set", value)


def _service(tmp_path: Path, *, brand: dict, observer, carrier,
             tamper=None, journal: OperationJournal | None = None):
    runtime = _ControlledTargetRuntime(tmp_path / "private", observer, brand,
                                       tamper=tamper)
    journal = journal or OperationJournal(tmp_path / "journal.sqlite")
    permits = _GrantingPermits()
    service = ConfigurationApplicationService(
        principal=PRINCIPAL, target=TARGET, carrier=carrier,
        runtime=runtime, permits=permits, journal=journal)
    return service, runtime, journal, permits


@contextmanager
def _host_service(tmp_path: Path, *, surface, brand: dict, observer,
                  tamper=None):
    """Composition through the REAL host: ``build_runtime`` plugin host is
    the carrier, the facet is published on the real point, the service is the
    platform's own ``ConfigurationApplicationService``."""
    from ordessa_server.bootstrap import build_runtime
    host_runtime = build_runtime(tmp_path / "host")
    try:
        host = host_runtime.plugin_host
        if surface is not None:
            host.activate(_FacetPlugin(surface))
        service, runtime, journal, permits = _service(
            tmp_path, brand=brand, observer=observer, tamper=tamper,
            carrier=host)
        yield service, runtime, journal, permits, host
    finally:
        host_runtime.stop()


def _observed(harness: str, native, adapter_version=(0, 1, 0)):
    return _ControlledRuntimeAdapter(harness, native, adapter_version)


def _published_directories(runtime: _ControlledTargetRuntime) -> list[Path]:
    return sorted(p for p in runtime.private_root.iterdir()
                  if p.name.startswith("gen-"))


# ============================================================== POSITIVE CHAIN
def test_codex_sandbox_mode_fragment_planned_and_applied_to_confirmed(tmp_path):
    """Codex ``sandbox_mode`` fragment: plan -> apply -> query/reconcile on
    the REAL service over the REAL point, against an observed (0,1,0)
    installation. The platform's own ``Confirmed`` carries the readback."""
    surface = _codex_surface()
    brand = _CODEX_BRAND
    observer = _observed(brand["harness"], brand["native"])
    fragment = _fragment("codex", brand["fragment_value"])
    with _host_service(tmp_path, surface=surface, brand=brand,
                       observer=observer) as (service, runtime, journal,
                                              permits, host):
        planned = service.plan(TARGET, (fragment,), "rev-1")
        assert isinstance(planned, Plan), planned
        assert planned.target == TARGET
        assert len(planned.desired_digest) == 64

        confirmed = service.apply(planned.plan_id, "op-codex-1", "permit-1")
        assert isinstance(confirmed, Confirmed), confirmed
        # the permit was spent once, on the platform's own Plan object
        assert permits.calls == [(PRINCIPAL, TARGET, "Plan", "op-codex-1",
                                  "permit-1")]
        assert confirmed.native_session_identity == "q5:t022:native-session-1"
        assert confirmed.applied_revision == "rev-2"
        assert confirmed.runtime_generation == TARGET.runtime_generation
        assert confirmed.verification_evidence_ref == "q5:t022:readback-evidence"
        assert confirmed.resource_changes == ("private/codex-settings.toml",)

        # query/reconcile read the durable ledger — same identity, no replay
        record = service.query("op-codex-1")
        assert isinstance(record, OperationRecord)
        assert record.result == confirmed
        assert record.operation_id == confirmed.operation_id
        assert service.reconcile("op-codex-1") == confirmed

        # application path: the PLATFORM wrote exactly one private gen-* dir
        published = _published_directories(runtime)
        assert len(published) == 1 and len(runtime.activated) == 1
        landed = tomllib.loads(
            (published[0] / "private" / "codex-settings.toml")
            .read_bytes().decode("utf-8"))
        assert landed == brand["expected_document"]
        # the fragment/claim identity the service admitted: the platform
        # merged and published precisely this claim path under the claimed
        # file target of THIS facet's descriptor
        assert surface._compiled == ((("sandbox_mode",), "workspace-write"),)
        assert surface.descriptor.adapter_versions.contains(
            observer.describe_installation().adapter_version) is True


def test_claude_bash_sandbox_fragment_planned_and_applied_to_confirmed(tmp_path):
    """Claude Bash-sandbox toggle fragment through the same real chain;
    landed bytes are JSON and the adapter's verify Match is what allowed the
    platform to confirm."""
    surface = _claude_surface()
    brand = _CLAUDE_BRAND
    observer = _observed(brand["harness"], brand["native"])
    fragment = _fragment("claude-code", brand["fragment_value"])
    with _host_service(tmp_path, surface=surface, brand=brand,
                       observer=observer) as (service, runtime, *_extra):
        planned = service.plan(TARGET, (fragment,), "rev-1")
        assert isinstance(planned, Plan), planned
        confirmed = service.apply(planned.plan_id, "op-claude-1", "permit-1")
        assert isinstance(confirmed, Confirmed), confirmed
        published = _published_directories(runtime)
        assert len(published) == 1
        landed = json.loads(
            (published[0] / "private" / "claude-settings.json")
            .read_bytes().decode("utf-8"))
        assert landed == brand["expected_document"]
        assert surface._compiled == ((("bashSandbox",), True),)
        assert service.reconcile("op-claude-1") == confirmed


def test_plan_alone_registers_intents_without_writing_anything(tmp_path):
    """Plan is effect-free: no generation directory appears and no durable
    operation exists until apply spends a permit."""
    surface = _codex_surface()
    brand = _CODEX_BRAND
    observer = _observed(brand["harness"], brand["native"])
    with _host_service(tmp_path, surface=surface, brand=brand,
                       observer=observer) as (service, runtime, _j, _p, _h):
        planned = service.plan(TARGET,
                               (_fragment("codex", brand["fragment_value"]),),
                               "rev-1")
        assert isinstance(planned, Plan)
        assert list(runtime.private_root.iterdir()) == []
        assert runtime.activated == []
        assert isinstance(service.query("op-not-applied"), NotFound)


def test_inspect_reports_platform_capability_at_observed_pin(tmp_path):
    """The platform's own capability answer for the observed installation:
    ``set`` supported with the injected evidence ref, ``reset`` unknown with
    a reason — the facet never self-certifies."""
    surface = _codex_surface()
    brand = _CODEX_BRAND
    observer = _observed(brand["harness"], brand["native"])
    with _host_service(tmp_path, surface=surface, brand=brand,
                       observer=observer) as (service, *_rest):
        capabilities = service.inspect(TARGET)
        assert isinstance(capabilities, ConfigurationCapabilities)
        by_operation = {item.operation: item for item in
                        capabilities.capabilities}
        set_cap = by_operation["set"]
        assert set_cap.status == "supported"
        assert set_cap.facet_id == SANDBOX_FACET_ID
        assert set_cap.harness_id == "codex"
        assert set_cap.native_version == (2, 0, 0)
        assert set_cap.adapter_version == (0, 1, 0)
        assert set_cap.evidence_ref == "q5:t022:capability-evidence"
        assert by_operation["reset"].status == "unknown"
        assert by_operation["reset"].reason


def test_resubmit_of_the_same_operation_key_never_repeats_the_effect(tmp_path):
    """Idempotency is the platform journal's (one-active fence + replay of
    the durable result): the second apply returns the recorded Confirmed
    without a second publication or a second permit spend."""
    surface = _codex_surface()
    brand = _CODEX_BRAND
    observer = _observed(brand["harness"], brand["native"])
    with _host_service(tmp_path, surface=surface, brand=brand,
                       observer=observer) as (service, runtime, _j, permits,
                                              _h):
        planned = service.plan(TARGET,
                               (_fragment("codex", brand["fragment_value"]),),
                               "rev-1")
        first = service.apply(planned.plan_id, "op-once", "permit-1")
        second = service.apply(planned.plan_id, "op-once", "permit-2")
        assert isinstance(first, Confirmed) and second == first
        assert len(runtime.activated) == 1
        assert len(_published_directories(runtime)) == 1
        assert len(permits.calls) == 1


# ================================================================= NEGATIVES
def test_observed_adapter_version_mismatch_is_refused_by_the_platform(tmp_path):
    """The (1,0,0) installation the ONLY in-tree observer publishes
    (fixture __init__.py:69) vs this facet's exact (0,1,0) descriptor pin
    (points.py:72 / pyproject.toml:7): the platform's joint gate
    (configuration_service.py:153) REFUSES. No widening, no fake admission."""
    surface = _codex_surface()
    brand = _CODEX_BRAND
    mismatched = _observed(brand["harness"], brand["native"],
                           FIXTURE_OBSERVED_ADAPTER_VERSION)
    with _host_service(tmp_path, surface=surface, brand=brand,
                       observer=mismatched) as (service, runtime, *_r):
        result = service.plan(TARGET,
                              (_fragment("codex", brand["fragment_value"]),),
                              "rev-1")
        assert not isinstance(result, Plan)
        assert isinstance(result, Refused)
        assert result.code is ErrorCode.CAPABILITY_UNSUPPORTED
        assert result.original_state_preserved is True
        assert list(runtime.private_root.iterdir()) == []


def test_unobserved_native_version_refuses_with_version_unverified(tmp_path):
    """A missing observation (native_version None) is the platform's
    `version-unverified` refusal (configuration_service.py:148-149), never a
    guess and never a confirmation."""
    surface = _codex_surface()
    brand = _CODEX_BRAND
    observer = _observed(brand["harness"], None)
    with _host_service(tmp_path, surface=surface, brand=brand,
                       observer=observer) as (service, *_r):
        result = service.plan(TARGET,
                              (_fragment("codex", brand["fragment_value"]),),
                              "rev-1")
        assert isinstance(result, Refused)
        assert result.code is ErrorCode.VERSION_UNVERIFIED


def test_unknown_harness_identity_is_refused_by_the_platform(tmp_path):
    """Harness-identity is checked on the same gate line
    (configuration_service.py:151): an observation of a harness this facet
    was not authored for is a platform refusal."""
    surface = _codex_surface()
    brand = _CODEX_BRAND
    observer = _observed("unknown-harness", brand["native"])
    with _host_service(tmp_path, surface=surface, brand=brand,
                       observer=observer) as (service, *_r):
        result = service.plan(TARGET,
                              (_fragment("codex", brand["fragment_value"]),),
                              "rev-1")
        assert isinstance(result, Refused)
        assert result.code is ErrorCode.CAPABILITY_UNSUPPORTED


def test_absent_facet_on_the_real_point_refuses_with_adapter_missing(tmp_path):
    """The platform's unavailable outcome for a non-selectable facet: the
    REAL ``SandboxAdaptersServerPlugin`` publishes three descriptors on one
    open point, which the host resolves to an observable absence
    (contribution_points.py resolve; recorded in t020) -> the service
    answers ``Refused(adapter-missing)``, never a guessed selection."""
    from ordessa_server.bootstrap import build_runtime
    host_runtime = build_runtime(tmp_path / "host")
    try:
        host = host_runtime.plugin_host
        host.activate(SandboxAdaptersServerPlugin())
        service, runtime, _j, _p = _service(
            tmp_path, brand=_CODEX_BRAND,
            observer=_observed("codex", (2, 0, 0)), carrier=host)
        result = service.plan(TARGET,
                              (_fragment("codex",
                                         _CODEX_BRAND["fragment_value"]),),
                              "rev-1")
        assert isinstance(result, Refused)
        assert result.code is ErrorCode.ADAPTER_MISSING
        assert list(runtime.private_root.iterdir()) == []
    finally:
        host_runtime.stop()


def test_stale_expected_revision_refuses_before_any_effect(tmp_path):
    surface = _codex_surface()
    brand = _CODEX_BRAND
    with _host_service(tmp_path, surface=surface, brand=brand,
                       observer=_observed(brand["harness"],
                                          brand["native"])) as (service, *_r):
        result = service.plan(TARGET,
                              (_fragment("codex", brand["fragment_value"]),),
                              "rev-OTHER")
        assert isinstance(result, Refused)
        assert result.code is ErrorCode.STALE_PLAN


def test_fragment_whose_claim_was_not_admitted_is_refused(tmp_path):
    """A locally defined adapter whose compile emits a SetField OUTSIDE its
    descriptor's registered claims: the platform's claim ceiling
    (configuration_service.py:196-197) refuses with ``invalid-fragment`` —
    the adapter's own words are never the authority."""

    class _OverreachingAdapter:
        descriptor = ConfigurationAdapterDescriptor(
            "q5.t022.overreaching", "v1", SANDBOX_FACET_ID,
            SANDBOX_FACET_SCHEMA_VERSION, "codex",
            VersionRange((2, 0, 0), (2, 0, 0)),
            VersionRange((0, 1, 0), (0, 1, 0)), ("sandbox_mode",),
            ValueSchema("object",
                        properties=(("sandbox_mode", ValueSchema("string")),),
                        required=("sandbox_mode",)),
            (FieldClaim("file", "codex-config-toml", ("sandbox_mode",)),))

        def assess(self, context, request):
            return Assessment("supported", evidence_ref="q5:t022:controlled")

        def compile(self, context, before, desired):
            handle = context.targets[0].handle
            return IntentSet((SetField(
                IntentSource(SANDBOX_FACET_ID, sandbox_item_id("codex"),
                             SANDBOX_FACET_SCHEMA_VERSION),
                handle, FieldPath(("shell",)), "/bin/bash"),))

        def verify(self, context, observed):  # pragma: no cover
            raise AssertionError("the claim ceiling refuses before verify")

    carrier = _SingleViewCarrier(payload=_OverreachingAdapter())
    service, runtime, _j, _p = _service(
        tmp_path, brand=_CODEX_BRAND,
        observer=_observed("codex", (2, 0, 0)), carrier=carrier)
    result = service.plan(TARGET,
                          (_fragment("codex", {"sandbox_mode": "read-only"}),),
                          "rev-1")
    assert not isinstance(result, Plan)
    assert isinstance(result, Refused)
    assert result.code is ErrorCode.INVALID_FRAGMENT
    assert any("intent exceeds registered claims" in line
               for line in result.diagnostics)
    assert list(runtime.private_root.iterdir()) == []


def test_required_coverage_the_observation_cannot_show_never_confirms(tmp_path):
    """Claude's observed mechanism covers Bash only; a fragment whose intent
    requires READ coverage is refused at plan with the platform's
    ``capability-unsupported`` carrying THIS facet's stable
    ``SANDBOX_COVERAGE_UNPROVEN`` code — and nothing reaches Confirmed or a
    write."""
    surface = _claude_surface(required_coverage=frozenset(
        {ToolCategory.BASH, ToolCategory.READ}))
    brand = _CLAUDE_BRAND
    with _host_service(tmp_path, surface=surface, brand=brand,
                       observer=_observed(brand["harness"],
                                          brand["native"])) as (service,
                                                                 runtime,
                                                                 *_r):
        result = service.plan(TARGET,
                              (_fragment("claude-code",
                                         brand["fragment_value"]),), "rev-1")
        assert isinstance(result, Refused)
        assert not isinstance(result, (Confirmed, Unknown))
        assert result.code is ErrorCode.CAPABILITY_UNSUPPORTED
        assert sandbox_code_of(result.diagnostics[0]) is \
            SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN
        assert list(runtime.private_root.iterdir()) == []


def test_native_receipt_drift_never_confirms_and_reconciles_unknown(tmp_path):
    """An effect the readback cannot honour (value drift -> the adapter
    answers Mismatch, configuration_service.py:303-305) leaves the durable
    result ``Unknown`` (:312-320), NEVER ``Confirmed``. Reopening the service
    on the same journal reconciles to the SAME Unknown without replaying,
    and a restart apply of the old plan refuses (no silent re-spend)."""
    brand = _CODEX_BRAND
    observer = _observed(brand["harness"], brand["native"])
    journal_path = tmp_path / "journal.sqlite"
    journal = OperationJournal(journal_path)
    surface = _codex_surface()
    from ordessa_server.bootstrap import build_runtime
    host_runtime = build_runtime(tmp_path / "host")
    try:
        host = host_runtime.plugin_host
        host.activate(_FacetPlugin(surface))
        service, runtime, _j, _p = _service(
            tmp_path, brand=brand, observer=observer, tamper="value",
            carrier=host, journal=journal)
        planned = service.plan(TARGET,
                               (_fragment("codex",
                                          brand["fragment_value"]),), "rev-1")
        assert isinstance(planned, Plan)
        outcome = service.apply(planned.plan_id, "op-drift", "permit-1")
        assert isinstance(outcome, Unknown), outcome
        assert not isinstance(outcome, Confirmed)
        assert outcome.phase == "verifying"
        assert outcome.allowed_next_action == "reconcile"
        record = service.query("op-drift")
        assert isinstance(record, OperationRecord)
        assert record.result == outcome
        assert service.reconcile("op-drift") == outcome

        # "restart": a fresh service over the SAME durable journal
        service2, runtime2, _j2, _p2 = _service(
            tmp_path, brand=brand, observer=observer, carrier=host,
            journal=OperationJournal(journal_path))
        assert service2.reconcile("op-drift") == outcome
        replay = service2.apply(planned.plan_id, "op-drift", "permit-x")
        assert isinstance(replay, Refused)
        assert replay.code is ErrorCode.STALE_PLAN
        assert runtime2.activated == []
    finally:
        host_runtime.stop()


def test_tampered_readback_manifest_is_refused_confirmation(tmp_path):
    """Even a digest-manifest lie at observation time (files != lease.files,
    configuration_service.py:301-302) produces ``Unknown`` — the platform
    never takes an unverified receipt as ``Confirmed``."""
    brand = _CODEX_BRAND
    surface = _codex_surface()
    with _host_service(tmp_path, surface=surface, brand=brand,
                       observer=_observed(brand["harness"], brand["native"]),
                       tamper="files") as (service, runtime, *_r):
        planned = service.plan(TARGET,
                               (_fragment("codex",
                                          brand["fragment_value"]),), "rev-1")
        outcome = service.apply(planned.plan_id, "op-tamper", "permit-1")
        assert isinstance(outcome, Unknown)
        assert not isinstance(outcome, Confirmed)


# ==================================================================== PURITY
class _IoWindow:
    """Frame-classifying recorder: every open/os.open during the window is
    attributed to the FIRST package-source frame that triggered it; spawn
    and socket calls are counted at all. Nothing is blocked — the platform
    legitimately writes through the injected temp target; what must be zero
    is any I/O, spawn or socket performed on behalf of
    ``ordessa_sandbox_adapters`` itself."""

    def __init__(self) -> None:
        self.package_dir = str(Path(adapters_package.__file__).parent)
        self.package_origins: list[str] = []
        self.spawn_calls = 0
        self.socket_calls = 0
        self.total_opens = 0
        #: non-vacuity: the platform MUST have opened files during the chain
        self.os_open_calls = 0

    def _origin(self) -> str | None:
        for frame in traceback.extract_stack():
            if str(frame.filename).startswith(self.package_dir):
                return f"{Path(frame.filename).name}:{frame.lineno}"
        return None

    def _src_fingerprint(self) -> dict:
        return {p.name: os.stat(p)
                for p in Path(self.package_dir).glob("*.py")}


def test_my_package_performs_no_io_during_the_plan_and_apply_chain(tmp_path,
                                                                   monkeypatch):
    brand = _CODEX_BRAND
    surface = _codex_surface()
    observer = _observed(brand["harness"], brand["native"])
    from ordessa_server.bootstrap import build_runtime
    host_runtime = build_runtime(tmp_path / "host")
    try:
        host = host_runtime.plugin_host
        host.activate(_FacetPlugin(surface))
        service, runtime, _j, _p = _service(
            tmp_path, brand=brand, observer=observer, carrier=host)

        window = _IoWindow()
        real_open, real_os_open = builtins.open, os.open
        real_popen, real_socket = subprocess.Popen, socket.socket

        def spy_open(*args, **kwargs):
            window.total_opens += 1
            origin = window._origin()
            if origin:
                window.package_origins.append(f"open:{origin}")
            return real_open(*args, **kwargs)

        def spy_os_open(*args, **kwargs):
            window.os_open_calls += 1
            origin = window._origin()
            if origin:
                window.package_origins.append(f"os.open:{origin}")
            return real_os_open(*args, **kwargs)

        def spy_popen(*args, **kwargs):
            window.spawn_calls += 1
            return real_popen(*args, **kwargs)

        def spy_socket(*args, **kwargs):
            window.socket_calls += 1
            return real_socket(*args, **kwargs)

        monkeypatch.setattr(builtins, "open", spy_open)
        monkeypatch.setattr(os, "open", spy_os_open)
        monkeypatch.setattr(subprocess, "Popen", spy_popen)
        monkeypatch.setattr(socket, "socket", spy_socket)

        before = window._src_fingerprint()
        fragment = _fragment("codex", brand["fragment_value"])
        planned = service.plan(TARGET, (fragment,), "rev-1")
        confirmed = service.apply(planned.plan_id, "op-purity", "permit-1")
        query = service.query("op-purity")
        reconcile = service.reconcile("op-purity")
        after = window._src_fingerprint()

        assert isinstance(confirmed, Confirmed), confirmed
        # the spies sat in the real call path (no vacuous zero-origin):
        assert window.os_open_calls > 0
        # MY PACKAGE performed no I/O itself during the whole chain:
        assert window.package_origins == []
        assert window.spawn_calls == 0 and window.socket_calls == 0
        assert before == after
        # the only writes are the PLATFORM's, into the injected temp target
        assert len(_published_directories(runtime)) == 1
        assert isinstance(query, OperationRecord) and query.result == reconcile
    finally:
        monkeypatch.undo()
        host_runtime.stop()
