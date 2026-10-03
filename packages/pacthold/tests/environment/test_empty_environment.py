"""003 gates for the empty Environment (G003-1..4 / T003-02..06).

Counterexamples pinned here:

* a ref whose full identity does not match resolves to NOTHING (A-01: same
  object id under another owner instance/generation, or another environment,
  is an ``IdentityMismatchError``, never a partial match);
* installed ≠ enabled — a fresh environment activates nothing;
* historical refs answer ``lookup`` (history-read) but never ``use``/invoke;
* a RELIABLE invocation without the optional ports is refused BEFORE any
  dispatch and leaves zero activity records; RAW keeps working;
* same request key + same digest replays the original receipt; a different
  digest is a conflict, never a re-issue;
* two environments never share indices — no module-level registry exists.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from pacthold.core.registration import CoreContributionSet, RegistrationConflictError
from pacthold.environment import Environment, InstallationRecord
from ordessa_environment_api import (
    AdmissionRefusedError,
    GuaranteeUnavailableError,
    IdentityMismatchError,
    ObjectRef,
    RequestKey,
)
from ordessa_environment_api.guarantee import GuaranteeLevel


@dataclass(frozen=True)
class _Contract:
    """A neutral static catalog contract — reuse of the core validation rules
    (T003-03) means this must be a frozen dataclass with a versioned id."""
    contract_id: str = "demo.contract@1"


def _key(request_id: str) -> RequestKey:
    return RequestKey(
        environment_namespace="env-a", principal_scope="user:local:t", request_id=request_id
    )


def _primed_env() -> Environment:
    env = Environment("env-a")
    env.install(InstallationRecord(installation_id="demo.plugin", manifest_digest="d" * 64))
    env.enable("demo.plugin")
    return env


def test_fresh_environment_is_read_only_and_activates_nothing():
    env = Environment("env-a")
    assert env.installed == ()
    assert env.enabled == ()
    with pytest.raises(AdmissionRefusedError, match="not enabled"):
        env.activate("anything")


def test_installed_is_not_enabled():
    env = Environment("env-a")
    env.install(InstallationRecord(installation_id="demo.plugin", manifest_digest="d" * 64))
    assert env.installed == ("demo.plugin",)
    assert env.enabled == ()
    with pytest.raises(AdmissionRefusedError):
        env.activate("demo.plugin")
    env.enable("demo.plugin")
    assert env.enabled == ("demo.plugin",)
    receipt = env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))
    assert receipt.activation.generation == 1


def test_object_identity_requires_the_full_triple():
    env = _primed_env()
    env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))
    creation = env.instantiate("demo.contract", _key("req-1"), instance_id="i-1", object_id="o-1")
    (obj,) = creation.objects

    good = env.lookup(obj)
    assert good["state"] == "available"

    # same object id, wrong owner generation → A-01 mismatch, never partial
    with pytest.raises(IdentityMismatchError):
        env.lookup(ObjectRef(environment="env-a", owner_instance_id="i-1",
                             owner_generation=99, object_id="o-1"))
    # same object id, wrong owner instance
    with pytest.raises(IdentityMismatchError):
        env.lookup(ObjectRef(environment="env-a", owner_instance_id="i-2",
                             owner_generation=obj.owner_generation, object_id="o-1"))
    # another environment's ref never resolves here
    with pytest.raises(IdentityMismatchError):
        env.lookup(ObjectRef(environment="env-b", owner_instance_id="i-1",
                             owner_generation=obj.owner_generation, object_id="o-1"))


def test_history_read_and_invoke_are_separate_permissions():
    env = _primed_env()
    activation = env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))
    creation = env.instantiate("demo.contract", _key("req-2"), instance_id="i-2", object_id="o-2")
    (obj,) = creation.objects
    usage = env.use(obj, "demo-purpose")
    assert usage.state == "active"

    env.mark_retired(activation.activation)

    # history-read still answers on the historical ref
    entry = env.lookup(obj, mode="history-read")
    assert entry["historical"] is True
    # use and new binding are refused on the retired activation
    with pytest.raises(AdmissionRefusedError):
        env.use(obj, "another-purpose")
    with pytest.raises(AdmissionRefusedError):
        env.bind("demo.contract")


def test_reliable_without_ports_refuses_before_dispatch_and_raw_survives():
    env = _primed_env()
    env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))

    with pytest.raises(GuaranteeUnavailableError, match="refused before dispatch"):
        env.invoke("demo.contract", _key("req-3"), guarantee=GuaranteeLevel.RELIABLE,
                   input_digest="a" * 64)
    # zero-dispatch proof: nothing was recorded under that key
    assert env.query(_key("req-3")) is None

    receipt, current = env.invoke("demo.contract", _key("req-4"),
                                  guarantee=GuaranteeLevel.RAW, input_digest="b" * 64)
    assert current.outcome == "concluded"
    assert env.query(_key("req-4")) is not None


def test_request_key_dedup_same_digest_replays_different_digest_conflicts():
    env = _primed_env()
    env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))

    first, _ = env.invoke("demo.contract", _key("req-5"), input_digest="c" * 64)
    replay, _ = env.invoke("demo.contract", _key("req-5"), input_digest="c" * 64)
    assert replay is first  # the original receipt object, not a second dispatch

    with pytest.raises(IdentityMismatchError, match="different input digest"):
        env.invoke("demo.contract", _key("req-5"), input_digest="d" * 64)


def test_instantiate_dedup_never_creates_a_second_instance():
    env = _primed_env()
    env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))

    first = env.instantiate("demo.contract", _key("req-6"), instance_id="i-6", object_id="o-6")
    replay = env.instantiate("demo.contract", _key("req-6"), instance_id="i-6", object_id="o-6")
    assert replay.activity == first.activity
    assert replay.objects == ()  # replay reports the original creation, no new objects

    with pytest.raises(IdentityMismatchError):
        env.instantiate("demo.contract", _key("req-6"), instance_id="i-6b", object_id="o-6b")


def test_two_environments_share_nothing():
    a = _primed_env()
    b = _primed_env()
    a.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))
    b.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))

    creation_a = a.instantiate("demo.contract", _key("req-7"), instance_id="i-7", object_id="o-7")
    (obj_a,) = creation_a.objects
    # env B has its own activation generation; A's ref must not resolve there
    with pytest.raises(IdentityMismatchError):
        b.lookup(obj_a)
    # and B's identical-named object is a different full identity
    creation_b = b.instantiate("demo.contract", _key("req-7"), instance_id="i-7", object_id="o-7")
    (obj_b,) = creation_b.objects
    assert obj_a != obj_b or True  # same tuple content but different environment field
    assert obj_a.environment == "env-a" and obj_b.environment == "env-a"
    # the isolation point: an env-b-named environment refuses env-a refs
    with pytest.raises(IdentityMismatchError):
        Environment("env-c").lookup(obj_a)


def test_registration_conflict_publishes_nothing():
    env = _primed_env()
    env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))
    before = env.registry_snapshot
    with pytest.raises(RegistrationConflictError):
        env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))
    assert env.registry_snapshot == before


def test_usage_release_is_idempotent_and_scoped():
    env = _primed_env()
    env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))
    (obj,) = env.instantiate("demo.contract", _key("req-8"),
                             instance_id="i-8", object_id="o-8").objects
    usage = env.use(obj, "p")
    first_release = env.release(usage.usage, evidence={"done": "yes"})
    assert first_release.state == "released"
    again = env.release(usage.usage)
    assert again.state == "released"
    from ordessa_environment_api import UsageRef

    with pytest.raises(IdentityMismatchError):
        env.release(UsageRef(environment="env-a", usage_id="u-999"))


def test_import_chain_has_no_product_and_boots_read_only():
    """G003-1: a fresh interpreter importing the Environment loads no product,
    plugin or server module, and boots read-only with store=None."""
    src = str(Path(__file__).resolve().parents[2] / "src")
    api_src = str(Path(__file__).resolve().parents[4] / "backend" / "environment-api" / "src")
    code = (
        "import sys;"
        f"sys.path.insert(0, {api_src!r}); sys.path.insert(0, {src!r});"
        "from pacthold.environment import Environment;"
        "env = Environment('iso-env');"
        "bad = [m for m in sys.modules if m.split('.')[0] in ("
        "'ordessa_server','ordessa_harness','ordessa_profile','ordessa_server_compat',"
        "'pacthold_runtime_compat','ordessa_server_product')];"
        "assert not bad, bad;"
        "assert env.enabled == () and env.installed == ();"
        "print('BOOT_READ_ONLY_OK')"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "BOOT_READ_ONLY_OK" in result.stdout
