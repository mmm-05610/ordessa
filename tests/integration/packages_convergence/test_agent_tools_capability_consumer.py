"""Actual Profile owner -> F1 wire -> bounded client, in-process transport only.

No socket, HTTP-server readiness, installed Agent wheel or native-brand claim.
"""
import asyncio,json
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
from io import BytesIO
import pytest
from ordessa_system_access_client import CapabilityClient,Service
from ordessa_interfaces.system_access import CapabilityHost,RequestContext,build_registry
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant
from ordessa_server.composition.registry_runtime import RegistryRuntime
from ordessa_server.composition.agent_bindings.profile_access import OriginalProfileAccess
from ordessa_agents.capability.profiles import build_profile_capability
from apps.cli.tests.integration.profile_test_owner import profile_owner


def test_ui_seed_requires_disposable_scope_uses_only_current_profiles_and_no_native(tmp_path):
    import importlib.util
    from ordessa_system_access_client import profile_schema
    root=Path(__file__).parents[3]
    path=root/'tooling/checks/server_product/seed-profile-ui-probe.py'
    spec=importlib.util.spec_from_file_location('current_ui_seed',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    ns='ordessa-profile-ui-fixture'
    class Policy:
        def admit_invoke(self,*args):return True
        def admit_object_access(self,*args):return True
    pin={'environmentNamespace':ns,'definitionId':'fixture','revision':'1'}
    original=profile_owner(tmp_path/'seed.sqlite',ns,'principal:seed',Policy(),pin)
    scope=Scope('fixture-realm','fixture-project');token='synthetic-seed-token'
    issuer=InstanceAccessAuthority(lambda:token,principal_id='seed',grants=(AccessGrant(scope,('agents.profiles.capabilities','agents.profiles.create')),),legacy_principal=None)
    caller=[issuer.authenticate('Bearer '+token)];invocation=object()
    access=OriginalProfileAccess(issuer,caller_resolver=lambda v:caller[0] if v is invocation else None,
        scope_for_service=lambda service:scope if service is original.service else None,
        principal_scope_for_caller=lambda p:'principal:'+p.principal_id)
    capability=build_profile_capability(original.service,invocation_resolver=lambda ctx:invocation,guard=access.guard)
    host=CapabilityHost(build_registry([capability]),('profiles',));calls=[]
    class Client:
        def profile_capabilities(self,key,required):
            calls.append('agents.profiles.capabilities')
            value=asyncio.run(host.call('agents.profiles.capabilities',{},RequestContext({},key)))
            assert value.status=='completed' and required in value.data['supportedMethods'],value.error
            return value.data
        def invoke(self,op,inputs,key):
            calls.append(op)
            value=asyncio.run(host.call(op,inputs,RequestContext({},key)))
            return {'status':value.status,'data':value.data}
    first={'schemaVersion':'1','harnessDefinitionRef':pin,'declarations':[]}
    second={**first,'metadata':{'phase':'next'}}
    try:
        with pytest.raises(ValueError):module.seed(Client(),namespace='real-project',first=first,next_content=second,request_prefix='seed')
        assert calls==[] and original.service.list()==()
        result=module.seed(Client(),namespace=ns,first=first,next_content=second,request_prefix='seed')
        assert result['status']=='completed' and result['profileCount']==2 and result['modelCalls']==0
        assert result['credentialImported'] is False and result['nativeApplied']=='unobserved'
        assert len(original.service.list())==2 and result['profileRefs'][0]!=result['profileRefs'][1]
        before=original.service._profile_store._conn.total_changes
        assert module.seed(Client(),namespace=ns,first=first,next_content=second,request_prefix='seed')==result
        assert original.service._profile_store._conn.total_changes==before
        assert set(calls)=={'agents.profiles.capabilities','agents.profiles.create'}
    finally:original.close()
