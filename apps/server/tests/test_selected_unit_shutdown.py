"""Selected shutdown consumer checks with the original Pi Unit owner.

No native Unit is created, no provider/model is called, and no credential is
read. Controlled wire handlers and the public Manager close call make stop
ordering observable; Execution owns native request/callback idleness.
"""
from ordessa_server.composition.runtime import RuntimeCompositionUnavailable
from threading import Event, Thread
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
import asyncio
import time

import pytest
from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_execution_agents.profiles import ProfileService
from ordessa_execution_agents.harness.providers.registry import (
    HarnessDefinitionDeclaration, HarnessDefinitionDescriptor,
    HarnessInstallationObservation,
)
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.configuration.product_selection import create_host_product_composition
from ordessa_server.composition.pi_selection import PiExecutionPorts, PiExecutionSelection
from ordessa_server.composition.product_runtime import build_product_runtime
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
from ordessa_units.assembly import UnitRunPermission
from ordessa_units.public import unit_services
from server_plugin_api import ServerMethodDescriptor


def _build_selected_runtime(tmp_path):
    product_root = tmp_path / "product"
    fingerprint = ProtectedFingerprintHmac(
        {"controlled": b"controlled-fingerprint-value-32!!"}, active_key_id="controlled")
    setup = create_host_product_composition(fingerprint_port=fingerprint).default_runtime(product_root)
    try:
        context = setup.unit_runtime.context
        definition = {"environmentNamespace": context.environment_namespace,
                      "definitionId": "pi", "revision": "1"}
        profiles = ProfileService(UnitProfileAdmission(context))
        profile = profiles.create(profile_id="selected-profile", name="Fixed test Profile",
            content={"schemaVersion": "1", "harnessDefinitionRef": definition,
                "declarations": [{"declarationId": "selected-model",
                    "configurationKind": "assets.model-provider", "schemaVersion": "1",
                    "action": "value", "requirement": "required",
                    "payload": {"provider": "opencode", "model": "step-5-preview-free",
                        "protocol": "openai-chat", "endpoint": "https://opencode.ai/zen/v1"}}]},
            request=profiles.request_key("create-selected-profile"))
        revision = profiles.get_revision(profile.current_revision)
    finally:
        setup.stop()

    root = tmp_path / "local"
    root.mkdir()
    environments = EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path / "environments.sqlite"),
        providers={"local": LocalEnvironmentResourceProvider(default_root=str(root))})
    instance = environments.register("local", str(root))
    descriptor = HarnessDefinitionDescriptor("pi", definition, "sha256:" + "a" * 64,
        "acp/v1", "controlled", "controlled", ("prepare", "start", "stop", "release"))
    declaration = HarnessDefinitionDeclaration(descriptor,
        lambda *_args: HarnessInstallationObservation(
            state="present", native_version=True, version_verified="controlled",
            evidence_ref="controlled-installation"))
    selection = PiExecutionSelection("agent", revision.ref, instance.identity, "local", "none", True,
        "selected-model", "opencode", "step-5-preview-free", "/bin/true", "a" * 64,
        "/bin/true", str(tmp_path / "unused-env-path"))

    def permission_factory(*, runtime, admission_context, selection, environment_instance):
        authority = runtime.wire.identity_authority
        scope = Scope(selection.profile_revision.environment_namespace, "shutdown-test")
        actions = frozenset({"prepare", "start", "interaction", "stop", "release"})
        authority.replace_grants((AccessGrant(
            scope, tuple("execution.units." + action for action in sorted(actions))),))
        principal = authority.authenticate("Bearer " + runtime.token)
        return UnitRunPermission(access_authority=authority, principal=principal, scope=scope,
            agent_id=selection.agent_id, profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity, root_directory=str(root),
            actions=actions, expires_at=time.time() + 600)

    ports = PiExecutionPorts(environments, declaration, fingerprint, permission_factory,
                             ("step-5-preview-free",), None)
    runtime = build_product_runtime(product_root, pi_selection=selection, pi_ports=ports)
    return runtime, instance


