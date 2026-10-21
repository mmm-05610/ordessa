"""Short-lived product entry cannot export retained handles; retained owner host can."""
import asyncio
from types import SimpleNamespace

from ordessa_environments import EnvironmentManager,OwnerScope,SQLiteEnvironmentStore
from ordessa_environments.capability import EnvironmentCapabilityService
from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_interfaces.system_access import RequestContext
from ordessa_cli.composition.environments import build_environment_domain
from ordessa_cli.composition.state import LocalState
from ordessa_server.composition.packages_convergence import build_packages_host


def test_one_shot_local_product_does_not_advertise_unusable_retained_use_effects(tmp_path):
    state=LocalState.open(str(tmp_path))
    domain=build_environment_domain(state,session=False)
    host=domain.host
    for operation in ('environments.acquire','environments.launch','environments.export-endpoint'):
        assert operation not in host.operations
    assert {'environments.create','environments.register','environments.exec','environments.files','environments.release'}<=set(host.operations)
    with SQLiteEnvironmentStore(state.environments_store).transaction() as db:
        assert db.execute('SELECT count(*) FROM environment_uses').fetchone()[0]==0
    domain.close()


def test_actual_retained_owner_factory_can_acquire_export_resolve_and_release_without_cli_reacquire(tmp_path):
    async def scenario():
        scope=OwnerScope('principal','existing-test-subject');invocation=object()
        manager=EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'env.sqlite'),
            providers={'local':LocalEnvironmentResourceProvider(default_root=str(tmp_path/'work'))})
        def authorize(s,a,t,i):return s==scope and i is invocation
        services=EnvironmentCapabilityService(manager,authorize=authorize,provider_catalog=[],aliases_path=tmp_path/'aliases.json')
        # External trusted test authority: resolver returns this issued object,
        # never reconstructing it from the public principal mapping.
        active=[]
        def context(name):
            ctx=RequestContext({'subject':scope.ref},name);active.append(ctx);return ctx
        def resolve(ctx):
            assert any(ctx is item for item in active)
            return issued
        issued=SimpleNamespace(owner_scope=scope)
        invocation=issued  # actual current owner authorization checks identity
        entry=SimpleNamespace(name='environments',module='ordessa_environments.capability',attr='factory')
        host=build_packages_host(allowlist=('environments',),bindings_by_capability={
            'environments':{'services':services,'invocation_resolver':resolve}},entry_points=(entry,))
        assert {'environments.acquire','environments.launch','environments.export-endpoint'}<=set(host.operations)
        created=await host.call('environments.create',{'provider':'local','root':str(tmp_path/'work'),'alias':'retained'},context('create'))
        assert created.status=='completed'
        acquired=await host.call('environments.acquire',{'reference':'retained','sharing':False},context('acquire'))
        assert acquired.status=='completed'
        use=acquired.data['useIdentity']
        try:
            exported=await host.call('environments.export-endpoint',{'useIdentity':use,'capabilities':['launcher','observe']},context('export'))
            assert exported.status=='completed'
            binding,descriptor=services.endpoints.resolve(exported.data['endpointRef'],scope,invocation=issued)
            assert descriptor['capabilities']==['launcher','observe']
            assert binding['use_id']==use and use in manager._owned_use_handles
        finally:
            released=await host.call('environments.release',{'useIdentity':use},context('release'))
            assert released.status=='completed'
        assert (tmp_path/'work').is_dir()
    asyncio.run(scenario())
