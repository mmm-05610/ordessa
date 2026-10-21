"""Assemble the default product's trusted inputs from one ServiceConfiguration.

Everything here is construction: no operation is served from this module. The
order matters and is deliberate — the instance token file and the Profile owner
are created only *inside a data root this process has already locked*, while the
authority, the pinned Harness catalog and the refusal ports are inert objects.

The Agent domain is assembled from the real owners: the environment owner
publishes the endpoints, the agents-owned bridges adapt them, and the instance
identity is the only authority over every start, prompt, native dispatch and
lifecycle write. Nothing here manufactures a grant, an endpoint or an instance.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import stat
from typing import Callable

from ordessa_agents.capability.agent_group import build_agent_group
from ordessa_agents.capability.harness import build_harness_capability
from ordessa_agents.capability.instances import build_agent_capability
from ordessa_agents.capability.native import build_native_capability
from ordessa_agents.capability.profiles import build_profile_capability
from ordessa_agents.bridges.environment_endpoints import EnvironmentEndpointResolver
from ordessa_agents.harness.preparation import PreparationResolver
from ordessa_agents.harness.providers.installed import (
    installed_provider_names,
    pinned_binding,
)
from ordessa_agents.public import HarnessCatalog
from ordessa_environments import EnvironmentRefused, ProcessRequest
from ordessa_interfaces.system_access import RequestContext
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant,
    InstanceAccessAuthority,
    VerifiedPrincipal,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.agent_authority import (
    ServerAgentAuthority,
    ServerInteractionAuthority,
    ServerPromptWriteGuard,
)
from ordessa_server.composition.agent_owner import AgentOwnerInputs, AgentOwnerUnavailable
from ordessa_server.composition.packages_convergence import build_harness_catalog
from ordessa_server.composition.profile_owner import (
    ServerProfileOwner,
    build_server_profile_owner,
)

from .service_configuration import ServiceConfiguration

#: The six brands this product's Local matrix is defined over (T08). Zero-config
#: admission is their intersection with what is installed; an explicit
#: configuration may name any other installed provider.
DEFAULT_HARNESS_BRANDS: "tuple[str, ...]" = (
    "kilo", "pi", "claude", "codex", "hermes", "dsh",
)

#: The root keys a prepared session may bind. The Server owns these private
#: directories inside the locked data root; the endpoint owner still creates and
#: reports the directory it exports for every root.
SESSION_ROOTS: "tuple[str, ...]" = (
    "work", "home", "config", "data", "state", "cache", "tmp",
    #: dsh declares this extra private root and refuses a session without it.
    "dsh-home",
)

_MAX_TOKEN_BYTES = 4096


def default_harness_allowlist() -> "tuple[str, ...]":
    installed = set(installed_provider_names())
    return tuple(name for name in DEFAULT_HARNESS_BRANDS if name in installed)


class ServiceStartupError(RuntimeError):
    """The configured instance identity or catalog cannot be constructed."""

    code = "SERVICE_STARTUP_UNAVAILABLE"


# -- instance token ----------------------------------------------------------

def _private_text(path: Path) -> str:
    """Read one private (0600) token file; no symlinks, printable ASCII only."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ServiceStartupError("instance token file is unavailable") from None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ServiceStartupError("instance token file must be a private regular file (0600)")
        raw = stream.read(_MAX_TOKEN_BYTES + 1)
    if len(raw) > _MAX_TOKEN_BYTES:
        raise ServiceStartupError("instance token file is oversized")
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError:
        raise ServiceStartupError("instance token file is not ASCII") from None
    if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise ServiceStartupError("instance token file has no usable token value")
    return token