@pytest.fixture
def selected_runtime(tmp_path):
    runtime, instance = _build_selected_runtime(tmp_path)
    runtime.start()
    try:
        yield runtime, instance
    finally:
        if runtime.stop_state == "idle" and runtime.started:
            runtime.stop()


@pytest.fixture
def unstarted_selected_runtime(tmp_path):
    runtime, instance = _build_selected_runtime(tmp_path)
    try:
        yield runtime, instance
    finally:
        if runtime.stop_state == "idle":
            runtime.stop()


def _assert_original_owner(runtime):
    owner = runtime.unit_execution_owner
    records = owner.records
    assert runtime.units is owner.manager
    assert records is unit_services(runtime.unit_runtime.context).unit_manager.records
    assert owner.permission.access_authority is runtime.wire.identity_authority
    return owner, records


def _register_blocking_method(runtime, method, handler, *, contextual=False):
    runtime.plugin_host.methods.register(ServerMethodDescriptor(
        method, frozenset(), frozenset(), handler,
        owner="shutdown.test", contextual=contextual))


def test_sync_admitted_dispatch_keeps_original_runtime_until_retry(selected_runtime, monkeypatch):
    runtime, _instance = selected_runtime
    owner, records = _assert_original_owner(runtime)
    principal = runtime.wire.identity_authority.authenticate("Bearer " + runtime.token)
    entered, release, finished = Event(), Event(), Event()
    close_calls = []
    from ordessa_units.api.manager import UnitManager
    actual_close = UnitManager.close

    def track_close(manager, authorization):
        close_calls.append((manager, authorization))
        return actual_close(manager, authorization)

    monkeypatch.setattr(UnitManager, "close", track_close)

    def handler(_params, _caller):
        assert _caller is principal
        entered.set()
        assert release.wait(5)
        finished.set()
        return {"ok": True}

    _register_blocking_method(runtime, "shutdown.sync", handler, contextual=True)
    outcomes = []
    thread = Thread(target=lambda: outcomes.append(
        runtime.wire.dispatch("shutdown.sync", {}, caller=principal)))
    thread.start()
    assert entered.wait(5)
    with pytest.raises(RuntimeCompositionUnavailable, match="admitted wire calls remain"):
        runtime.stop()
    assert runtime.stop_state == "pending"
    assert close_calls == []
    runtime.wire.identity_authority.verify(principal)
    assert runtime.owner.acquired
    assert runtime.unit_execution_owner is owner and owner.records is records
    assert runtime.plugin_host.active_ids()

    release.set()
    thread.join(5)
    assert not thread.is_alive() and finished.is_set()
    assert outcomes == [{"ok": True}]
    runtime.plugin_host.methods.unregister("shutdown.sync", owner="shutdown.test")
    runtime.stop()
    assert runtime.stop_state == "completed"
    assert len(close_calls) == 1 and close_calls[0][0] is runtime.units
    assert runtime.owner.acquired is False
    runtime.stop()
    assert len(close_calls) == 1


def test_async_same_loop_pending_stop_does_not_close_original_manager(selected_runtime, monkeypatch):
    runtime, _instance = selected_runtime
    owner, records = _assert_original_owner(runtime)
    principal = runtime.wire.identity_authority.authenticate("Bearer " + runtime.token)
    entered, release = asyncio.Event(), asyncio.Event()
    from ordessa_units.api.manager import UnitManager
    actual_close = UnitManager.close
    close_calls = []

    def track_close(manager, authorization):
        close_calls.append((manager, authorization))
        return actual_close(manager, authorization)

    monkeypatch.setattr(UnitManager, "close", track_close)

    async def handler(_params, _caller):
        entered.set()
        await release.wait()
        return {"async": True}

    _register_blocking_method(runtime, "shutdown.async", handler, contextual=True)

    async def exercise():
        dispatch = asyncio.create_task(runtime.wire.dispatch_async(
            "shutdown.async", {}, caller=principal))
        await entered.wait()
        with pytest.raises(RuntimeCompositionUnavailable, match="admitted wire calls remain"):
            runtime.stop()
        assert runtime.stop_state == "pending"
        assert close_calls == []
        runtime.wire.identity_authority.verify(principal)
        assert runtime.owner.acquired
        assert runtime.unit_execution_owner is owner and owner.records is records
        release.set()
        assert await dispatch == {"async": True}

    asyncio.run(exercise())
    runtime.plugin_host.methods.unregister("shutdown.async", owner="shutdown.test")
    runtime.stop()
    assert runtime.stop_state == "completed"
    assert len(close_calls) == 1


