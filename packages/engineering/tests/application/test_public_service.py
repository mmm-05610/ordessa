"""Public assembly exercises the sole gate against original scoped SQLite.

The Access fixture is an explicit test authority, never a production grant.
"""
import asyncio
from dataclasses import asdict
import importlib.util

import pytest

from ordessa_engineering.application.api import ApplicationError, CommandContext, EngineeringService
from ordessa_engineering.application.assembly import EngineeringPorts, build_engineering_service
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope


SCOPE = Scope("public-service-realm", "public-service-project")


def context(request, scope=SCOPE):
    return CommandContext(scope, "fixture-principal", ActorRef("fixture-human", "human", "test"),
                          request, "2026-10-12T12:00:00.000000Z", "fixture-trace")


class Access:
    def __init__(self):
        self.allowed = True
        self.calls = []

    def require(self, ctx, operation):
        self.calls.append((ctx, operation))
        if not self.allowed:
            raise ApplicationError("ACCESS_DENIED")


def test_canonical_dispatch_gate_preserves_original_port_result_and_authority():
    from types import SimpleNamespace
    from ordessa_engineering.application.contracts.execution_dispatch import EXECUTION_DISPATCH
    factory=SimpleNamespace(authority_id='fixture')
    access=Access();calls=[];result=object()
    port=SimpleNamespace(factory=factory,access=access,
        execute=lambda operation,parameters,ctx:(calls.append((operation,parameters,ctx)) or result))
    service=EngineeringService(factory,access,execution_dispatch=port)
    params={'dispatch':{'run_id':'run','step_id':'dispatch','attempt':1,
        'unit_ref':{'environmentNamespace':'fixture','unitId':'unit','ownerProviderRef':{},'sourceRevision':'revision'},
        'params':{'prompt':[]},'actions':['edit_repository'],'timeout':1}}
    ctx=context('native-request')
    assert asyncio.run(service.execute(EXECUTION_DISPATCH,params,ctx)) is result
    assert calls==[(EXECUTION_DISPATCH,params,ctx)]
    assert calls[0][1] is params and calls[0][2] is ctx
    with pytest.raises(ApplicationError,match='DISPATCH_AUTHORITY_MISMATCH'):
        EngineeringService(factory,access,execution_dispatch=SimpleNamespace(
            factory=object(),access=access,execute=port.execute))
    missing=EngineeringService(factory,access)
    with pytest.raises(ApplicationError,match='DISPATCH_AUTHORITY_UNAVAILABLE'):
        asyncio.run(missing.execute(EXECUTION_DISPATCH,params,ctx))


def test_package_public_gate_uses_original_owner_request_identity():
    import runpy
    from pathlib import Path
    from ordessa_engineering.domain.packages.codec import encode_package
    from ordessa_infrastructure.encoding import decode_json
    from ordessa_engineering.application.usecases.packages.implementation import ImplementationUseCases
    helpers=runpy.run_path(str(Path(__file__).parents[1]/'domain/test_implementation_package_binding.py'))
    _,_,package,*_=helpers['_records']()
    ctx=CommandContext(package.scope,'fixture-principal',package.created_by,'freeze-original',
        package.created_at,'trace')
    parameters={'record':decode_json(encode_package(package))}
    from ordessa_engineering.application.contracts.commands import ReadSet
    assert EngineeringService.command_request_digest('engineering.packages.freeze',parameters,ctx,
        ReadSet(ctx.scope,()))==ImplementationUseCases.package_request_digest(package,ctx)
    service=EngineeringService(object(),Access())
    observed=[];expected=object()
    service._packages.freeze_package=lambda record,context:(observed.append((record,context)) or expected)
    assert asyncio.run(service.execute('engineering.packages.freeze',parameters,ctx)) is expected
    assert observed==[(package,ctx)]


