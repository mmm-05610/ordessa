"""Local Agent/Profile composition: real owner ports, one foreground process.

The CLI supplies an explicit environment endpoint and the local OS-user
invocation. Profile content, instance records, turns and effects stay in the
original owners; this module only connects them.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
import pathlib
from pathlib import Path
import shutil
import stat
import sys

from ordessa_execution_agents.capability import (
    build_agent_capability, build_harness_capability, build_profile_capability,
)
from ordessa_execution_agents.harness.providers.catalog import HarnessCatalog
from ordessa_execution_agents.profiles import encode_revision_ref
from ordessa_execution_agents.public import (
    AgentManager, InteractionService, Records,
)
from ordessa_execution_agents.sdk import BoundPath, PrepareContext, SessionBootstrap
from ordessa_execution_agents.sdk.prepare import canonical_digest, canonical_json
from ordessa_execution_agents.instances.contracts import PreparedAgentContext
from ordessa_interfaces.system_access import CapabilityHost, build_registry

from .endpoints import EnvironmentEndpointResolver
from .environments import EnvironmentDomain, build_environment_domain
from .identity import LocalForegroundAuthority
from .profile import build_profile_owner
from .state import LocalState, ensure_private_key

_HARNESS_GROUP = 'ordessa.harness_providers'
_BRAND_BINARY = {
    'kilo': 'kilo', 'hermes': 'hermes', 'gemini-cli': 'gemini', 'goose': 'goose',
    'grok-build': 'grok', 'dsh': 'dsh', 'claude': 'claude', 'codex': 'codex',
    'pi': 'pi', 'kimi': 'kimi', 'qwen': 'qwen', 'qoder': 'qoder', 'opencode': 'opencode',
    'copilot': 'copilot', 'vibe': 'vibe',
}
# Explicit launch data for the selected first-party brands; no secrets. Callers
# may override the executable through a trusted local configuration file.
_BRAND_ENV = {
    'kilo': {'KILO_CONFIG_CONTENT': '{"autoupdate":false}',
             'KILO_DISABLE_MODELS_FETCH': '1',
             'NODE_USE_SYSTEM_CA': '1',
             'SSL_CERT_FILE': '/etc/ssl/certs/ca-certificates.crt'},
    'pi': {'PI_CODING_AGENT_DIR': None},
    'codex': {'CODEX_HOME': None},
    'claude': {'CLAUDE_CONFIG_DIR': '$config'},
    'hermes': {'HERMES_HOME': None},
    # ``$root`` means "the private directory for that approved root": dsh
    # requires a native home distinct from HOME, so it cannot reuse HOME.
    'dsh': {'DSH_HOME': '$dsh-home'},
}
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

    def _allow(self, action, invocation):
        if action not in self.actions:
            raise AgentRefused('action is not locally enabled: ' + action,
                               code='CAPABILITY_UNSUPPORTED')
        return self._verified(invocation)

    def principal_scope(self, invocation):
        return self._verified(invocation)

    def check_start(self, invocation, request, descriptor):
        self._allow('agents.start', invocation)
        try:
            pin = dict(descriptor.definition_ref)
        except (TypeError, ValueError):
            raise AgentRefused('harness descriptor pin is unavailable',
                               code='HARNESS_UNAVAILABLE') from None
        if not pin:
            raise AgentRefused('harness descriptor pin is unavailable',
                               code='HARNESS_UNAVAILABLE')

    def check_lifecycle_write(self, invocation, binding):
        self._allow('agents.start', invocation)

    def check_read_instance(self, invocation, instance_id):
        self._allow('agents.get', invocation)

    def check_instance_lifecycle(self, invocation, control, action):
        self._allow('agents.stop' if action == 'stop' else 'agents.detach', invocation)

    @contextmanager
    def guard_instance_lifecycle(self, invocation, control, action):
        self._allow('agents.stop' if action == 'stop' else 'agents.detach', invocation)
        yield

    def check_read_binding(self, invocation, instance_ref):
        self._allow('agents.query', invocation)

    def check_read_turn(self, invocation, query):
        self._allow('agents.query', invocation)

    def check_send(self, invocation, binding):
        self._allow('agents.prompt', invocation)

    def check_cancel(self, invocation, binding):
        from ordessa_execution_agents.sdk.interactions import CancelBinding
        if type(binding) is not CancelBinding:
            raise AgentRefused('cancel binding is invalid', code='INVALID_INPUT')
        self._allow('agents.cancel', invocation)


class PromptWriteGuard:
    """Physical prompt/cancel cut: current local authority and single use."""

    def __init__(self, authority: LocalAgentAuthority):
        self._authority = authority

    @contextmanager
    def guard_write(self, binding, invocation):
        from ordessa_execution_agents.sdk.interactions import CancelBinding
        action = 'agents.cancel' if type(binding) is CancelBinding else 'agents.prompt'
        self._authority._allow(action, invocation)
        yield


class LocalPreparationResolver:
    """Build the approved launch context from real Profile/endpoint/material data."""

    def __init__(self, *, profile_service, catalog, endpoints, authority, state):
        self._profile_service = profile_service
        self._catalog = catalog
        self._endpoints = endpoints
        self._authority = authority
        self._state = state
        self._harness_config = {}

    def set_harness_config(self, providers):
        self._harness_config = dict(providers)

    def _command(self, definition_id, bound):
        entry = self._harness_config.get(definition_id, {})
        command = entry.get('command')
        if command:
            return tuple(command)
        executable = _BRAND_BINARY.get(definition_id, definition_id)
        if bound.descriptor.get('endpointKind') == 'remote-gateway':
            # A remote endpoint runs the harness inside its own file area; a host
            # PATH lookup would be meaningless (and a host path would not exist
            # there). The configured argv or the brand's command name is used
            # verbatim and resolved by the remote shell/runtime.
            return (executable,)
        resolved = shutil.which(executable)
        if not resolved:
            raise AgentRefused('selected harness executable is not installed: ' + executable)
        return (os.path.abspath(resolved),)

    def _materialize_credentials(self, descriptor, bound, content, directories):
        """Copy Profile-declared credential files into the private roots.

        The Profile carries only the binding (source path + target root/path);
        the bytes never enter the records, receipts or evidence. The target is
        created 0600 and must stay inside an approved root.
        """
        for declaration in content.declarations:
            if declaration.configuration_kind != 'credentials.file':
                continue
            if (declaration.schema_version != '1' or declaration.action != 'value'
                    or declaration.resource_refs):
                raise AgentRefused('credential binding declaration is invalid')
            try:
                payload = dict(declaration.payload)
            except (TypeError, ValueError):
                raise AgentRefused('credential binding declaration is invalid') from None
            if set(payload) != {'sourcePath', 'rootKey', 'relativePath'}:
                raise AgentRefused('credential binding declaration is invalid')
            source = payload['sourcePath']; root_key = payload['rootKey']
            relative = payload['relativePath']
            if any(type(item) is not str or not item or '\x00' in item
                   for item in (source, root_key, relative)):
                raise AgentRefused('credential binding declaration is invalid')
            if root_key not in descriptor.required_roots or root_key not in directories:
                raise AgentRefused('credential binding root is not approved: ' + root_key)
            parts = pathlib.PurePosixPath(relative).parts
            if pathlib.PurePosixPath(relative).is_absolute() or not parts or '..' in parts:
                raise AgentRefused('credential binding path escapes its root')
            if bound.descriptor.get('endpointKind') == 'remote-gateway':
                raise AgentRefused('credential bindings for a remote endpoint are not materialized yet')
            source_path = pathlib.Path(source)
            if not source_path.is_absolute():
                raise AgentRefused('credential binding source must be absolute')
            try:
                info = source_path.lstat()
            except OSError:
                raise AgentRefused('credential binding source is unavailable') from None
            if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > 262144:
                raise AgentRefused('credential binding source must be a small regular file')
            root_path = pathlib.Path(directories[root_key]).resolve()
            target = (root_path / relative).resolve()
            if root_path != target and root_path not in target.parents:
                raise AgentRefused('credential binding path escapes its root')
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            data = source_path.read_bytes()
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
            os.chmod(target, 0o600)

    def _directories(self, bound, descriptor, invocation):
        scope = invocation.owner_scope
        locator = bound.ref.projection()
        directories = {}
        for root in descriptor.required_roots:
            # The backend's file area owns existence and creation; a remote
            # provider's paths are inside its sandbox, not on the host filesystem.
            path = self._endpoints.directory_ready(locator, scope,
                BoundPath(root, '.').projection(), invocation=invocation, create=True)
            directories[root] = str(path)
        return directories

    def resolve(self, request, bound, invocation):
        self._authority._allow('agents.start', invocation)
        revision = self._profile_service.get_revision(request.profile_revision_ref)
        pin = dict(revision.content.harness_definition_ref)
        provider = self._catalog.resolve(pin)
        descriptor = provider.descriptor
        if dict(descriptor.definition_ref) != pin:
            raise AgentRefused('harness pin differs from the descriptor')
        if request.session_mode != 'fresh' or request.resume_ref is not None:
            raise AgentRefused('only a fresh native session is supported')
        if request.material_refs:
            raise AgentRefused('material preparation is not available in the local CLI')
        capabilities = tuple(bound.descriptor.get('capabilities', ()))
        if not {'launcher', 'communicate'} <= set(capabilities):
            raise AgentRefused('the endpoint does not export launcher/communicate')
        roots = set(bound.descriptor.get('rootKeys', ()))
        if not set(descriptor.required_roots) <= roots:
            raise AgentRefused('the endpoint does not export every required root')
        allowed_configurations = tuple(bound.descriptor.get('preparedConfigurations', ()))
        for ref in request.prepared_configuration_refs:
            if ref.projection() not in allowed_configurations:
                raise AgentRefused('prepared configuration is not bound to this endpoint')
            self._endpoints.verify(bound.ref.projection(), invocation.owner_scope,
                ref.projection(), invocation=invocation)
        directories = self._directories(bound, descriptor, invocation)
        remote = bound.descriptor.get('endpointKind') == 'remote-gateway'
        environment = {
            'HOME': directories['home'],
            # A remote endpoint has its own binary layout; the host PATH would
            # describe a different machine.
            'PATH': ('/usr/local/bin:/usr/bin:/bin' if remote
                     else os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')),
            'XDG_CONFIG_HOME': directories['config'],
            'XDG_DATA_HOME': directories['data'],
            'XDG_STATE_HOME': directories['state'],
            'XDG_CACHE_HOME': directories['cache'],
            'TMPDIR': directories['tmp'],
        }
        brand = _BRAND_ENV.get(descriptor.provider_id, {})
        for key, value in brand.items():
            if value is None:
                environment[key] = directories['home']
            elif value.startswith('$'):
                root = value[1:]
                if root not in directories:
                    raise AgentRefused('harness environment root is not bound: ' + root)
                environment[key] = directories[root]
            else:
                environment[key] = value
        provider_config = self._harness_config.get(descriptor.provider_id, {})
        for key, value in provider_config.get('env', {}).items():
            environment[key] = value
        for target, source in provider_config.get('envFrom', {}).items():
            value = os.environ.get(source)
            if type(value) is not str or not value:
                raise AgentRefused('credential environment source is unavailable: ' + source)
            environment[target] = value
        self._materialize_credentials(descriptor, bound, revision.content, directories)
        command = self._command(descriptor.provider_id, bound)
        prepared = request.prepared_configuration_refs
        context = PrepareContext(
            {'members': sorted(capabilities), 'harnessPin': pin},
            {root: BoundPath(root, '.') for root in descriptor.required_roots},
            command, environment, (), request.material_refs, prepared,
            SessionBootstrap('fresh', directories['work']))
        # A local root is identified by its host path and inode; a remote root
        # has no host inode at all (its path lives in the backend file area), so
        # the binding records the backend path and its remote kind instead.
        binding = canonical_digest({
            root: ({'path': directories[root], 'inode': os.stat(directories[root]).st_ino}
                   if not remote else {'path': directories[root], 'kind': 'remote'})
            for root in descriptor.required_roots})
        source = canonical_json(encode_revision_ref(revision.ref))
        captured = datetime.now(timezone.utc).isoformat()
        return PreparedAgentContext(context, source, binding, captured, directories['work'])


PROFILE_ACTIONS = frozenset({
    'profiles.capabilities', 'profiles.list', 'profiles.create', 'profiles.entry',
    'profiles.read', 'profiles.edit', 'profiles.clone', 'profiles.rename',
    'profiles.archive', 'profiles.restore', 'profiles.preview', 'profiles.readEntry',
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
                base.verify(invocation) and invocation))
        preparation = LocalPreparationResolver(
            profile_service=profile_owner.service, catalog=catalog,
            endpoints=environment.endpoints, authority=authority, state=state)
        preparation.set_harness_config(harness_config['providers'])
        interactions = InteractionService(records, authority, resolver,
            native_prompts=catalog.prompt_handlers())
        manager = AgentManager(
            resolver, records, profile_service=profile_owner.service,
            harness_resolver=catalog, preparation_resolver=preparation,
            lifecycle_authority=authority)
        capabilities = [
            build_profile_capability(profile_owner.service,
                invocation_resolver=base.resolve, guard=profile_owner.guard.guard),
            build_agent_capability(manager, interactions,
                invocation_resolver=base.resolve, write_guard=PromptWriteGuard(authority)),
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


__all__ = ['AgentDomain', 'AgentRefused', 'LocalAgentAuthority', 'LocalPreparationResolver',
           'ProfileDomain', 'PromptWriteGuard', 'build_agent_domain', 'build_harness_catalog',
           'build_profile_domain']
