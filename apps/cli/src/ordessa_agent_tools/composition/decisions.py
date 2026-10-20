"""Local Decision assembly over the original runner/evidence ports.

The rules engine is the installed CEL plugin, never a hand-written or always
true substitute. Engine absence is reported as an explicit refusal; validate
and cold reads remain available.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from decision_runtime import DecisionError, DecisionRunner, FilesystemEvidenceStore, load_rules_engine
from decision_runtime.capability import build_capability
from decision_runtime.evidence import EvidenceScope
from ordessa_interfaces.system_access import CapabilityHost, build_registry

from .identity import LocalForegroundAuthority
from .state import LocalState

DECISION_ACTIONS = frozenset({
    'decisions.validate', 'decisions.run', 'decisions.get',
    'decisions.evidence', 'decisions.query',
})


class DecisionDomain:
    def __init__(self, *, authority, host, capability, engine_error=None, provider_error=None):
        self.authority = authority
        self.host = host
        self.capability = capability
        self.engine_error = engine_error
        self.provider_error = provider_error

    def close(self):
        self.authority.revoke()


def build_decision_domain(state: LocalState) -> DecisionDomain:
    authority = LocalForegroundAuthority(actions=DECISION_ACTIONS)
    evidence = FilesystemEvidenceStore(state.decisions_root)
    engine = None
    engine_error = None
    try:
        engine = load_rules_engine('cel')
    except DecisionError as error:
        engine_error = error.code
    provider, provider_error = _provider(state)
    settings = _settings(evidence=evidence, engine=engine, provider=provider)

    def scope(invocation, operation):
        if operation not in DECISION_ACTIONS:
            raise DecisionError('permission_denied')
        return EvidenceScope('principal', invocation.owner_scope.ref)

    capability = build_capability(settings, invocation_resolver=authority.resolve,
                                  evidence_scope_resolver=scope)
    host = CapabilityHost(build_registry([capability]), ('decisions',))
    return DecisionDomain(authority=authority, host=host, capability=capability,
                          engine_error=engine_error, provider_error=provider_error)


def _provider(state: LocalState):
    """Optional real ask provider; configuration supplies only an env name."""
    path = state.root / 'decision.json'
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, None
    except OSError:
        return None, 'decision configuration is unreadable'
    try:
        config = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None, 'decision configuration is not JSON'
    if not isinstance(config, dict) or set(config) - {
            'provider', 'baseUrl', 'model', 'secretEnv', 'timeoutSeconds', 'longContext'}:
        return None, 'decision configuration shape is invalid'
    if config.get('provider') != 'jev':
        return None, 'decision provider is unsupported'
    base_url = config.get('baseUrl')
    model = config.get('model')
    secret_env = config.get('secretEnv')
    timeout = config.get('timeoutSeconds', 30)
    long_context = config.get('longContext', False)
    if type(long_context) is not bool:
        return None, 'decision provider configuration is invalid'
    if (not isinstance(base_url, str) or not base_url.startswith('https://')
            or not isinstance(model, str) or not model
            or not isinstance(secret_env, str) or not secret_env
            or not secret_env.replace('_', '').isalnum()
            or type(timeout) not in (int, float) or not 0 < timeout <= 300):
        return None, 'decision provider configuration is invalid'
    key = os.environ.get(secret_env)
    if not isinstance(key, str) or not key:
        return None, 'decision provider credential environment is unavailable'
    try:
        from ordessa_decision_jev import JevDecisionProvider, JevProviderSettings
        settings = JevProviderSettings(base_url=base_url.rstrip('/'), model=model,
                                       secret_ref='jev-api-key', timeout_seconds=float(timeout),
                                       long_context=long_context)
        provider = JevDecisionProvider(settings, secret_resolver=lambda ref: key)
    except Exception as error:
        return None, 'decision provider refused: ' + type(error).__name__
    return provider, None


def _settings(*, evidence, engine, provider=None):
    from decision_runtime.settings import DecisionsSettings
    return DecisionsSettings(
        runner_factory=DecisionRunner, evidence=evidence,
        default_engine=engine, engines={'cel': engine} if engine is not None else {},
        provider=provider)


__all__ = ['DECISION_ACTIONS', 'DecisionDomain', 'build_decision_domain']
