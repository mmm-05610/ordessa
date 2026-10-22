"""The single ``ordessa`` CLI entry.

One console, three capability groups, two explicit modes. Domain composition is
lazy: help, ``list`` and ``describe`` use static descriptors and open no store
or brand runtime; a command builds only the owner it addresses.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

from ordessa_agents.preparation import PreparationRefused
from ordessa_interfaces.channels import cli as channel
from ordessa_system_access_client import CapabilityClient, ClientError, load_service

from .composition.agents import AgentRefused, build_agent_domain, build_profile_domain
from .composition.decisions import build_decision_domain
from .composition.environments import build_environment_domain
from .composition.remote import RemoteHost, RemoteRefused, load_remote_registry
from .composition.defaults import DefaultTargetRefused, default_service
from .composition.state import LocalState, StateRefused

_DOMAINS = {
    'environments': 'environments',
    'agents': 'agents',
    'profiles': 'agents',
    'decisions': 'decisions',
}


class _BoundHost:
    """One built domain host plus the auth callable and its close callback."""

    def __init__(self, host, authenticate, close):
        self.host = host
        self.registry = host.registry
        self.authenticate = authenticate
        self._close = close

    async def call(self, operation_id, request, context):
        return await self.host.call(operation_id, request, context)

    def envelope(self, *, command, request_id, result):
        return self.host.envelope(command=command, request_id=request_id, result=result)

    def close(self):
        if self._close is not None:
            self._close()


def _metadata(*, remote=False):
    """Static metadata. Session-only retained-handle operations are hidden locally
    (a one-shot local process cannot hold them) but published in remote mode, where
    the Server owns the handles."""
    from ordessa_environments.capability import descriptor as environments
    from ordessa_agents.capability.harness import descriptor as harness
    from ordessa_agents.capability.instances import descriptor as instances
    from ordessa_agents.capability.profiles import descriptor as profiles
    from ordessa_decision.capability import descriptor as decisions
    from .composition.environments import SESSION_ONLY
    operations = [*environments().operations, *instances(include_native=remote, include_cancel=True).operations,
                  *profiles().operations, *harness().operations, *decisions().operations]
    return [operation for operation in operations if remote or operation.id not in SESSION_ONLY]


def _options(argv):
    """Remove the explicit mode selectors; everything else is channel input.

    Three mutually exclusive ways to address an owner: `--state` (local), or a
    remote target named by `--config/--service` or by `--data-root` (or nothing,
    which means the default data root). A flag is never a hint for another mode.
    """
    state = config = service = data_root = None
    rest = []
    index = 0
    tokens = list(argv)
    while index < len(tokens):
        token = tokens[index]
        if token == '--':
            rest.extend(tokens[index:])
            break
        matched = False
        for flag in ('--state', '--config', '--service', '--data-root'):
            if token == flag:
                if index + 1 >= len(tokens):
                    raise StateRefused(f'{flag} needs a value')
                value = tokens[index + 1]
                if flag == '--state':
                    state = value
                elif flag == '--config':
                    config = value
                elif flag == '--service':
                    service = value
                else:
                    data_root = value
                index += 2
                matched = True
                break
            if token.startswith(flag + '='):
                value = token.split('=', 1)[1]
                if flag == '--state':
                    state = value
                elif flag == '--config':
                    config = value
                elif flag == '--service':
                    service = value
                else:
                    data_root = value
                index += 1
                matched = True
                break
        if matched:
            continue
        rest.append(token)
        index += 1
    if state is None and config is None and service is None:
        state = os.environ.get('ORDESSA_STATE')
    if (config is None) != (service is None):
        raise StateRefused('--config and --service must be supplied together')
    if state is not None and (config is not None or data_root is not None):
        raise StateRefused('--state (local) and a remote target are mutually exclusive')
    if config is not None and data_root is not None:
        raise StateRefused('--config names its endpoint; --data-root is for the default target')
    return state, config, service, data_root, rest


_GLOBAL_WITH_VALUE = ('--request-id', '--timeout', '--save-result')
_GLOBAL_SWITCHES = ('--json', '--help', '-h')


def _command_tokens(tokens):
    """Drop global options so the command path can be identified lazily."""
    result = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _GLOBAL_SWITCHES:
            index += 1
            continue
        if token in _GLOBAL_WITH_VALUE:
            index += 2
            continue
        if any(token.startswith(flag + '=') for flag in _GLOBAL_WITH_VALUE):
            index += 1
            continue
        result.extend(tokens[index:])
        break
    return result


def _domain_for(tokens):
    tokens = _command_tokens(tokens)
    if not tokens:
        return None
    # Profile and harness commands never address the Environment owner, so they
    # get a Profile-only host instead of composing Environment, Use and records.
    if tokens[0] == 'agents' and len(tokens) > 1 and tokens[1] in ('profiles', 'harness'):
        return 'profiles'
    if tokens[0] in ('list', 'describe'):
        return None
    if tokens[0] == 'call':
        if len(tokens) < 2:
            return 'invalid'
        operation = tokens[1]
        prefix = operation.split('.', 1)[0]
        return _DOMAINS.get(prefix, 'invalid')
    if tokens[0] == 'session':
        return 'session'
    return _DOMAINS.get(tokens[0], 'invalid')


def _local_domain(state: LocalState, domain: str):
    if domain == 'environments':
        owner = build_environment_domain(state, session=False)
        return _BoundHost(owner.host, owner.authority.authenticate, owner.close)
    if domain == 'agents':
        owner = build_agent_domain(state, session=False)
        return _BoundHost(owner.host, owner.environment.authority.authenticate, owner.close)
    if domain == 'profiles':
        owner = build_profile_domain(state)
        return _BoundHost(owner.host, owner.authority.authenticate, owner.close)
    if domain == 'decisions':
        owner = build_decision_domain(state)
        return _BoundHost(owner.host, owner.authority.authenticate, owner.close)
    raise StateRefused('no domain selected')


def _remote_service_domain(service):
    client = CapabilityClient(service, timeout=30)
    registry = load_remote_registry(client)
    host = RemoteHost(client=client, registry=registry)
    authenticate = lambda command: {'kind': 'remote-service', 'id': service.alias}
    return _BoundHost(host, authenticate, None)


def _remote_domain(config: str, service_name: str):
    return _remote_service_domain(load_service(config, service_name))


def _default_remote_domain(data_root):
    """The zero-configuration target: a deterministic refusal, never a local fallback."""
    service = default_service(data_root=data_root)
    try:
        return _remote_service_domain(service)
    except ClientError as error:
        raise DefaultTargetRefused(
            f"no reachable ordessa-server at {service.endpoint} ({error.code}); "
            "start `ordessa-server` for the default instance, or pass --state/--config explicitly"
        ) from None


def _report_failure(rest, code, message, exit_code):
    """One deterministic failure surface; JSON mode keeps the single envelope."""
    print(f'ordessa: {message}', file=sys.stderr)
    if '--json' in rest:
        envelope = {'apiVersion': 'agent-tools/1', 'requestId': uuid.uuid4().hex,
                    'command': ' '.join(rest), 'status': 'refused', 'data': None,
                    'error': {'code': code, 'message': message, 'retryable': False},
                    'operationRef': None, 'evidenceRefs': []}
        print(json.dumps(envelope, ensure_ascii=False, sort_keys=True))
    return exit_code


_CLIENT_EXIT = {
    'INVALID_INPUT': 2, 'PERMISSION_DENIED': 2, 'AUTHORITY_UNAVAILABLE': 2,
    'CAPABILITY_UNSUPPORTED': 4, 'ENDPOINT_UNAVAILABLE': 4, 'PROVIDER_UNAVAILABLE': 4,
    'CONFLICT': 5, 'PROTOCOL_INVALID': 5, 'EFFECT_UNKNOWN': 6,
    'CLEANUP_PENDING': 6, 'OBSERVATION_TIMEOUT': 7,
}


def _client_failure(rest, error):
    # The client's own exit codes include 3 for authorization; the command
    # contract maps PERMISSION_DENIED to 2. Always publish the contract code.
    code = {2: 'INVALID_INPUT', 3: 'PERMISSION_DENIED', 4: 'CAPABILITY_UNSUPPORTED',
            5: 'CONFLICT', 6: 'EFFECT_UNKNOWN', 7: 'OBSERVATION_TIMEOUT'}.get(
                error.exit_code, 'INVALID_INPUT')
    return _report_failure(rest, code, error.message, _CLIENT_EXIT.get(code, 2))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        state_path, config, service, data_root, rest = _options(argv)
    except StateRefused as error:
        print(f'ordessa: {error}', file=sys.stderr)
        return 2
    remote = config is not None or state_path is None
    metadata = _metadata(remote=remote)
    if not rest or rest[0] in ('--help', '-h'):
        try:
            channel.render_help([token for token in rest if token not in ('--help', '-h')],
                                metadata, sys.stdout)
        except Exception:
            channel.render_help([], metadata, sys.stdout)
        return 0
    if '--help' in rest or '-h' in rest:
        try:
            channel.render_help([token for token in rest if token not in ('--help', '-h')],
                                metadata, sys.stdout)
        except Exception:
            channel.render_help([], metadata, sys.stdout)
        return 0
    domain = _domain_for(rest)
    if domain == 'session':
        if state_path is None:
            print('ordessa: session requires --state DIR', file=sys.stderr)
            return 2
        from .session import run_session
        try:
            state = LocalState.open(state_path)
        except StateRefused as error:
            print(f'ordessa: {error}', file=sys.stderr)
            return 2
        return asyncio.run(run_session(state))
    if domain == 'invalid':
        return channel.run(rest, metadata=metadata, stdin=sys.stdin.buffer,
                           stdout=sys.stdout, stderr=sys.stderr)
    if domain is None:
        return channel.run(rest, metadata=metadata, stdin=sys.stdin.buffer,
                           stdout=sys.stdout, stderr=sys.stderr)
    bound = None
    try:
        if config is not None:
            bound = _remote_domain(config, service)
        elif state_path is not None:
            bound = _local_domain(LocalState.open(state_path), domain)
        else:
            bound = _default_remote_domain(data_root)
        return channel.run(rest, host=bound, authenticate=bound.authenticate,
                           metadata=metadata, stdin=sys.stdin.buffer,
                           stdout=sys.stdout, stderr=sys.stderr)
    except ClientError as error:
        return _client_failure(rest, error)
    except DefaultTargetRefused as error:
        return _report_failure(rest, 'AUTHORITY_UNAVAILABLE', str(error), 4)
    except (StateRefused, AgentRefused, PreparationRefused, RemoteRefused, OSError) as error:
        return _report_failure(rest, 'INVALID_INPUT', str(error), 2)
    except Exception as error:
        from ordessa_decision import DecisionError
        from ordessa_environments import EnvironmentRefused
        from ordessa_agents.sdk.harness import HarnessError
        import sqlite3
        if isinstance(error, (EnvironmentRefused, HarnessError, DecisionError, sqlite3.Error)):
            return _report_failure(rest, 'INVALID_INPUT',
                                   'local composition refused: ' + type(error).__name__, 2)
        raise
    finally:
        if bound is not None:
            bound.close()


__all__ = ['main']
