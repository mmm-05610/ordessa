"""The managed environment capability model: statuses, requirements, digest.

These cases exercise the model itself and its wiring into the managed path
(``BackendObservation`` -> store -> ``EnvironmentSnapshot``/``EnvironmentUse``).
The retired legacy ``Capabilities`` / ``require_guarantees`` shape is asserted
absent in ``test_contract_surface.py``; here the legacy *object shape* is
proven to be refused rather than accepted.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ordessa_environments import (
    BYTE_CHANNEL_CAPABILITY,
    CAPABILITY_KEYS,
    FILE_AREA_CAPABILITY,
    OUTBOUND_NETWORK_CAPABILITY,
    PROCESS_CAPABILITY,
    STREAMING_STDERR_CAPABILITY,
    TERMINAL_CAPABILITY,
    BackendNotFound,
    BackendObservation,
    CapabilityReport,
    CapabilityStatus,
    EnvironmentGuaranteeUnmet,
    EnvironmentManager,
    EnvironmentRefused,
    SQLiteEnvironmentStore,
    require_capabilities,
)
from ordessa_environments.management.store import decode_observation, encode_observation


def report(values=None, **overrides):
    base = dict(
        values=values if values is not None else {PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED},
        isolation="none",
        assurance="provider_self_report",
    )
    base.update(overrides)
    return CapabilityReport(**base)


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------

def test_status_vocabulary_is_the_four_agreed_values():
    assert {status.value for status in CapabilityStatus} == {
        "supported", "conditional", "unavailable", "unsupported",
    }
    assert all(isinstance(status, str) for status in CapabilityStatus)


def test_capability_keys_are_the_five_legacy_keys_plus_outbound_network():
    assert OUTBOUND_NETWORK_CAPABILITY == "outbound-network"
    assert CAPABILITY_KEYS == frozenset({
        PROCESS_CAPABILITY, BYTE_CHANNEL_CAPABILITY, FILE_AREA_CAPABILITY,
        STREAMING_STDERR_CAPABILITY, TERMINAL_CAPABILITY, OUTBOUND_NETWORK_CAPABILITY,
    })


def test_report_rejects_unknown_keys_and_non_status_values():
    with pytest.raises(EnvironmentRefused):
        report({"invented-capability": CapabilityStatus.SUPPORTED})
    with pytest.raises(EnvironmentRefused):
        report({PROCESS_CAPABILITY: "supported"})
    with pytest.raises(EnvironmentRefused):
        report({"": CapabilityStatus.SUPPORTED})
    with pytest.raises(EnvironmentRefused):
        report({PROCESS_CAPABILITY + "x" * 200: CapabilityStatus.SUPPORTED})


def test_report_bounds_isolation_assurance_affinity_and_details():
    report()  # empty affinity and details are valid
    with pytest.raises(EnvironmentRefused):
        report(isolation="")
    with pytest.raises(EnvironmentRefused):
        report(assurance="")
    with pytest.raises(EnvironmentRefused):
        report(isolation="x" * 65)
    with pytest.raises(EnvironmentRefused):
        report(affinity="x" * 257)
    with pytest.raises(EnvironmentRefused):
        report(details={"fact": 1})
    with pytest.raises(EnvironmentRefused):
        report(details={"fact": "x" * 513})
    with pytest.raises(EnvironmentRefused):
        report(details={f"fact-{index}": "value" for index in range(33)})


def test_provides_is_the_derived_supported_view():
    value = report({
        PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED,
        FILE_AREA_CAPABILITY: CapabilityStatus.CONDITIONAL,
        TERMINAL_CAPABILITY: CapabilityStatus.UNSUPPORTED,
        OUTBOUND_NETWORK_CAPABILITY: CapabilityStatus.UNAVAILABLE,
    })
    assert value.provides == frozenset({PROCESS_CAPABILITY})


# ---------------------------------------------------------------------------
# digest stability
# ---------------------------------------------------------------------------

def test_report_digest_is_stable_and_content_addressed():
    first = report({PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED,
                    FILE_AREA_CAPABILITY: CapabilityStatus.CONDITIONAL})
    reordered = report({FILE_AREA_CAPABILITY: CapabilityStatus.CONDITIONAL,
                        PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED})
    assert first.digest == reordered.digest
    assert first.digest == first.digest

    assert first.digest != report(
        {PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED,
         FILE_AREA_CAPABILITY: CapabilityStatus.SUPPORTED}).digest
    assert first.digest != report(
        {PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED,
         FILE_AREA_CAPABILITY: CapabilityStatus.CONDITIONAL},
        isolation="container").digest
    assert first.digest != report(
        {PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED,
         FILE_AREA_CAPABILITY: CapabilityStatus.CONDITIONAL},
        details={"root": "/srv"}).digest


# ---------------------------------------------------------------------------
# requirement semantics
# ---------------------------------------------------------------------------

def test_supported_passes_by_default():
    require_capabilities(report(), [PROCESS_CAPABILITY])


def test_conditional_requires_explicit_opt_in():
    value = report({FILE_AREA_CAPABILITY: CapabilityStatus.CONDITIONAL})
    with pytest.raises(EnvironmentGuaranteeUnmet):
        require_capabilities(value, [FILE_AREA_CAPABILITY])
    require_capabilities(value, [FILE_AREA_CAPABILITY], accept_conditional=True)


@pytest.mark.parametrize("status", [CapabilityStatus.UNAVAILABLE, CapabilityStatus.UNSUPPORTED])
def test_unavailable_and_unsupported_always_refuse(status):
    value = report({TERMINAL_CAPABILITY: status})
    for accept in (False, True):
        with pytest.raises(EnvironmentGuaranteeUnmet):
            require_capabilities(value, [TERMINAL_CAPABILITY], accept_conditional=accept)


def test_absent_key_refuses_and_the_missing_keys_are_reported():
    value = report({PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED})
    with pytest.raises(EnvironmentGuaranteeUnmet) as caught:
        require_capabilities(value, [PROCESS_CAPABILITY, TERMINAL_CAPABILITY, FILE_AREA_CAPABILITY])
    assert "terminal" in str(caught.value) and "files" in str(caught.value)
    assert "process" not in str(caught.value).split("does not provide")[1]


def test_requirement_policy_and_report_type_are_explicit():
    with pytest.raises(EnvironmentRefused):
        require_capabilities(report(), [PROCESS_CAPABILITY], accept_conditional=1)
    with pytest.raises(EnvironmentRefused):
        require_capabilities(
            SimpleNamespace(provides=frozenset({PROCESS_CAPABILITY}), detail={}),
            [PROCESS_CAPABILITY],
        )
    with pytest.raises(EnvironmentRefused):
        require_capabilities(report(), [""])


# ---------------------------------------------------------------------------
# observations and uses
# ---------------------------------------------------------------------------

class ControlledProvider:
    identity = "controlled"
    binding_id = "controlled-capability-scope"
    operations = frozenset()

    def __init__(self):
        self.observed = CapabilityReport(
            {PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED,
             FILE_AREA_CAPABILITY: CapabilityStatus.CONDITIONAL,
             TERMINAL_CAPABILITY: CapabilityStatus.UNAVAILABLE},
            "controlled", "provider_self_report", "",
            {"resourceKind": "directory"},
        )

    def inspect(self, backend_id):
        return BackendObservation(backend_id, "running", self.observed,
            datetime.now(timezone.utc).isoformat(), endpoint_kind="local", health="ready")

    def create(self, reference, *, operation_id):
        return self.inspect("immutable-backend")

    def open_use(self, backend_id, **kwargs):
        return SimpleNamespace(
            files=SimpleNamespace(root=lambda: "/controlled"),
            execution=SimpleNamespace(start=lambda request: None),
            release=lambda: {"resourcePreserved": True},
        )


def test_observation_and_store_carry_the_report(tmp_path):
    provider = ControlledProvider()
    manager = EnvironmentManager(
        store=SQLiteEnvironmentStore(tmp_path / "environments.db"),
        providers={provider.identity: provider},
    )
    instance = manager.create(provider.identity, {})
    snapshot = instance.snapshot
    assert snapshot.observation.capabilities == provider.observed
    assert snapshot.observation.endpoint_kind == "local"
    assert snapshot.observation.health == "ready"

    # The report survives a fresh manager reading the same database.
    cold = EnvironmentManager(
        store=SQLiteEnvironmentStore(tmp_path / "environments.db"),
        providers={provider.identity: provider},
    )
    assert cold.get(instance.identity).snapshot.observation.capabilities == provider.observed


def test_use_exposes_a_report_and_inherits_the_confirmed_observation(tmp_path):
    provider = ControlledProvider()
    manager = EnvironmentManager(
        store=SQLiteEnvironmentStore(tmp_path / "environments.db"),
        providers={provider.identity: provider},
    )
    instance = manager.create(provider.identity, {})
    use = instance.acquire("unit", sharing=False)
    assert isinstance(use.capabilities, CapabilityReport)
    assert use.capabilities == provider.observed
    require_capabilities(use.capabilities, [PROCESS_CAPABILITY])
    with pytest.raises(EnvironmentGuaranteeUnmet):
        require_capabilities(use.capabilities, [FILE_AREA_CAPABILITY])
    require_capabilities(use.capabilities, [FILE_AREA_CAPABILITY], accept_conditional=True)
    use.release()


def test_a_live_use_may_refine_the_confirmed_observation_report(tmp_path):
    provider = ControlledProvider()
    refined = CapabilityReport(
        {PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED,
         FILE_AREA_CAPABILITY: CapabilityStatus.SUPPORTED},
        "controlled", "provider_self_report",
    )
    provider.open_use = lambda backend_id, **kwargs: SimpleNamespace(
        capabilities=refined,
        files=SimpleNamespace(root=lambda: "/controlled"),
        execution=SimpleNamespace(start=lambda request: None),
        release=lambda: {"resourcePreserved": True},
    )
    manager = EnvironmentManager(
        store=SQLiteEnvironmentStore(tmp_path / "environments.db"),
        providers={provider.identity: provider},
    )
    instance = manager.create(provider.identity, {})
    use = instance.acquire("unit", sharing=False)
    assert use.capabilities == refined
    assert use.capabilities.provides == frozenset({PROCESS_CAPABILITY, FILE_AREA_CAPABILITY})
    use.release()


def test_observation_refuses_a_legacy_capabilities_object():
    with pytest.raises(EnvironmentRefused):
        BackendObservation("backend", "running",
            SimpleNamespace(provides=frozenset({PROCESS_CAPABILITY}), detail={}),
            datetime.now(timezone.utc).isoformat())


@pytest.mark.parametrize("field,value", [("endpoint_kind", "tunnel"), ("health", "green")])
def test_observation_bounds_endpoint_kind_and_health(field, value):
    kwargs = {field: value}
    with pytest.raises(EnvironmentRefused):
        BackendObservation("backend", "running", report(),
            datetime.now(timezone.utc).isoformat(), **kwargs)


def test_schema1_json_without_statuses_decodes_as_supported():
    legacy = ('{"backend_id": "backend", "state": "running", "observed_at": "now", '
              '"isolation": "none", "provides": ["process", "files"], '
              '"detail": {"resourceKind": "directory", "perProcessStop": false, "restartCount": 0}}')
    observation = decode_observation(legacy)
    assert observation.capabilities.values == {
        PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED,
        FILE_AREA_CAPABILITY: CapabilityStatus.SUPPORTED,
    }
    # Legacy free-form detail scalars read back as their canonical JSON spelling.
    assert observation.capabilities.details == {
        "resourceKind": "directory", "perProcessStop": "false", "restartCount": "0",
    }
    assert observation.endpoint_kind == "local" and observation.health == "unknown"
    assert encode_observation(observation).count('"values"')


def test_encode_requires_an_actual_observation():
    with pytest.raises(EnvironmentRefused):
        encode_observation(object())
    with pytest.raises(EnvironmentRefused):
        encode_observation(BackendObservation("", "running", report(),
            datetime.now(timezone.utc).isoformat()))
