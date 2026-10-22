"""Preparation port: build the approved launch context for a Harness provider.

This module is owned by the agents distribution and depends on no concrete
environment owner and on no application state directory. It binds one Profile
revision to one externally prepared endpoint and produces the launch context a
provider consumes: the approved private roots, the provider command, the
nonsecret launch environment and the private directory binding.

The caller injects every owner-specific piece:

``profile_service``
    The agents-owned Profile service that owns the revision.
``catalog``
    The agents-owned harness catalog that owns the pinned provider.
``endpoints``
    The caller's endpoint service. It owns directory existence and creation,
    so a local endpoint reports a host path and a remote endpoint reports the
    path inside its own file area. This port only calls it.
``authority``
    The caller's authority port. It decides whether a preparation may run and
    raises its own refusal when it may not.
``roots``
    The root keys the caller approves for a prepared session, mapped to the
    local directory the caller owns for that root. Only an approved key is
    bound; the endpoint owner still creates and reports the directory.
``harness_config``
    The caller's trusted local provider configuration: ``command``, ``env``
    and ``envFrom`` per provider.

Nothing here reads an application state file, resolves a host installation
layout for another owner or names an environment exception. A refusal raised
by this port is the agents' own preparation refusal; the injected authority
and the provider keep their own refusal types.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
import pathlib
import shutil
import stat
from types import MappingProxyType

from ..instances.contracts import PreparedAgentContext
from ..preparation import PreparationRefused
from ..profiles import encode_revision_ref
from ..sdk.harness import PrepareContext
from ..sdk.prepare import (
    BoundPath, SessionBootstrap, canonical_digest, canonical_json,
)

__all__ = ['PreparationResolver']

# Explicit launch data for the selected first-party brands; no secrets. The
# caller may override the executable and the environment through a trusted
# local configuration file.
_BRAND_BINARY = {
    'kilo': 'kilo', 'hermes': 'hermes', 'gemini-cli': 'gemini', 'goose': 'goose',
    'grok-build': 'grok', 'dsh': 'dsh', 'claude': 'claude', 'codex': 'codex',
    'pi': 'pi', 'kimi': 'kimi', 'qwen': 'qwen', 'qoder': 'qoder', 'opencode': 'opencode',
    'copilot': 'copilot', 'vibe': 'vibe',
}
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


class PreparationResolver:
    """Build the approved launch context from real Profile/endpoint data."""

    def __init__(self, *, profile_service, catalog, endpoints, authority, roots,
                 harness_config=None):
        self._profile_service = profile_service
        self._catalog = catalog
        self._endpoints = endpoints
        self._authority = authority
        self._roots = MappingProxyType({str(key): str(value)
                                        for key, value in dict(roots or {}).items()})
        self._harness_config = {}
        if harness_config is not None:
            self.set_harness_config(harness_config)

    def set_harness_config(self, providers):
        """Adopt the caller's trusted local provider configuration.

        The provider entry keeps its ``command`` (a bounded argv list), ``env``
        (explicit values) and ``envFrom`` (values read from the host
        environment) rules; nothing else is read from it.
        """
        self._harness_config = dict(providers)

    def _authorize(self, invocation):
        allow = getattr(self._authority, 'allow', None)
        if not callable(allow):
            raise PreparationRefused('preparation authority is unavailable')
        # The authority keeps its own refusal type and its own decision.
        allow('agents.start', invocation)

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
            raise PreparationRefused('selected harness executable is not installed: '
                                     + executable)
        return (os.path.abspath(resolved),)

    def _materialize_credentials(self, descriptor, bound, content, directories, invocation):
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
                raise PreparationRefused('credential binding declaration is invalid')
            try:
                payload = dict(declaration.payload)
            except (TypeError, ValueError):
                raise PreparationRefused('credential binding declaration is invalid') from None
            if set(payload) != {'sourcePath', 'rootKey', 'relativePath'}:
                raise PreparationRefused('credential binding declaration is invalid')
            source = payload['sourcePath']; root_key = payload['rootKey']
            relative = payload['relativePath']
            if any(type(item) is not str or not item or '\x00' in item
                   for item in (source, root_key, relative)):
                raise PreparationRefused('credential binding declaration is invalid')
            if root_key not in descriptor.required_roots or root_key not in directories:
                raise PreparationRefused('credential binding root is not approved: ' + root_key)
            parts = pathlib.PurePosixPath(relative).parts
            if pathlib.PurePosixPath(relative).is_absolute() or not parts or '..' in parts:
                raise PreparationRefused('credential binding path escapes its root')
            source_path = pathlib.Path(source)
            if not source_path.is_absolute():
                raise PreparationRefused('credential binding source must be absolute')
            try:
                info = source_path.lstat()
            except OSError:
                raise PreparationRefused('credential binding source is unavailable') from None
            if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > 262144:
                raise PreparationRefused('credential binding source must be a small regular file')
            data = source_path.read_bytes()
            if bound.descriptor.get('endpointKind') == 'remote-gateway':
                # A remote endpoint's private roots live in its backend file
                # area, not on the host: materialize through the environment's
                # own files port (digest-pinned, 0600) and never via a host path.
                try:
                    text = data.decode('utf-8')
                except UnicodeDecodeError:
                    raise PreparationRefused(
                        'credential binding source is not UTF-8 text') from None
                digest = 'sha256:' + hashlib.sha256(data).hexdigest()
                artifact = {'schemaVersion': 'configuration-artifact/1',
                            'target': BoundPath(root_key, relative).projection(),
                            'mediaType': 'application/json', 'textUtf8': text,
                            'digest': digest, 'mode': 0o600}
                try:
                    materialized = self._endpoints.materialize(
                        bound.ref.projection(), invocation.owner_scope, artifact,
                        request_id='credential-materialize/' + digest.split(':', 1)[1][:32],
                        invocation=invocation)
                except Exception:
                    raise PreparationRefused(
                        'remote credential materialization was refused') from None
                if (type(materialized) is not dict
                        or materialized.get('status') != 'completed'
                        or materialized.get('digest') != digest):
                    raise PreparationRefused(
                        'remote credential materialization did not complete')
                continue
            root_path = pathlib.Path(directories[root_key]).resolve()
            target = (root_path / relative).resolve()
            if root_path != target and root_path not in target.parents:
                raise PreparationRefused('credential binding path escapes its root')
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
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
            if root not in self._roots:
                raise PreparationRefused('harness root is not approved: ' + root)
            # The endpoint's file area owns existence and creation; a remote
            # provider's paths are inside its sandbox, not on the host
            # filesystem.
            path = self._endpoints.directory_ready(locator, scope,
                BoundPath(root, '.').projection(), invocation=invocation, create=True)
            directories[root] = str(path)
        return directories

    def resolve(self, request, bound, invocation):
        self._authorize(invocation)
        revision = self._profile_service.get_revision(request.profile_revision_ref)
        pin = dict(revision.content.harness_definition_ref)
        provider = self._catalog.resolve(pin)
        descriptor = provider.descriptor
        if dict(descriptor.definition_ref) != pin:
            raise PreparationRefused('harness pin differs from the descriptor')
        if request.session_mode != 'fresh' or request.resume_ref is not None:
            raise PreparationRefused('only a fresh native session is supported')
        if request.material_refs:
            raise PreparationRefused('material preparation is not available here')
        capabilities = tuple(bound.descriptor.get('capabilities', ()))
        if not {'launcher', 'communicate'} <= set(capabilities):
            raise PreparationRefused('the endpoint does not export launcher/communicate')
        roots = set(bound.descriptor.get('rootKeys', ()))
        if not set(descriptor.required_roots) <= roots:
            raise PreparationRefused('the endpoint does not export every required root')
        allowed_configurations = tuple(bound.descriptor.get('preparedConfigurations', ()))
        for ref in request.prepared_configuration_refs:
            if ref.projection() not in allowed_configurations:
                raise PreparationRefused('prepared configuration is not bound to this endpoint')
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
                    raise PreparationRefused('harness environment root is not bound: ' + root)
                environment[key] = directories[root]
            else:
                environment[key] = value
        provider_config = self._harness_config.get(descriptor.provider_id, {})
        for key, value in provider_config.get('env', {}).items():
            environment[key] = value
        for target, source in provider_config.get('envFrom', {}).items():
            value = os.environ.get(source)
            if type(value) is not str or not value:
                raise PreparationRefused('credential environment source is unavailable: ' + source)
            environment[target] = value
        self._materialize_credentials(descriptor, bound, revision.content, directories, invocation)
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
