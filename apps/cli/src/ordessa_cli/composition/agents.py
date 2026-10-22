"""Local Agent/Profile composition: real owner ports, one foreground process.

The CLI supplies an explicit environment endpoint and the local OS-user
invocation. Profile content, instance records, turns and effects stay in the
original owners; this module only connects them. The launch preparation
itself is the agents owner's shared port: the CLI contributes its approved
roots, its authority and its trusted harness configuration.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sys

from ordessa_agents.capability import (
    build_agent_capability, build_harness_capability, build_profile_capability,
)
from ordessa_agents.capability.agent_group import build_agent_group
from ordessa_agents.bridges.environment_endpoints import EnvironmentEndpointResolver
from ordessa_agents.harness.preparation import PreparationResolver
from ordessa_agents.harness.providers.catalog import HarnessCatalog
from ordessa_agents.public import (
    AgentManager, InteractionService, Records,
)
from ordessa_environments import EnvironmentRefused, ProcessRequest
from ordessa_interfaces.system_access import CapabilityHost, build_registry

from .environments import EnvironmentDomain, build_environment_domain
from .identity import LocalForegroundAuthority
from .profile import build_profile_owner
from .state import LocalState, ensure_private_key

_HARNESS_GROUP = 'ordessa.harness_providers'
# The local roots a prepared session may bind. The CLI owns these directories
# under its state directory; the endpoint owner still creates and reports the
# directory it exports for every root.
#: Private roots the CLI approves. ``dsh-home`` is declared by the dsh brand
#: (its provider refuses a session without that distinct root); approving it
#: here does not create it elsewhere — the endpoint owner still creates every
#: exported root inside the environment's own file area.
_SESSION_ROOTS = ('work', 'home', 'config', 'data', 'state', 'cache', 'tmp', 'dsh-home')
_HARNESS_CONFIG = 'harness.json'


class AgentRefused(RuntimeError):
    def __init__(self, message='', code='PREPARATION_REFUSED'):
        self.code = code
        super().__init__(message or code)


def _read_harness_config(state: LocalState) -> dict:
    path = state.root / _HARNESS_CONFIG
    try:
        import json
        raw = path.read_bytes()
    except FileNotFoundError:
        # Absence admits nothing: no installed provider is loaded unless the
        # state directory names it in an explicit allowlist.
        return {'providers': {}, 'allowlist': []}
    except OSError:
        raise AgentRefused('harness configuration is unreadable') from None
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise AgentRefused('harness configuration is not JSON') from None
    if not isinstance(value, dict) or set(value) - {'providers', 'allowlist'}:
        raise AgentRefused('harness configuration shape is invalid')
    allowlist = value.get('allowlist', [])
    if (not isinstance(allowlist, list) or len(allowlist) > 64
            or any(not isinstance(name, str) or not name or len(name) > 128 for name in allowlist)
            or len(set(allowlist)) != len(allowlist)):
        raise AgentRefused('harness allowlist must be a bounded list of unique provider ids')
    providers = value.get('providers', {})
    if not isinstance(providers, dict):
        raise AgentRefused('harness providers configuration is invalid')
    for name, entry in providers.items():
        if (not isinstance(name, str) or not isinstance(entry, dict)
                or set(entry) - {'command', 'env', 'envFrom'}):
            raise AgentRefused('harness provider configuration is invalid')
        command = entry.get('command')
        if command is not None and (not isinstance(command, list) or not command
                                    or any(not isinstance(item, str) or not item for item in command)):
            raise AgentRefused('harness command must be a bounded argv list')
        if set(entry) - {'command', 'env', 'envFrom'}:
            raise AgentRefused('harness provider configuration is invalid')
        environment = entry.get('env', {})
        if (not isinstance(environment, dict)
                or any(not isinstance(k, str) or not isinstance(v, str)
                       for k, v in environment.items())):
            raise AgentRefused('harness environment must be string values')
        if any(any(marker in key.upper() for marker in
                   ('TOKEN', 'SECRET', 'PASSWORD', 'APIKEY', 'API_KEY', 'CREDENTIAL'))
               for key in environment):
            raise AgentRefused('harness configuration cannot carry credentials')
        env_from = entry.get('envFrom', {})
        if (not isinstance(env_from, dict)
                or any(not isinstance(k, str) or not isinstance(v, str)
                       or not k or not v or not k.replace('_', '').isalnum()
                       or not v.replace('_', '').isalnum()
                       for k, v in env_from.items())
                or set(env_from) & set(environment)):
            raise AgentRefused('harness envFrom references are invalid')
    return {'providers': providers, 'allowlist': list(allowlist)}


def _session_roots(state: LocalState) -> dict:
    """The local roots this CLI approves for a prepared agent session.

    The preparation port binds only approved root keys. The endpoint owner
    still creates and reports the directory it exports for every root, so a
    remote endpoint keeps the path inside its own file area.
    """
    return {key: (state.work if key == 'work' else state.work / key)
            for key in _SESSION_ROOTS}


def build_harness_catalog(namespace: str, allowlist=()):
    """Load only allowlisted entry points; never claim admission from PATH.

    Admission is decided here, before any implementation is imported: an
    installed entry point that is not in the allowlist is recorded as rejected
    and its module is never loaded, so it cannot run import-time effects.
    """
    from importlib.metadata import entry_points
    providers = []
    failures = {}
    admitted = frozenset(allowlist)
    points = sorted(entry_points(group=_HARNESS_GROUP), key=lambda item: item.name)
    for point in points:
        if point.name not in admitted:
            failures[point.name] = 'not admitted by the harness allowlist'
            continue
        try:
            distribution_version = getattr(getattr(point, 'dist', None), 'version', None) or '0'
            pin = {'environmentNamespace': namespace, 'definitionId': point.name,
                   'revision': distribution_version}
            factory = point.load()
            module_name = getattr(type(factory), '__module__', '')
            module = sys.modules.get(module_name)
            path = getattr(module, '__file__', None)
            if not path or not os.path.isfile(path):
                failures[point.name] = 'implementation module unavailable'
                continue
            digest = 'sha256:' + hashlib.sha256(Path(path).read_bytes()).hexdigest()
            provider = factory.build({'definition_ref': pin, 'implementation_digest': digest})
            providers.append(provider)
        except Exception as error:  # one unavailable brand must not mask another
            failures[point.name] = type(error).__name__
    installed = {point.name for point in points}
    for name in sorted(admitted - installed):
        failures[name] = 'allowlisted provider is not installed'
    return HarnessCatalog(providers), failures


class LocalAgentAuthority:
    """Owner-specific authority on the SAME local OS-user invocation object."""

    def __init__(self, base: LocalForegroundAuthority, actions):
        self.base = base
        self.actions = frozenset(actions)
        self._revoked = False

    @property
    def principal_scope_value(self):
        return self.base.principal_scope

    def revoke(self):
        self._revoked = True

    def _verified(self, invocation):
        if self._revoked:
            raise AgentRefused('local authority revoked', code='AUTHORITY_UNAVAILABLE')
        return self.base.verify(invocation)

    def verify(self, invocation):
        return self._verified(invocation)

    def allow(self, action, invocation):
        """Authority port: the action must be locally enabled for this invocation.

        The shared preparation port asks through this method, so the decision
        and its refusal stay with the owner of the local invocation.
        """
        if action not in self.actions:
            raise AgentRefused('action is not locally enabled: ' + action,
                               code='CAPABILITY_UNSUPPORTED')
        return self._verified(invocation)

    def principal_scope(self, invocation):
        return self._verified(invocation)

    def check_start(self, invocation, request, descriptor):
        self.allow('agents.start', invocation)
        try:
            pin = dict(descriptor.definition_ref)
        except (TypeError, ValueError):
            raise AgentRefused('harness descriptor pin is unavailable',
                               code='HARNESS_UNAVAILABLE') from None
        if not pin:
            raise AgentRefused('harness descriptor pin is unavailable',
                               code='HARNESS_UNAVAILABLE')

    def check_lifecycle_write(self, invocation, binding):
        self.allow('agents.start', invocation)

    def check_read_instance(self, invocation, instance_id):
        self.allow('agents.get', invocation)

    def check_instance_lifecycle(self, invocation, control, action):
        self.allow('agents.stop' if action == 'stop' else 'agents.detach', invocation)

    @contextmanager
    def guard_instance_lifecycle(self, invocation, control, action):
        self.allow('agents.stop' if action == 'stop' else 'agents.detach', invocation)
        yield

    def check_read_binding(self, invocation, instance_ref):
        self.allow('agents.query', invocation)

    def check_read_turn(self, invocation, query):
        self.allow('agents.query', invocation)

    def check_send(self, invocation, binding):
        self.allow('agents.prompt', invocation)

    def check_cancel(self, invocation, binding):
        from ordessa_agents.sdk.interactions import CancelBinding
        if type(binding) is not CancelBinding:
            raise AgentRefused('cancel binding is invalid', code='INVALID_INPUT')
        self.allow('agents.cancel', invocation)


class PromptWriteGuard:
    """Physical prompt/cancel cut: current local authority and single use."""

    def __init__(self, authority: LocalAgentAuthority):
        self._authority = authority

    @contextmanager
    def guard_write(self, binding, invocation):
        from ordessa_agents.sdk.interactions import CancelBinding
        action = 'agents.cancel' if type(binding) is CancelBinding else 'agents.prompt'
        self._authority.allow(action, invocation)
        yield


PROFILE_ACTIONS = frozenset({
    'agents.profiles.capabilities', 'agents.profiles.list', 'agents.profiles.create', 'agents.profiles.entry',
    'agents.profiles.read', 'agents.profiles.edit', 'agents.profiles.clone', 'agents.profiles.rename',
    'agents.profiles.archive', 'agents.profiles.restore', 'agents.profiles.preview', 'agents.profiles.readEntry',
})


class ProfileDomain:
    """Profile/Harness-only host: no Environment store, Use or endpoint owner."""

    def __init__(self, *, profile_owner, catalog, failures, authority, host):
        self.profile_owner = profile_owner
        self.catalog = catalog
        self.failures = dict(failures)
        self.authority = authority
        self.host = host
        self.capabilities = ()

    def close(self):
        try:
            self.authority.revoke()
        finally:
            self.profile_owner.close()


def build_profile_domain(state: LocalState) -> ProfileDomain:
    """Compose only the Profile/Harness owners.

    ``agents profiles ...`` and ``agents harness ...`` never read or open the
    Environment store, so a Profile read cannot fail because an unrelated owner
    is unavailable, and no Environment file is created by a read-only command.
    """
    namespace = 'local-' + hashlib.sha256(str(state.root).encode()).hexdigest()[:16]
    harness_config = _read_harness_config(state)
    catalog, failures = build_harness_catalog(namespace, harness_config['allowlist'])
    authority = LocalForegroundAuthority(actions=PROFILE_ACTIONS)
    profile_owner = build_profile_owner(
        store_path=state.profiles_store, namespace=namespace,
        principal_scope=authority.principal_scope,
        key_material=ensure_private_key(state.fingerprint_key),
        catalog=catalog, authority=authority)
    capabilities = [
        build_profile_capability(profile_owner.service,
            invocation_resolver=authority.resolve, guard=profile_owner.guard.guard),
        build_harness_capability(catalog, admission=failures),
    ]
    host = CapabilityHost(build_registry(capabilities), ('profiles', 'agents.harness'))
    return ProfileDomain(profile_owner=profile_owner, catalog=catalog, failures=failures,
                         authority=authority, host=host)


class AgentDomain:
    def __init__(self, *, environment: EnvironmentDomain, profile_owner, catalog,
                 failures, manager, interactions, records, authority, host,
                 capabilities, environment_owned=True):
        self.environment = environment
        self.capabilities = tuple(capabilities)
        self.environment_owned = environment_owned
        self.profile_owner = profile_owner
        self.catalog = catalog
        self.failures = dict(failures)
        self.manager = manager
        self.interactions = interactions
        self.records = records
        self.authority = authority
        self.host = host

    def close(self):
        try:
            self.authority.revoke()
        finally:
            try:
                self.records.close()
            finally:
                self.profile_owner.close()
                if self.environment_owned:
                    self.environment.close()


def build_agent_domain(state: LocalState, *, session: bool = False,
                       environment: EnvironmentDomain | None = None) -> AgentDomain:
    environment_owned = environment is None
    if environment is None:
        environment = build_environment_domain(state, session=session)
    # Constructed owners are closed in reverse order if any later step refuses:
    # a constructor failure must not leak an authority, SQLite connection or the
    # environment it does not own.
    closers = []
    try:
        namespace = 'local-' + hashlib.sha256(str(state.root).encode()).hexdigest()[:16]
        harness_config = _read_harness_config(state)
        catalog, failures = build_harness_catalog(namespace, harness_config['allowlist'])
        base = environment.authority
        authority = LocalAgentAuthority(base, actions={
            'agents.start', 'agents.get', 'agents.query', 'agents.prompt',
            'agents.stop', 'agents.detach', 'agents.reconcile', 'agents.cancel',
        })
        closers.append(authority.revoke)
        profile_owner = build_profile_owner(
            store_path=state.profiles_store, namespace=namespace,
            principal_scope=base.principal_scope,
            key_material=ensure_private_key(state.fingerprint_key),
            catalog=catalog, authority=authority)
        closers.append(profile_owner.close)
        agent_path = state.agent_store
        records = Records(agent_path)
        closers.append(records.close)
        if agent_path.exists():
            os.chmod(agent_path, 0o600)
        resolver = EnvironmentEndpointResolver(
            environment.endpoints,
            invocation_resolver=lambda invocation: (
                base.verify(invocation) and invocation),
            process_request_factory=ProcessRequest.build,
            refusal=EnvironmentRefused)
        preparation = PreparationResolver(
            profile_service=profile_owner.service, catalog=catalog,
            endpoints=environment.endpoints, authority=authority,
            roots=_session_roots(state), harness_config=harness_config['providers'])
        interactions = InteractionService(records, authority, resolver,
            native_prompts=catalog.prompt_handlers(),
            native_codecs=catalog.native_codecs())
        manager = AgentManager(
            resolver, records, profile_service=profile_owner.service,
            harness_resolver=catalog, preparation_resolver=preparation,
            lifecycle_authority=authority)
        capabilities = [
            build_agent_group(
                build_profile_capability(profile_owner.service,
                    invocation_resolver=base.resolve, guard=profile_owner.guard.guard),
                build_agent_capability(manager, interactions,
                    invocation_resolver=base.resolve, write_guard=PromptWriteGuard(authority))),
            build_harness_capability(catalog, admission=failures),
        ]
        host = CapabilityHost(build_registry(capabilities),
                              ('profiles', 'agents', 'agents.harness'))
        return AgentDomain(environment=environment, profile_owner=profile_owner,
                           catalog=catalog, failures=failures, manager=manager,
                           interactions=interactions, records=records,
                           authority=authority, host=host, capabilities=capabilities,
                           environment_owned=environment_owned)
    except BaseException:
        for closer in reversed(closers):
            try:
                closer()
            except Exception:
                pass
        if environment_owned:
            try:
                environment.close()
            except Exception:
                pass
        raise


__all__ = ['AgentDomain', 'AgentRefused', 'LocalAgentAuthority',
           'ProfileDomain', 'PromptWriteGuard', 'build_agent_domain', 'build_harness_catalog',
           'build_profile_domain']
