"""Real async HTTP -> issued machine -> original schema7 library/UoW."""
import asyncio
from dataclasses import asdict, replace

import httpx
import pytest

from ordessa_interfaces.http import create_app
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from ordessa_server.composition.product_runtime import build_product_runtime

SCOPE = Scope("slice-realm", "slice-project")


@pytest.fixture
def runtime(tmp_path):
    value = build_product_runtime(tmp_path / "server", library_path=tmp_path / "library.sqlite",
        library_id="slice-library", scope=SCOPE, create_library=True)
    value.start()
    try:
        yield value
    finally:
        value.stop()


def call(runtime, method, parameters=None, *, request_id="slice-request-one", scope=SCOPE, extra=None):
    async def post():
        params = {"scope": asdict(scope), "requestId": request_id}
        if parameters is not None:
            params["parameters"] = parameters
        params.update(extra or {})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                base_url="http://127.0.0.1") as client:
            response = await client.post("/wire/v1/" + method,
                headers={"Authorization": "Bearer " + runtime.token},
                json={"jsonrpc": "2.0", "id": "transport-attempt", "method": method, "params": params})
            assert response.status_code == 200
            return response.json()
    return asyncio.run(post())


def parameters():
    return {"kind": "other", "initial": {"media_type": "application/json", "schema_id": "urn:test:v1",
        "inline_value": {"question": "A?", "answer": "A", "assurance": "agent-attested"}}}


def test_capabilities_are_actual_handlers_and_missing_whole_product_is_explicit(runtime):
    data = call(runtime, "engineering.capabilities")["result"]
    from ordessa_engineering.application.api import EngineeringService
    from ordessa_server.composition.engineering import EngineeringServerPlugin
    plugin, = (item for item in runtime.plugin_selection
               if type(item) is EngineeringServerPlugin)
    binding = plugin._binding_for(runtime.wire.identity_authority)
    bound = binding.service.bound_operation_capabilities().capabilities
    assert data["commands"] == [{
        "operation": item.capability_id,
        "interface_version": item.interface_version,
        "contract_digest": item.contract_digest,
        "contract": item.contract,
    } for item in bound]
    assert data["queries"] == list(dict.fromkeys((*EngineeringService.supported_queries,
        'engineering.reviews.get_request', 'engineering.runs.get_wait')))
    assert data["supports"]["method_slot_bridge"] is True
    assert all(data["supports"][name] is False for name in
        ("consent", "dispatch", "semantic_review", "work_projection", "durable_events"))
    assert {item["interface_version"] for item in data["commands"]} == {"1", "2"}
    assert "error" in call(runtime, "engineering.approvals.record_consent", {"approved": True})


def test_command_replay_queries_revision_and_original_result_survive_restart(runtime):
    original = call(runtime, "engineering.artifacts.create", parameters())["result"]
    assert call(runtime, "engineering.artifacts.create", parameters())["result"] == original
    assert original["status"] == "completed"
    assert call(runtime, "engineering.commands.get", {"request_id": "slice-request-one"})["result"] == original
    ref = original["result"]["revision_ref"]
    resolved = call(runtime, "engineering.references.resolve", {"ref": ref})["result"]
    assert resolved["record_type"] == "ArtifactRevision"
    assert resolved["data"]["payload"]["inline_value"]["assurance"] == "agent-attested"
    artifact = call(runtime, "engineering.artifacts.get", {"artifact_id": ref["artifact_id"]})["result"]
    assert artifact["record_type"] == "Artifact"
    runtime.stop()
    runtime.start()
    assert call(runtime, "engineering.commands.get", {"request_id": "slice-request-one"})["result"] == original
    assert call(runtime, "engineering.artifacts.create", parameters())["result"] == original


def test_changed_payload_same_request_cannot_overwrite_original(runtime):
    original = call(runtime, "engineering.artifacts.create", parameters())["result"]
    changed = parameters()
    changed["initial"]["inline_value"]["answer"] = "B"
    conflict = call(runtime, "engineering.artifacts.create", changed)
    assert "error" in conflict
    assert call(runtime, "engineering.commands.get", {"request_id": "slice-request-one"})["result"] == original


@pytest.mark.parametrize("extra", [{"human_id": "owner"}, {"verified": True}, {"approved": True}])
def test_json_cannot_upgrade_service_actor_or_supply_confirmation(runtime, extra):
    assert call(runtime, "engineering.artifacts.create", parameters(), extra=extra)["error"]["code"] == "INVALID_REQUEST"
    assert "error" in call(runtime, "engineering.commands.get", {"request_id": "slice-request-one"})


def test_cross_project_or_revoked_capability_refuses_before_usecase(runtime):
    assert call(runtime, "engineering.artifacts.create", parameters(), scope=Scope(SCOPE.realm_id, "foreign"))["error"]["code"] == "FORBIDDEN"
    runtime.wire.identity_authority.replace_grants((AccessGrant(SCOPE, ("engineering.capabilities",)),))
    assert call(runtime, "engineering.artifacts.create", parameters())["error"]["code"] == "FORBIDDEN"


def test_unavailable_proposal_read_is_not_empty_success(runtime):
    response = call(runtime, "engineering.changes.get", {"change_id": "absent-change"})
    assert "error" in response and "result" not in response


def test_explicit_create_never_migrates_or_replaces_existing_library(tmp_path):
    args = dict(library_path=tmp_path / "library.sqlite", library_id="slice-library", scope=SCOPE)
    rt = build_product_runtime(tmp_path / "server", create_library=True, **args)
    rt.stop()
    before = (tmp_path / "library.sqlite").read_bytes()
    with pytest.raises(Exception):
        build_product_runtime(tmp_path / "server", create_library=True, **args)
    assert (tmp_path / "library.sqlite").read_bytes() == before


