"""Environment admission around the opaque managed transport lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from ordessa_environment_api import AdmissionRefusedError, RequestKey
from ordessa_environment_api.guarantee import GuaranteeLevel
from pacthold.core.registration import CoreContributionSet
from pacthold.environment import Environment, InstallationRecord
from ordessa_server_product.composition import ServerProductComposition
from ordessa_server_product.managed_transport import EnvironmentManagedTransport


@dataclass(frozen=True)
class _Start:
    contract_id = "native.channel-start@1"


@dataclass(frozen=True)
class _Write:
    contract_id = "native.channel-write@1"


@dataclass(frozen=True)
class _Release:
    contract_id = "native.channel-release@1"


class _Policy:
    def admit_invoke(self, principal: str, surface: str, guarantee: str) -> bool:
        return principal == "local" and guarantee == "raw"

    def admit_object_access(self, principal: str, object_ref: str, mode: str) -> bool:
        return True


class _Transport:
    def __init__(self, *, start_error=None, write_error=None, release=None):
        self.start_error = start_error
        self.write_error = write_error
        self.release = release or {"confirmed": True, "reason": "released", "report": {"released": True}}
        self.starts = 0
        self.lines = []
        self.releases = 0
        self.terminations = 0
        self.pid = 4321
        self.established = False
        self.configuration_profile_snapshot = None

    def start(self):
        self.starts += 1
        if self.start_error:
            raise self.start_error
        self.established = True
        return self

    def send_line(self, text):
        self.lines.append(text)
        if self.write_error:
            raise self.write_error

    def request_release(self):
        self.releases += 1
        return self.release

    def terminate(self):
        self.terminations += 1


def _environment(environment_id: str, *, policy=None) -> Environment:
    environment = Environment(environment_id, policy=policy)
    environment.install(InstallationRecord("native.transport", "a" * 64))
    environment.enable("native.transport")
    receipt = environment.activate("native.transport", CoreContributionSet(contracts=(_Start, _Write, _Release)))
    environment.native_channel_activation = receipt.activation
    return environment


def test_missing_policy_refuses_start_and_write_before_external_effects():
    environment = _environment("env-transport-denied")
    transport = _Transport()

    with pytest.raises(AdmissionRefusedError):
        EnvironmentManagedTransport.open(environment, transport)
    with pytest.raises(AdmissionRefusedError):
        EnvironmentManagedTransport(environment, transport).send_line('{"method":"session/prompt"}')

    assert transport.starts == 0
    assert transport.lines == []


def test_admitted_start_write_and_release_call_concrete_transport_once():
    environment = _environment("env-transport-allowed", policy=_Policy())
    transport = _Transport()
    managed = EnvironmentManagedTransport.open(environment, transport)
    managed.send_line("immutable line")
    receipt = managed.request_release()

    assert transport.starts == 1
    assert transport.lines == ["immutable line"]
    assert transport.releases == 1
    assert receipt == transport.release
    assert managed.pid == 4321
    assert managed.established is True


@pytest.mark.parametrize("failed_operation", ["start", "write"])
def test_transport_error_is_unknown_and_wrapper_does_not_resend(monkeypatch, failed_operation):
    environment = _environment(f"env-transport-{failed_operation}-unknown", policy=_Policy())
    transport = _Transport(
        start_error=RuntimeError("connect reply lost") if failed_operation == "start" else None,
        write_error=RuntimeError("write reply lost") if failed_operation == "write" else None,
    )
    if failed_operation == "start":
        request_suffix = "fixed-start-request"
        monkeypatch.setattr(
            "ordessa_server_product.managed_transport.uuid4",
            lambda: SimpleNamespace(hex=request_suffix),
        )
        with pytest.raises(RuntimeError, match="connect reply lost") as failure:
            EnvironmentManagedTransport.open(environment, transport)
    else:
        managed = EnvironmentManagedTransport.open(environment, transport)
        request_suffix = "fixed-write-request"
        monkeypatch.setattr(
            "ordessa_server_product.managed_transport.uuid4",
            lambda: SimpleNamespace(hex=request_suffix),
        )
        with pytest.raises(RuntimeError, match="write reply lost"):
            managed.send_line("possible partial write")

    request = RequestKey(
        environment_namespace=environment.environment_id,
        principal_scope="local",
        request_id="managed-transport-" + request_suffix,
        comparison={"operation": failed_operation},
    )
    fact = environment.query(request)
    assert transport.starts == 1
    assert transport.lines == ([] if failed_operation == "start" else ["possible partial write"])
    assert fact is not None
    assert fact[0].delivery == "unknown"
    assert fact[1].outcome == "unknown"
    if failed_operation == "start":
        # The caller still owns the exact transport and Environment. Start is
        # uncertain, so the failure carries pending closure responsibility.
        pending = failure.value.pending_closure
        assert pending.environment is environment
        assert pending.activation == environment.native_channel_activation
        assert pending.transport._transport is transport
        assert pending.request == request
        assert pending.activity == fact


def test_release_unknown_receipt_keeps_native_identity_visible():
    environment = _environment("env-transport-release-unknown", policy=_Policy())
    transport = _Transport(release={
        "confirmed": False, "reason": "close-timeout", "report": None,
    })
    managed = EnvironmentManagedTransport.open(environment, transport)
    receipt = managed.request_release()

    assert receipt == {"confirmed": False, "reason": "close-timeout", "report": None}
    assert managed.established is True
    assert managed.pid == 4321
    assert transport.releases == 1


def test_transport_callbacks_are_explicitly_raw(monkeypatch):
    environment = _environment("env-transport-raw", policy=_Policy())
    original_invoke = environment.invoke
    guarantees = []

    def record_invoke(*args, **kwargs):
        guarantees.append(kwargs["guarantee"])
        return original_invoke(*args, **kwargs)

    monkeypatch.setattr(environment, "invoke", record_invoke)
    transport = _Transport()
    managed = EnvironmentManagedTransport.open(environment, transport)
    managed.send_line("line")
    managed.request_release()

    assert guarantees == [GuaranteeLevel.RAW] * 3


def _runtime_for(environment):
    return SimpleNamespace(core_binding=SimpleNamespace(environment=environment))


def test_unknown_start_blocks_activation_retirement():
    environment = _environment("env-transport-retirement-block", policy=_Policy())
    composition = ServerProductComposition()
    transport = _Transport(start_error=RuntimeError("connect reply lost"))

    with pytest.raises(RuntimeError, match="outcome unknown") as failure:
        composition._admit_native_transport(_runtime_for(environment), transport)

    pending = failure.value.pending_closure
    assert pending.activation == environment.native_channel_activation
    assert transport.starts == 1
    assert environment.settlements(
        pending.activation.plugin_id, pending.activation.generation,
    ) == ("native-channel-start-unknown:" + pending.request.request_id,)
    state, blockers = environment.retire_activation(pending.activation)
    assert state == "retire-pending"
    assert any(blocker.startswith("unclassified-deliveries:") for blocker in blockers)


def test_pending_start_can_be_explicitly_released_after_retire_pending():
    environment = _environment("env-transport-controlled-close", policy=_Policy())
    composition = ServerProductComposition()
    transport = _Transport(
        start_error=RuntimeError("connect reply lost"),
        release={"confirmed": False, "reason": "close-timeout", "report": None},
    )

    with pytest.raises(RuntimeError, match="outcome unknown") as failure:
        composition._admit_native_transport(_runtime_for(environment), transport)
    request_id = failure.value.pending_closure.request.request_id

    unconfirmed = composition.release_pending_native_transport(request_id)
    assert unconfirmed["confirmed"] is False
    state, blockers = environment.retire_activation(environment.native_channel_activation)
    assert state == "retire-pending"
    assert any(blocker.startswith("unclassified-deliveries:") for blocker in blockers)

    # The pending record survives the false receipt. A caller may explicitly
    # ask again after obtaining new native evidence, even after drain; the
    # wrapper does not retry automatically.
    transport.release = {"confirmed": True, "reason": "released", "report": {"released": True}}
    confirmed = composition.release_pending_native_transport(request_id)
    assert confirmed["confirmed"] is True
    state, blockers = environment.retire_activation(environment.native_channel_activation)
    assert state == "retired"
    assert blockers == ()
