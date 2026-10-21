"""Dependency construction only; owner services retain runtime and durable state."""
from pathlib import Path

from ordessa_interfaces.system_access import CapabilityHost, build_registry
from ordessa_interfaces.system_access.discovery import load_capabilities

from ordessa_server.composition.decision_bindings.authorization import protect_decisions


def build_packages_host(*, allowlist, bindings_by_capability, entry_points=None):
    """Load exact allowlisted factories with their own validated bindings.

    No shared services facade: each owner receives its own service instance.
    """
    names = tuple(allowlist)
    if len(set(names)) != len(names) or set(names) != set(bindings_by_capability):
        raise ValueError('allowlist must match explicit capability binding keys')
    capabilities = []
    for name in names:
        loaded = load_capabilities((name,), bindings_by_capability[name], entry_points=entry_points)
        for capability in loaded:
            capabilities.append(protect_decisions(capability, bindings_by_capability[name])
                                if capability.descriptor.id == 'decisions' else capability)
    return CapabilityHost(build_registry(capabilities), names)


def build_harness_catalog(*,allowlist,bindings_by_provider,entry_points=None):
    """Exact allowlisted SDK factories; configuration is not an execution grant."""
    from importlib.metadata import entry_points as installed_entry_points
    from ordessa_agents.harness.providers.catalog import HarnessCatalog
    from ordessa_agents.sdk import HarnessError
    names=tuple(allowlist)
    if not names or len(set(names))!=len(names) or set(names)!=set(bindings_by_provider):
        raise HarnessError('HARNESS_ALLOWLIST_INVALID')
    points=installed_entry_points(group='ordessa.harness_providers') if entry_points is None else tuple(entry_points)
    selected={}
    for point in points:
        if point.group!='ordessa.harness_providers' or point.name not in names:continue
        if point.name in selected:raise HarnessError('HARNESS_ENTRYPOINT_CONFLICT')
        selected[point.name]=point
    if set(selected)!=set(names):raise HarnessError('HARNESS_UNAVAILABLE')
    providers=[]
    for name in names:
        try:
            factory=selected[name].load()
            if not callable(getattr(factory,'build',None)):raise HarnessError('HARNESS_FACTORY_INVALID')
            providers.append(factory.build(bindings_by_provider[name]))
        except HarnessError:raise
        except Exception:raise HarnessError('HARNESS_PROVIDER_UNAVAILABLE') from None
    return HarnessCatalog(providers)


def build_agent_registry_host(owner,*,invocation_resolver,native_write_guard,profile_guard):
    """Default current Agent/Profile selection on the SAME assembled owner.

    Missing original authorities refuse composition; no grant or endpoint Use is
    manufactured. The product retains owner lifetime outside ephemeral commands.
    """
    from ordessa_agents.public import InteractionService,ProfileService
    from ordessa_agents.capability.native import build_native_capability
    from ordessa_agents.capability.profiles import build_profile_capability
    if (type(owner.interactions) is not InteractionService or type(owner.profile_service) is not ProfileService
            or owner.interactions.records is not owner.records or owner.manager.records is not owner.records):
        raise TypeError('single original Agent owner required')
    from ordessa_agents.capability.agent_group import build_agent_group
    capabilities=[build_agent_group(
        build_profile_capability(owner.profile_service,invocation_resolver=invocation_resolver,guard=profile_guard),
        build_native_capability(owner.interactions,invocation_resolver=invocation_resolver,write_guard=native_write_guard))]
    return CapabilityHost(build_registry(capabilities),('profiles','agents'))



def build_agent_registry_runtime(owner,authority,*,context_factory,invocation_resolver,
        native_write_guard,profile_guard,server_id,close=None):
    """Default long-lived native/Profile selection, sharing ORIGINAL authority.

    The existing Server identity and authenticated invocation mapping are supplied
    by trusted composition; no token/database/permission is created here.
    """
    from ordessa_server.composition.registry_runtime import RegistryRuntime
    if (getattr(owner.interactions.authority,'authority',None) is not authority
            or getattr(getattr(profile_guard,'__self__',None),'authority',None) is not authority):
        raise TypeError('native/Profile must share the original instance authority')
    host=build_agent_registry_host(owner,invocation_resolver=invocation_resolver,
        native_write_guard=native_write_guard,profile_guard=profile_guard)
    return RegistryRuntime(host,authority,context_factory=context_factory,server_id=server_id,close=close)


def build_product_registry_runtime(data_root,product,authority,*,context_factory,server_id,authority_factory=None,deadline_seconds=30.0):
    """Current product -> original root -> original Agent owner -> F1 registry.

    Trusted dependencies must be known before acquiring/creating a root. The
    identity may be supplied directly (controlled host) or built by
    `authority_factory(root)` *after* the root lock is held — the latter is how the
    production path creates the instance token file inside a root it owns and
    nowhere else. The returned runtime retains the owner and OS lock; closing
    revokes SDK access. No core.sqlite is created/adopted or historical schema
    activated here.
    """
    from ordessa_server.composition.root_ownership import DataRootOwner
    from ordessa_server.composition.registry_runtime import RegistryRuntime
    from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority
    if authority_factory is not None and authority is not None:
        raise TypeError('one origin for the original instance authority')
    if authority_factory is None and type(authority) is not InstanceAccessAuthority:
        raise TypeError('original instance authority/context mapping required')
    if authority_factory is not None and not callable(authority_factory):
        raise TypeError('callable original instance authority factory required')
    if not callable(context_factory):
        raise TypeError('original instance authority/context mapping required')
    product.require_trusted_startup()
    if type(server_id) is not str or not server_id or len(server_id)>512:
        raise ValueError('original bounded Server identity required')
    root=Path(data_root)
    if not root.is_absolute():raise ValueError('explicit absolute product root required')
    root_owner=DataRootOwner(root);root_owner.acquire()
    owner=None
    try:
        (root/'state').mkdir(mode=0o700,exist_ok=True)
        store=root/'state'/'core.sqlite';child=root/'state'/'agent-owner'/'agent-instances.sqlite'
        binding=root_owner.bind_owned_root(root_path=root,store_path=store,child_path=child)
        live_authority=(authority_factory(root) if authority_factory is not None else authority)
        if type(live_authority) is not InstanceAccessAuthority:
            raise TypeError('original instance authority required')
        owner=product.assemble_owner(store,binding,authority=live_authority)
        capabilities=product.build_capabilities(owner)
        host=CapabilityHost(build_registry(capabilities),tuple(c.descriptor.id for c in capabilities))
        def close():
            try:owner.revoke()
            finally:root_owner.release()
        runtime=RegistryRuntime(host,live_authority,context_factory=context_factory,server_id=server_id,close=close,deadline_seconds=deadline_seconds)
        runtime.agent_owner=owner
        return runtime
    except BaseException:
        try:
            if owner is not None:owner.revoke()
        finally:root_owner.release()
        raise