@pytest.mark.parametrize("result_kind", ("unknown", "partial", "mixed_pending", "malformed_pending", "exception"))
def test_unknown_partial_or_malformed_manager_results_block_replay_and_teardown(
        selected_runtime, monkeypatch, result_kind):
    runtime, _instance = selected_runtime
    owner, records = _assert_original_owner(runtime)
    principal = runtime.wire.identity_authority.authenticate("Bearer " + runtime.token)
    from ordessa_units.api.manager import UnitManager
    calls = []

    pending = {"identity": {"unitId": "controlled-result-only"},
        "state": "pending", "unresolved": True}
    results = {
        "unknown": {"state": "unknown", "units": (), "unresolved": True},
        "partial": {"state": "partial", "units": ({"identity": {"unitId": "controlled"},
            "state": "confirmed"},), "unresolved": False},
        "mixed_pending": {"state": "pending", "units": (pending,
            {"identity": {"unitId": "controlled-other"}, "state": "unknown"}),
            "unresolved": True},
        "malformed_pending": {"state": "pending", "units": (), "unresolved": True},
    }

    def unresolved(manager, authorization):
        calls.append((manager, authorization))
        if result_kind == "exception":
            raise RuntimeError("controlled close failure")
        return results[result_kind]

    monkeypatch.setattr(UnitManager, "close", unresolved)
    active = runtime.plugin_host.active_ids()
    with pytest.raises(RuntimeCompositionUnavailable):
        runtime.stop()
    assert runtime.stop_state == "pending"
    assert len(calls) == 1 and calls[0][0] is runtime.units
    assert runtime.unit_execution_owner is owner and owner.records is records
    runtime.wire.identity_authority.verify(principal)
    assert runtime.owner.acquired and runtime.plugin_host.active_ids() == active

    with pytest.raises(RuntimeCompositionUnavailable, match="shutdown is pending"):
        runtime.stop()
    with pytest.raises(RuntimeCompositionUnavailable, match="shutdown is pending"):
        runtime.start()
    assert len(calls) == 1
    assert runtime.owner.acquired and runtime.plugin_host.active_ids() == active


def test_exact_all_pending_result_can_retry_with_same_original_authorization(
        selected_runtime, monkeypatch):
    runtime, _instance = selected_runtime
    owner, records = _assert_original_owner(runtime)
    principal = runtime.wire.identity_authority.authenticate("Bearer " + runtime.token)
    from ordessa_units.api.manager import UnitManager
    actual_close = UnitManager.close
    calls = []
    pending = {"identity": {"unitId": "controlled-result-only"},
        "state": "pending", "unresolved": True}

    def pending_then_close(manager, authorization):
        calls.append((manager, authorization))
        if len(calls) == 1:
            return {"state": "pending", "units": (pending,), "unresolved": True}
        return actual_close(manager, authorization)

    monkeypatch.setattr(UnitManager, "close", pending_then_close)
    active = runtime.plugin_host.active_ids()
    with pytest.raises(RuntimeCompositionUnavailable, match="close is pending"):
        runtime.stop()
    assert runtime.stop_state == "pending"
    assert len(calls) == 1
    assert runtime.unit_execution_owner is owner and owner.records is records
    assert runtime.owner.acquired and runtime.plugin_host.active_ids() == active
    runtime.wire.identity_authority.verify(principal)

    runtime.stop()
    assert len(calls) == 2 and calls[0][0] is calls[1][0] is runtime.units
    assert calls[0][1] is calls[1][1]
    assert runtime.stop_state == "completed"