def test_public_assembly_uses_original_journal_and_immutable_reads_after_reopen(tmp_path):
    path = (tmp_path / "engineering.sqlite").resolve()
    access = Access()
    library = EngineeringLibrary.create(path, library_id="public-service", schema_version=7)
    factory = SQLiteUoWFactory(library)
    ports = EngineeringPorts(access)
    service = build_engineering_service(factory, ports)
    assert type(service) is EngineeringService
    assert service._factory is factory
    parameters = {"kind": "plan", "initial": {"media_type": "application/json",
                  "schema_id": "urn:fixture:public-document", "inline_value": {"report": "asserted"}}}
    ctx = context("create")
    try:
        first = asyncio.run(service.execute("engineering.artifacts.create", parameters, ctx))
        assert first.status == "completed"
        assert asyncio.run(service.execute("engineering.artifacts.create", parameters, ctx)) == first
        ref = first.result["revision_ref"]
        access.allowed = False
        with pytest.raises(ApplicationError, match="ACCESS_DENIED"):
            asyncio.run(service.execute("engineering.artifacts.create", parameters, context("denied")))
        access.allowed = True
        with pytest.raises(ApplicationError, match="COMMAND_NOT_FOUND"):
            asyncio.run(service.query("engineering.commands.get", {"request_id": "denied"},
                                      context("denial-read")))
        assert not library._connection.in_transaction
    finally:
        library.close()
    reopened = EngineeringLibrary.open(path, library_id="public-service")
    try:
        restored = build_engineering_service(SQLiteUoWFactory(reopened), ports)
        assert asyncio.run(restored.execute("engineering.artifacts.create", parameters, ctx)) == first
        revision = asyncio.run(restored.query("engineering.references.resolve", {"ref": ref}, context("read")))
        assert asdict(revision.ref) == ref
        assert revision.payload.value == {"report": "asserted"}
        with pytest.raises(ApplicationError, match="SCOPE_MISMATCH"):
            asyncio.run(restored.query("engineering.references.resolve", {"ref": ref},
                                      context("wrong-scope", Scope(SCOPE.realm_id, "another-project"))))
    finally:
        reopened.close()


def test_absent_authority_and_cancel_before_execution_produce_no_write(tmp_path):
    library = EngineeringLibrary.create((tmp_path / "no-authority.sqlite").resolve(),
                                        library_id="no-authority", schema_version=7)
    try:
        service = build_engineering_service(SQLiteUoWFactory(library), EngineeringPorts(None))
        with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
            asyncio.run(service.execute("engineering.artifacts.create", {}, context("missing")))
        async def cancelled():
            task = asyncio.create_task(service.execute("engineering.artifacts.create", {}, context("cancelled")))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        asyncio.run(cancelled())
        assert library._connection.execute("SELECT count(*) FROM eng_commands").fetchone()[0] == 0
        assert not library._connection.in_transaction
    finally:
        library.close()


def test_retired_facade_module_is_absent_and_missing_persistence_is_explicit():
    assert importlib.util.find_spec("ordessa_engineering.application.usecases.facade") is None
    with pytest.raises(ApplicationError, match="PERSISTENCE_AUTHORITY_UNAVAILABLE"):
        build_engineering_service(None, EngineeringPorts(None))
    with pytest.raises(ApplicationError, match="INVALID_ENGINEERING_PORTS"):
        build_engineering_service(object(), object())


def test_conditional_effect_routes_keep_original_authority_payload_and_result(tmp_path):
    library = EngineeringLibrary.create((tmp_path / "routes.sqlite").resolve(), library_id="routes", schema_version=7)
    factory, access = SQLiteUoWFactory(library), Access()
    calls, result = [], object()
    class Routes:
        def invoke(self, operation, parameters, ctx):
            calls.append((operation, parameters, ctx))
            return result
    routes = Routes()
    routes.factory, routes.access = factory, access
    try:
        service = build_engineering_service(factory, EngineeringPorts(access, implementation_routes=routes))
        ctx, params = context("dispatch"), {"run_id": "bound-original-work", "native": {"prompt": []}}
        assert asyncio.run(service.execute("engineering.implementation.reconcile", params, ctx)) is result
        assert calls == [("engineering.implementation.reconcile", params, ctx)]
        assert calls[0][1] is params and calls[0][2] is ctx
        assert access.calls[-1] == (ctx, "engineering.implementation.reconcile")
        access.allowed = False
        with pytest.raises(ApplicationError, match="ACCESS_DENIED"):
            asyncio.run(service.execute("engineering.implementation.reconcile", params, ctx))
        assert len(calls) == 1
        access.allowed = True
        # An attached reconciliation port must not restore a retired dispatch
        # entry or route its payload to a parallel authority.
        with pytest.raises(ApplicationError, match="OPERATION_UNAVAILABLE"):
            asyncio.run(service.execute("engineering.implementation.dispatch", params, ctx))
        assert len(calls) == 1
        assert "engineering.implementation.dispatch" not in {
            d.capability_id for d in service.bound_operation_capabilities().capabilities}
        assert asyncio.run(service.query("engineering.implementation.get_dispatch", params, ctx)) is result
        with pytest.raises(ApplicationError, match="OPERATION_UNAVAILABLE"):
            asyncio.run(service.execute("engineering.implementation.start_run", {}, ctx))
        absent = build_engineering_service(factory, EngineeringPorts(access))
        with pytest.raises(ApplicationError, match="OPERATION_UNAVAILABLE"):
            asyncio.run(absent.execute("engineering.implementation.dispatch", params, ctx))
        routes.access = Access()
        with pytest.raises(ApplicationError, match="IMPLEMENTATION_AUTHORITY_MISMATCH"):
            build_engineering_service(factory, EngineeringPorts(access, implementation_routes=routes))
        assert not library._connection.in_transaction
    finally:
        library.close()