def test_actual_compiled_method_bridge_executes_same_facade_journal(runtime, tmp_path):
    # Use the public loader/compiler, not a fabricated Program/green review.
    import hashlib
    import json
    from ordessa_engineering.methods import compile_method
    from ordessa_engineering.methods.loading.loader import load_method
    from ordessa_engineering.methods.definitions.models import MethodSource
    from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
    from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
    source = tmp_path / "method"
    source.mkdir()
    descriptor = command_capabilities().capabilities[0]
    workflow = {"schema_version": 1, "entry": "capture", "context_slots": ["kind", "body"],
        "steps": [{"id": "capture", "kind": "operation", "operation": descriptor.capability_id,
            "inputs": {"kind": "kind", "initial": "body"},
            "outcomes": {name: {"stop": name} for name in ("completed", "rejected")}}],
        "stop_outcomes": ["completed", "rejected"], "wait_kinds": []}
    raw = json.dumps(workflow).encode()
    (source / "workflow.yaml").write_bytes(raw)
    manifest = {"schema_version": 1, "method_id": "test.slice-method", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "resources": [{"id": "workflow.main", "kind": "workflow", "path": "workflow.yaml",
            "media_type": "application/yaml", "sha256": hashlib.sha256(raw).hexdigest()}],
        "requires": [{key: getattr(descriptor, key) for key in
            ("capability_id", "kind", "interface_version", "contract_digest")}], "documents": []}
    (source / "method.yaml").write_text(json.dumps(manifest))
    loaded = load_method(MethodSource(source), FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, command_capabilities(), "test.slice/1")
    assert compiled.ok, compiled.error
    plugin = next(plugin for plugin in runtime.plugin_selection if plugin.descriptor().id == "ordessa.engineering")
    binding = plugin._binding_for(runtime.wire.identity_authority)
    caller = runtime.wire.identity_authority.authenticate("Bearer " + runtime.token)
    result = asyncio.run(binding.execute_node(compiled.value.program, "capture",
        {"kind": "other", "body": parameters()["initial"]}, caller=caller, request_id="bridge-request-one"))
    assert result["status"] == "completed"
    assert call(runtime, "engineering.commands.get", {"request_id": "bridge-request-one"})["result"] == result
    broken = replace(compiled.value.program,
        capability_bindings=(replace(compiled.value.program.capability_bindings[0], contract_digest="0" * 64),))
    with pytest.raises(Exception, match="METHOD_CAPABILITY_CHANGED"):
        asyncio.run(binding.execute_node(broken, "capture", {"kind": "other", "body": parameters()["initial"]},
            caller=caller, request_id="bridge-request-two"))
    assert "error" in call(runtime, "engineering.commands.get", {"request_id": "bridge-request-two"})


def test_async_contextual_error_wall_does_not_leak_exception(runtime):
    from ordessa_server_plugin_api import ServerMethodDescriptor
    from ordessa_server_plugin_api.wire_errors import WireError
    async def broken(params, caller):
        raise RuntimeError('private-material-sentinel')
    runtime.wire._registry.register(ServerMethodDescriptor(method_id='engineering.test_failure',
        required_params=frozenset({'requestId'}), optional_params=frozenset(),
        handler=broken, owner='ordessa.engineering', contextual=True))
    caller = runtime.wire.identity_authority.authenticate('Bearer ' + runtime.token)
    with pytest.raises(WireError) as failure:
        asyncio.run(runtime.wire.dispatch_async('engineering.test_failure', {'requestId': 'error-wall-request'}, caller=caller))
    assert 'private-material-sentinel' not in str(failure.value)


def test_legacy_async_handler_cannot_run_after_legacy_admission_ends(runtime):
    from ordessa_server_plugin_api import ServerMethodDescriptor
    from ordessa_server_plugin_api.wire_errors import WireError
    effects = []
    async def deferred(params):
        effects.append('unauthorized-deferred-effect')
    runtime.wire._registry.register(ServerMethodDescriptor(method_id='engineering.legacy_async',
        required_params=frozenset({'requestId'}), optional_params=frozenset(),
        handler=deferred, owner='ordessa.engineering', contextual=False))
    caller = runtime.wire.identity_authority.authenticate('Bearer ' + runtime.token)
    with pytest.raises(WireError, match='Async methods require contextual admission'):
        asyncio.run(runtime.wire.dispatch_async('engineering.legacy_async', {'requestId': 'legacy-async-request'}, caller=caller))
    assert effects == []


def test_unbound_dispatch_not_advertised_and_not_given_default_machine_grant(runtime):
    caps=call(runtime,'engineering.capabilities')['result']
    operation='engineering.implementation.dispatch'
    from ordessa_engineering.application.api import EXECUTION_DISPATCH
    assert operation not in caps['supported_methods']
    assert all(item['operation']!=operation for item in caps['commands'])
    assert runtime.wire._registry.lookup(operation) is None
    principal = runtime.wire.identity_authority.authenticate('Bearer ' + runtime.token)
    assert all(EXECUTION_DISPATCH not in grant.capabilities for grant in principal.grants)
    assert call(runtime,operation,{'run_id':'r','step_id':'s','attempt':1,'unit_ref':{},'params':{},'actions':[]})['error']['code']=='INVALID_REQUEST'