def test_invalid_original_permission_blocks_close_without_new_teardown(selected_runtime):
    runtime, _instance = selected_runtime
    owner, records = _assert_original_owner(runtime)
    active = runtime.plugin_host.active_ids()
    authority = runtime.wire.identity_authority
    authority.invalidate()
    invalid_epoch = authority.credential_epoch

    with pytest.raises(RuntimeCompositionUnavailable, match="did not confirm"):
        runtime.stop()

    assert runtime.stop_state == "pending"
    assert authority.credential_epoch == invalid_epoch
    assert runtime.unit_execution_owner is owner and owner.records is records
    assert runtime.owner.acquired and runtime.plugin_host.active_ids() == active
    with pytest.raises(RuntimeCompositionUnavailable, match="shutdown is pending"):
        runtime.stop()


def test_teardown_waits_for_original_manager_close_result(selected_runtime, monkeypatch):
    runtime, _instance = selected_runtime
    owner, records = _assert_original_owner(runtime)
    principal = runtime.wire.identity_authority.authenticate("Bearer " + runtime.token)
    from ordessa_units.api.manager import UnitManager
    actual_close = UnitManager.close
    entered, release, finished = Event(), Event(), Event()
    calls = []

    def delayed_close(manager, authorization):
        calls.append((manager, authorization))
        entered.set()
        assert release.wait(5)
        result = actual_close(manager, authorization)
        finished.set()
        return result

    monkeypatch.setattr(UnitManager, "close", delayed_close)
    failures = []

    def stop():
        try:
            runtime.stop()
        except BaseException as exc:
            failures.append(exc)

    stopping = Thread(target=stop)
    stopping.start()
    assert entered.wait(5)
    assert runtime.stop_state == "pending"
    assert runtime.owner.acquired
    assert runtime.unit_execution_owner is owner and owner.records is records
    assert runtime.plugin_host.active_ids()
    runtime.wire.identity_authority.verify(principal)

    release.set()
    stopping.join(5)
    assert not stopping.is_alive()
    assert finished.is_set() and failures == []
    assert runtime.stop_state == "completed"
    assert len(calls) == 1 and calls[0][0] is runtime.units
    assert runtime.owner.acquired is False


def test_failed_start_uses_selected_stop_gate_and_retains_root_on_pending_close(
        unstarted_selected_runtime, monkeypatch):
    runtime, _instance = unstarted_selected_runtime
    owner, records = _assert_original_owner(runtime)
    authority = runtime.wire.identity_authority
    principal = authority.authenticate("Bearer " + runtime.token)
    epoch = authority.credential_epoch
    active = runtime.plugin_host.active_ids()
    stop_hooks = []
    monkeypatch.setattr(runtime.plugin_host, "run_stop_hooks",
        lambda: stop_hooks.append("called"))
    monkeypatch.setattr(runtime.wire, "reopen_admission", lambda: False)
    from ordessa_units.api.manager import UnitManager
    close_calls = []
    pending = {"identity": {"unitId": "controlled-result-only"},
        "state": "pending", "unresolved": True}
    monkeypatch.setattr(UnitManager, "close", lambda manager, authorization: (
        close_calls.append((manager, authorization)) or
        {"state": "pending", "units": (pending,), "unresolved": True}))

    with pytest.raises(RuntimeCompositionUnavailable, match="wire dispatch admission could not reopen") as failure:
        runtime.start()

    assert runtime.stop_state == "pending" and runtime.started is False
    assert len(close_calls) == 1 and close_calls[0][0] is runtime.units
    assert stop_hooks == []
    assert runtime.unit_execution_owner is owner and owner.records is records
    assert runtime.owner.acquired and runtime.plugin_host.active_ids() == active
    assert authority.credential_epoch == epoch
    authority.verify(principal)
    assert any("close is pending" in str(item)
               for item in getattr(failure.value, "cleanup_errors", ()))