def provision_instance_token(path: Path) -> bool:
    """Create the instance token 0600 if absent; return True when created.

    Must run inside an already locked data root. An existing file is validated,
    never rewritten: replacing material would invalidate every live client.
    """
    if not isinstance(path, Path) or not path.is_absolute():
        raise ServiceStartupError("an absolute instance token path is required")
    parent = path.parent
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = parent.lstat()
    except OSError:
        raise ServiceStartupError("instance token directory is unavailable") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ServiceStartupError("instance token directory must be a real directory")
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        _private_text(path)
        return False
    except OSError:
        raise ServiceStartupError("instance token cannot be created") from None
    try:
        os.write(fd, secrets.token_urlsafe(32).encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    _private_text(path)
    return True


# -- authority and request binding ------------------------------------------

def build_authority(configuration: ServiceConfiguration) -> InstanceAccessAuthority:
    """One instance bearer identity with finite, exact-scope grants."""
    access = configuration.access
    scope = Scope(access.realm, access.project)
    legacy = "local" if access.principal_id == "local" else None
    return InstanceAccessAuthority(
        lambda: _private_text(access.token_file),
        principal_id=access.principal_id,
        grants=(AccessGrant(scope, access.grants),),
        legacy_principal=legacy,
    )


def build_context_factory(configuration: ServiceConfiguration) -> Callable[..., RequestContext]:
    """Map the authenticated caller onto this request's context and invocation."""

    def context_factory(caller, request_id, deadline):
        if type(caller) is not VerifiedPrincipal:
            raise ServiceStartupError("verified instance caller required")
        return RequestContext(
            principal={"id": caller.principal_id, "epoch": caller.credential_epoch},
            request_id=request_id,
            deadline=deadline,
            invocation=caller,
        )

    return context_factory


def invocation_resolver(context):
    """Resolve the trusted caller (principal + owner scope); absence refuses.

    The capability handlers receive the request context; the agents-owned
    endpoint bridge receives the invocation that was already resolved from that
    same context. Both are the one verified instance caller, so a single
    resolver serves both ports and neither port can substitute its own object.
    """
    from ordessa_server.composition.invocation import (
        ServerInvocation,
        invocation_from_context,
    )
    if type(context) is ServerInvocation:
        return context
    return invocation_from_context(context)


# -- pinned Harness catalog --------------------------------------------------

def build_catalog(configuration: ServiceConfiguration) -> HarnessCatalog:
    """Admit exactly the configured installed providers, pinned by digest."""
    from importlib.metadata import entry_points

    allowed = tuple(configuration.harness_allowlist)
    if not allowed:
        return HarnessCatalog(())
    installed = {point.name: point for point in entry_points(group="ordessa.harness_providers")}
    missing = [name for name in allowed if name not in installed]
    if missing:
        raise ServiceStartupError("configured Harness provider is not installed: " + ", ".join(missing))
    bindings = {
        name: pinned_binding(installed[name], environment_namespace=configuration.profiles_namespace)
        for name in allowed
    }
    try:
        return build_harness_catalog(allowlist=tuple(allowed), bindings_by_provider=bindings)
    except Exception as error:
        raise ServiceStartupError("Harness catalog is unavailable: " + type(error).__name__) from None


# -- the real endpoint and preparation ports ---------------------------------

def build_session_roots(data_root: Path) -> "dict[str, str]":
    """The private root directories this Server approves for a prepared session.

    Every directory lives inside the locked data root, is absolute and is
    created private (0700) before it is approved. The endpoint owner still
    creates and reports the directory it exports for every root; this map is
    the Server's own approval of the root keys.
    """
    if not isinstance(data_root, Path) or not data_root.is_absolute():
        raise AgentOwnerUnavailable('an absolute product root is required')
    base = data_root / 'state' / 'agents'
    roots = {}
    for key in SESSION_ROOTS:
        path = base / key
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        roots[key] = str(path)
    return roots


class ServerPreparationResolver:
    """The agents-owned preparation port, refused in the original manager's type.

    The preparation port raises its own refusal type; the Agent capability
    understands the original manager/interaction refusal types. Mapping the
    REFUSAL (never the decision) keeps a refused preparation a known refusal:
    preparation produces a plan and never an effect, so an "unknown outcome"
    would claim more uncertainty than the owner has.
    """

    def __init__(self, inner) -> None:
        self._inner = inner

    def resolve(self, request, bound, invocation):
        from ordessa_agents.preparation import PreparationRefused
        from ordessa_agents.public import ManagerRefused
        try:
            return self._inner.resolve(request, bound, invocation)
        except PreparationRefused as error:
            raise ManagerRefused(error.code, str(error)) from None


def build_agent_ports(environment_owner, *, catalog: HarnessCatalog,
                      profile_service, lifecycle_authority, roots, providers=None):
    """The agents-owned ports over the environment owner's real endpoints.

    ``EnvironmentEndpointResolver`` adapts the environment owner's endpoint
    service to the Agent runtime; it names no environment owner of its own and
    it never acquires a resource. ``PreparationResolver`` is the agents-owned
    preparation port: it binds one Profile revision to one bound endpoint and
    produces the launch context the provider consumes.

    ``providers`` is the configured per-brand launch configuration (command,
    env, envFrom). It is the same trusted configuration the CLI reads from its
    own harness configuration, and it is handed to the preparation port
    unchanged: an absent section means no override, so every brand launches
    its own declared command.
    """
    endpoints = environment_owner.services.endpoints
    resolver = EnvironmentEndpointResolver(
        endpoints,
        invocation_resolver=invocation_resolver,
        process_request_factory=ProcessRequest.build,
        refusal=EnvironmentRefused,
    )
    preparation = ServerPreparationResolver(PreparationResolver(
        profile_service=profile_service, catalog=catalog, endpoints=endpoints,
        authority=lifecycle_authority, roots=roots,
        harness_config=dict(providers or {})))
    return resolver, preparation


def build_owner_inputs(
    *,
    configuration: ServiceConfiguration,
    authority: InstanceAccessAuthority,
    catalog: HarnessCatalog,
    profile_owner: ServerProfileOwner,
    endpoint_resolver,
    preparation_resolver,
    environment_owner=None,
    decision_owner=None,
) -> AgentOwnerInputs:
    """Assemble the existing Agent-owner inputs over this slice's real Profile owner."""

    def capabilities(owner):
        built = []
        for capability_id in configuration.capabilities:
            if capability_id == "agents":
                parts = [build_profile_capability(
                    owner.profile_service,
                    invocation_resolver=invocation_resolver,
                    guard=profile_owner.guard.guard,
                )]
                # The Harness catalog is part of the same `agents` group: it is
                # already assembled and pinned, so advertising what it admits is
                # an observed fact, not a promise.
                parts.append(build_harness_capability(catalog, admission={}))
                # The instance and native parts are bound to the SAME original
                # owner and to the instance identity: the physical write cut is
                # the Server's own guard, never a permissive default.
                write_guard = ServerPromptWriteGuard(authority)
                parts.append(build_agent_capability(
                    owner.manager, owner.interactions,
                    invocation_resolver=invocation_resolver,
                    write_guard=write_guard,
                ))
                parts.append(build_native_capability(
                    owner.interactions,
                    invocation_resolver=invocation_resolver,
                    write_guard=write_guard,
                ))
                built.append(build_agent_group(*parts))
            elif capability_id == "environments":
                if environment_owner is None:
                    raise AgentOwnerUnavailable('environments capability declared but not assembled')
                built.append(environment_owner.capability)
            elif capability_id == "decisions":
                if decision_owner is None:
                    raise AgentOwnerUnavailable('decisions capability declared but not assembled')
                built.append(decision_owner.capability)
            else:  # guarded by the configuration loader; never silently skipped
                raise AgentOwnerUnavailable('capability is declared but not assembled: ' + capability_id)
        return tuple(built)

    def close_owners():
        try:
            if decision_owner is not None:
                decision_owner.close()
        finally:
            try:
                if environment_owner is not None:
                    environment_owner.close()
            finally:
                profile_owner.close()

    # Lifecycle/interaction policy is the real instance identity; the endpoint
    # and preparation ports are the real bridges over the environment owner.
    lifecycle = ServerAgentAuthority(authority)
    interaction = ServerInteractionAuthority(authority)
    return AgentOwnerInputs(
        profile_owner.service,
        catalog,
        endpoint_resolver,
        preparation_resolver,
        lifecycle,
        interaction,
        capabilities,
        close_owners,
    )


def build_root_inputs(
    data_root: Path,
    configuration: ServiceConfiguration,
    *,
    authority: InstanceAccessAuthority,
    root_ownership_proof,
) -> "tuple[AgentOwnerInputs, ServerProfileOwner]":
    """Construct every root-scoped owner for one startup.

    The caller must already hold the data-root lock: the instance token file, the
    Profile store and its key material are created here and nowhere else. The
    returned profile owner is closed through `AgentOwnerInputs.close`, so a later
    construction failure revokes and closes it in the existing owner order.
    """
    provision_instance_token(configuration.access.token_file)
    catalog = build_catalog(configuration)
    profile_owner = build_server_profile_owner(
        data_root,
        namespace=configuration.profiles_namespace,
        principal_scope=configuration.principal_scope,
        authority=authority,
        scope=Scope(configuration.access.realm, configuration.access.project),
        validator=catalog,
    )
    environment_owner = None
    try:
        if "environments" in configuration.capabilities:
            from ordessa_server.composition.environment_owner import build_environment_owner
            environment_owner = build_environment_owner(
                data_root, authority=authority, invocation_resolver=invocation_resolver)
        decision_owner = None
        if "decisions" in configuration.capabilities:
            from ordessa_server.composition.decision_owner import build_decision_owner
            decision_owner = build_decision_owner(data_root, invocation_resolver=invocation_resolver)
        # The Agent domain needs the environment owner's real endpoints; without
        # that owner the instance operations are not assembled at all.
        if environment_owner is None:
            raise AgentOwnerUnavailable(
                'the agents capability needs the environments owner for its endpoints')
        endpoint_resolver, preparation_resolver = build_agent_ports(
            environment_owner, catalog=catalog, profile_service=profile_owner.service,
            lifecycle_authority=ServerAgentAuthority(authority),
            roots=build_session_roots(data_root),
            providers=configuration.harness_providers)
        inputs = build_owner_inputs(configuration=configuration, authority=authority,
                                    catalog=catalog, profile_owner=profile_owner,
                                    endpoint_resolver=endpoint_resolver,
                                    preparation_resolver=preparation_resolver,
                                    environment_owner=environment_owner,
                                    decision_owner=decision_owner)
    except BaseException:
        if environment_owner is not None:
            environment_owner.close()
        profile_owner.close()
        raise
    return inputs, profile_owner


__all__ = [
    "ServiceStartupError", "SESSION_ROOTS", "ServerPreparationResolver",
    "build_agent_ports", "build_authority",
    "build_catalog", "DEFAULT_HARNESS_BRANDS", "build_context_factory",
    "build_owner_inputs", "build_root_inputs", "build_session_roots",
    "default_harness_allowlist",
    "invocation_resolver", "installed_provider_names", "provision_instance_token",
]
