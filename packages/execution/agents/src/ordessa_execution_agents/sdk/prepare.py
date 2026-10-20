"""F1.1 exact launch/artifact DTOs owned by the Agent/Profile distribution.

Additive completion of DESIGN §3.2-3.3: callable signatures are unchanged, and
no second DTO family is created. Everything here is a frozen value plus its own
closed JSON projection and digest; the only trust in these values is what an
endpoint adapter independently re-verifies at the actual effect boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

from .instances import EndpointRef

CAPABILITIES = frozenset({'launcher', 'observe', 'communicate', 'terminate', 'detach', 'files'})
SESSION_MODES = frozenset({'fresh', 'resume', 'none'})
ROOT_KEY = re.compile(r'[a-z][a-z0-9_-]{0,63}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
ENV_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,255}\Z')
MAX_ID = 512
MAX_ARGV = 256
MAX_ARGV_BYTES = 8192
MAX_ENV = 128
MAX_ENV_KEY = 256
MAX_ENV_VALUE = 8192
MAX_INLINE_ARTIFACT = 256 * 1024
MAX_INLINE_TOTAL = 1024 * 1024
MAX_PLAN_BYTES = 2 * 1024 * 1024
MAX_REFS = 128
MAX_FACTS_KEYS = 64
MAX_FACTS_BYTES = 64 * 1024
MAX_FACTS_DEPTH = 8
MAX_ERROR_DIAGNOSTIC = 256
MAX_ERROR_CODE = 128


class PrepareValueError(ValueError):
    """Closed, sanitized refusal for one frozen DTO value."""


def canonical_digest(value: Any) -> str:
    raw = canonical_json(value)
    return 'sha256:' + hashlib.sha256(raw.encode('utf-8')).hexdigest()


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(_thaw(value), sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise PrepareValueError('value must be finite JSON') from None


def _text(value, name, limit=MAX_ID):
    if type(value) is not str or not value or len(value) > limit:
        raise PrepareValueError(f'{name} must be a bounded nonempty string')
    if any(ord(char) < 0x20 or ord(char) == 0x7f for char in value):
        raise PrepareValueError(f'{name} must not contain control characters')
    if len(value.encode('utf-8')) > limit * 4:
        raise PrepareValueError(f'{name} is too long')
    return value


def _digest(value, name='digest'):
    if type(value) is not str or not value.startswith('sha256:') or not HEX64.match(value[7:]):
        raise PrepareValueError(f'{name} must be sha256:<64 hex>')
    return value


def _count(value, name='count'):
    if type(value) is not int or type(value) is bool or value < 0:
        raise PrepareValueError(f'{name} must be a nonnegative integer')
    return value


def _freeze(value):
    """Recursively seal a JSON value: maps become read-only, lists become tuples."""
    if isinstance(value, Mapping) and type(value) is not MappingProxyType:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    """Project a frozen value back to plain JSON for encoding and comparison."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _string_keys(value, name, level=0):
    if level > MAX_FACTS_DEPTH + 8:
        raise PrepareValueError(f'{name} is nested too deeply')
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise PrepareValueError(f'{name} must use string JSON keys')
            _string_keys(item, name, level + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _string_keys(item, name, level + 1)


def _sealed_map(value, name):
    if not isinstance(value, Mapping):
        raise PrepareValueError(f'{name} must be a JSON object')
    plain = _thaw(value)
    canonical_json(plain)
    _string_keys(plain, name)
    return _freeze(plain)


def _tuple_of(value, cls, name, limit=MAX_REFS):
    if type(value) is not tuple or len(value) > limit:
        raise PrepareValueError(f'{name} must be a tuple of at most {limit} items')
    for item in value:
        if type(item) is not cls:
            raise PrepareValueError(f'{name} contains a foreign value')
    return value


@dataclass(frozen=True)
class BoundPath:
    root_key: str
    relative_path: str

    def __post_init__(self):
        if type(self.root_key) is not str or not ROOT_KEY.match(self.root_key):
            raise PrepareValueError('root_key is not an approved directory key')
        _relative(self.relative_path)

    def projection(self):
        return {'schemaVersion': 'bound-path/1', 'rootKey': self.root_key,
                'relativePath': self.relative_path}


def _relative(value):
    if type(value) is not str or not value or len(value) > MAX_ID:
        raise PrepareValueError('relative_path must be a bounded nonempty string')
    if value == '.':
        return value
    if value.startswith('/') or '\\' in value:
        raise PrepareValueError('relative_path must be a canonical relative POSIX path')
    if any(ord(char) < 0x20 or ord(char) == 0x7f for char in value):
        raise PrepareValueError('relative_path must not contain control characters')
    parts = value.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise PrepareValueError('relative_path must not contain empty, dot or parent segments')
    return value


@dataclass(frozen=True)
class CredentialRef:
    issuer: str
    ref: str
    revision: str

    def __post_init__(self):
        _text(self.issuer, 'issuer')
        _text(self.ref, 'ref')
        _text(self.revision, 'revision')

    def projection(self):
        return {'schemaVersion': 'credential-ref/1', 'issuer': self.issuer,
                'ref': self.ref, 'revision': self.revision}


@dataclass(frozen=True)
class SecretBinding:
    target: str
    destination: str | BoundPath
    credential_ref: CredentialRef

    def __post_init__(self):
        if self.target not in ('env', 'file'):
            raise PrepareValueError('secret target must be env or file')
        if type(self.credential_ref) is not CredentialRef:
            raise PrepareValueError('secret binding needs a CredentialRef')
        if self.target == 'env':
            if type(self.destination) is not str or not ENV_NAME.match(self.destination):
                raise PrepareValueError('env secret destination must be a valid variable name')
        elif type(self.destination) is not BoundPath:
            raise PrepareValueError('file secret destination must be a BoundPath')

    def projection(self):
        destination = (self.destination if type(self.destination) is str
                       else self.destination.projection())
        return {'schemaVersion': 'secret-binding/1', 'target': self.target,
                'destination': destination, 'credentialRef': self.credential_ref.projection()}


@dataclass(frozen=True)
class PreparedConfigurationRef:
    issuer: str
    configuration_id: str
    revision: str
    digest: str
    media_type: str
    byte_length: int
    location: BoundPath

    def __post_init__(self):
        _text(self.issuer, 'issuer')
        _text(self.configuration_id, 'configuration_id')
        _text(self.revision, 'revision')
        _digest(self.digest)
        _text(self.media_type, 'media_type')
        _count(self.byte_length, 'byte_length')
        if type(self.location) is not BoundPath:
            raise PrepareValueError('prepared configuration needs a BoundPath location')

    def projection(self):
        return {'schemaVersion': 'prepared-configuration-ref/1', 'issuer': self.issuer,
                'configurationId': self.configuration_id, 'revision': self.revision,
                'digest': self.digest, 'mediaType': self.media_type,
                'byteLength': self.byte_length, 'location': self.location.projection()}


@dataclass(frozen=True)
class MaterialRef:
    issuer: str
    material_id: str
    revision: str
    digest: str
    media_type: str
    byte_length: int
    location: BoundPath | None = None

    def __post_init__(self):
        _text(self.issuer, 'issuer')
        _text(self.material_id, 'material_id')
        _text(self.revision, 'revision')
        _digest(self.digest)
        _text(self.media_type, 'media_type')
        _count(self.byte_length, 'byte_length')
        if self.location is not None and type(self.location) is not BoundPath:
            raise PrepareValueError('material location must be a BoundPath or None')

    def projection(self):
        return {'schemaVersion': 'agent-material-ref/1', 'issuer': self.issuer,
                'materialId': self.material_id, 'revision': self.revision,
                'digest': self.digest, 'mediaType': self.media_type,
                'byteLength': self.byte_length,
                'location': None if self.location is None else self.location.projection()}


@dataclass(frozen=True)
class ConfigurationArtifact:
    target: BoundPath
    media_type: str
    text_utf8: str
    digest: str = ''
    mode: int = 384

    def __post_init__(self):
        if type(self.target) is not BoundPath:
            raise PrepareValueError('artifact target must be a BoundPath')
        _text(self.media_type, 'media_type')
        if type(self.text_utf8) is not str:
            raise PrepareValueError('artifact text must be a string')
        try:
            raw = self.text_utf8.encode('utf-8')
        except UnicodeEncodeError:
            raise PrepareValueError('artifact text must be valid UTF-8') from None
        if len(raw) > MAX_INLINE_ARTIFACT:
            raise PrepareValueError('inline artifact exceeds 256KiB')
        expected = 'sha256:' + hashlib.sha256(raw).hexdigest()
        if self.digest and self.digest != expected:
            raise PrepareValueError('artifact digest does not match its text bytes')
        object.__setattr__(self, 'digest', expected)
        if type(self.mode) is not int or self.mode not in (384, 420):
            raise PrepareValueError('artifact mode must be 0o600 or 0o644')

    def projection(self):
        return {'schemaVersion': 'configuration-artifact/1', 'target': self.target.projection(),
                'mediaType': self.media_type, 'textUtf8': self.text_utf8,
                'digest': self.digest, 'mode': self.mode}


@dataclass(frozen=True)
class SessionBootstrap:
    mode: str
    location: str | None = None

    def __post_init__(self):
        if self.mode not in SESSION_MODES:
            raise PrepareValueError('session mode must be fresh, resume or none')
        if self.mode == 'none':
            if self.location is not None:
                raise PrepareValueError('mode none requires a null location')
        else:
            _text(self.location, 'session location')

    def projection(self):
        return {'schemaVersion': 'session-bootstrap/1', 'mode': self.mode,
                'location': self.location}


@dataclass(frozen=True)
class LaunchPlan:
    argv: tuple[str, ...]
    cwd_ref: BoundPath
    environment_values: Mapping[str, str]
    secret_bindings: tuple[SecretBinding, ...]
    configuration_artifacts: tuple[ConfigurationArtifact, ...]
    prepared_configuration_refs: tuple[PreparedConfigurationRef, ...]
    material_refs: tuple[MaterialRef, ...]
    session_bootstrap: SessionBootstrap
    required_capabilities: tuple[str, ...]
    plan_digest: str = ''

    def __post_init__(self):
        if type(self.argv) is not tuple or not 1 <= len(self.argv) <= MAX_ARGV:
            raise PrepareValueError('argv must hold 1..256 entries')
        for item in self.argv:
            _text(item, 'argv entry', MAX_ARGV_BYTES)
            if len(item.encode('utf-8')) > MAX_ARGV_BYTES:
                raise PrepareValueError('an argv entry exceeds 8192 UTF-8 bytes')
        if type(self.cwd_ref) is not BoundPath:
            raise PrepareValueError('cwd_ref must be a BoundPath')
        env = _sealed_map(dict(self.environment_values), 'environment_values')
        if len(env) > MAX_ENV:
            raise PrepareValueError('environment_values holds more than 128 entries')
        for key, value in env.items():
            if type(key) is not str or not ENV_NAME.match(key) or len(key) > MAX_ENV_KEY:
                raise PrepareValueError('environment key is invalid')
            if type(value) is not str or len(value.encode('utf-8')) > MAX_ENV_VALUE:
                raise PrepareValueError('environment value is too long')
        object.__setattr__(self, 'environment_values', _freeze(env))
        _tuple_of(self.secret_bindings, SecretBinding, 'secret_bindings')
        _tuple_of(self.configuration_artifacts, ConfigurationArtifact, 'configuration_artifacts')
        _tuple_of(self.prepared_configuration_refs, PreparedConfigurationRef,
                  'prepared_configuration_refs')
        _tuple_of(self.material_refs, MaterialRef, 'material_refs')
        if type(self.session_bootstrap) is not SessionBootstrap:
            raise PrepareValueError('session_bootstrap must be a SessionBootstrap')
        caps = self.required_capabilities
        if type(caps) is not tuple or len(set(caps)) != len(caps) or not set(caps) <= CAPABILITIES:
            raise PrepareValueError('required_capabilities must be unique endpoint member names')
        secrets = set()
        for binding in self.secret_bindings:
            destination = (binding.destination if type(binding.destination) is str
                           else binding.destination.projection())
            marker = canonical_json(destination)
            if marker in secrets:
                raise PrepareValueError('duplicate secret destination')
            secrets.add(marker)
            if binding.target == 'env' and binding.destination in env:
                raise PrepareValueError('secret env destination also appears in environment_values')
        total = sum(len(item.text_utf8.encode('utf-8')) for item in self.configuration_artifacts)
        if total > MAX_INLINE_TOTAL:
            raise PrepareValueError('inline artifacts exceed 1MiB in total')
        if len(canonical_json(self.projection(without_digest=True)).encode('utf-8')) > MAX_PLAN_BYTES:
            raise PrepareValueError('launch plan exceeds 2MiB')
        computed = canonical_digest(self.projection(without_digest=True))
        if self.plan_digest and self.plan_digest != computed:
            raise PrepareValueError('plan_digest does not match the plan')
        object.__setattr__(self, 'plan_digest', computed)

    @classmethod
    def decode(cls, value) -> 'LaunchPlan':
        if type(value) is not dict or set(value) != {
                'schemaVersion', 'argv', 'cwdRef', 'environmentValues', 'secretBindings',
                'configurationArtifacts', 'preparedConfigurationRefs', 'materialRefs',
                'sessionBootstrap', 'requiredCapabilities', 'planDigest'}:
            raise PrepareValueError('launch plan is not the closed projection')
        if value['schemaVersion'] != 'agent-launch-plan/1':
            raise PrepareValueError('launch plan schemaVersion is not agent-launch-plan/1')
        plan = cls(
            argv=tuple(value['argv']),
            cwd_ref=BoundPath(value['cwdRef']['rootKey'], value['cwdRef']['relativePath']),
            environment_values=value['environmentValues'],
            secret_bindings=tuple(
                SecretBinding(binding['target'],
                              binding['destination'] if type(binding['destination']) is str
                              else BoundPath(binding['destination']['rootKey'],
                                             binding['destination']['relativePath']),
                              CredentialRef(binding['credentialRef']['issuer'],
                                            binding['credentialRef']['ref'],
                                            binding['credentialRef']['revision']))
                for binding in value['secretBindings']),
            configuration_artifacts=tuple(
                ConfigurationArtifact(BoundPath(item['target']['rootKey'], item['target']['relativePath']),
                                      item['mediaType'], item['textUtf8'], item['digest'], item['mode'])
                for item in value['configurationArtifacts']),
            prepared_configuration_refs=tuple(_prepared_from(item) for item in value['preparedConfigurationRefs']),
            material_refs=tuple(_material_from(item) for item in value['materialRefs']),
            session_bootstrap=SessionBootstrap(value['sessionBootstrap']['mode'],
                                               value['sessionBootstrap']['location']),
            required_capabilities=tuple(value['requiredCapabilities']),
            plan_digest=value['planDigest'])
        if plan.projection() != value:
            raise PrepareValueError('launch plan does not re-encode to its own bytes')
        return plan

    def projection(self, *, without_digest: bool = False):
        value = {
            'schemaVersion': 'agent-launch-plan/1',
            'argv': list(self.argv),
            'cwdRef': self.cwd_ref.projection(),
            'environmentValues': _thaw(self.environment_values),
            'secretBindings': [item.projection() for item in self.secret_bindings],
            'configurationArtifacts': [item.projection() for item in self.configuration_artifacts],
            'preparedConfigurationRefs': [item.projection() for item in self.prepared_configuration_refs],
            'materialRefs': [item.projection() for item in self.material_refs],
            'sessionBootstrap': self.session_bootstrap.projection(),
            'requiredCapabilities': list(self.required_capabilities),
        }
        if not without_digest:
            value['planDigest'] = self.plan_digest
        return value


@dataclass(frozen=True)
class EndpointError:
    code: str
    diagnostic: str

    def __post_init__(self):
        _text(self.code, 'error code', MAX_ERROR_CODE)
        _text(self.diagnostic, 'error diagnostic', MAX_ERROR_DIAGNOSTIC)

    def projection(self):
        return {'code': self.code, 'diagnostic': self.diagnostic}


@dataclass(frozen=True)
class LaunchObservation:
    operation_ref: str
    status: str
    process_endpoint_ref: EndpointRef | None = None
    facts: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    error: EndpointError | None = None

    def __post_init__(self):
        _text(self.operation_ref, 'operation_ref')
        if self.status not in ('accepted', 'completed', 'refused', 'unknown'):
            raise PrepareValueError('observation status is not a frozen value')
        if self.process_endpoint_ref is not None and type(self.process_endpoint_ref) is not EndpointRef:
            raise PrepareValueError('process_endpoint_ref must be an EndpointRef or None')
        facts = _sealed_map(self.facts, 'facts')
        if len(facts) > MAX_FACTS_KEYS:
            raise PrepareValueError('facts hold more than 64 keys')
        if len(canonical_json(facts).encode('utf-8')) > MAX_FACTS_BYTES:
            raise PrepareValueError('facts exceed 64KiB')
        if _depth(facts) > MAX_FACTS_DEPTH:
            raise PrepareValueError('facts exceed depth 8')
        object.__setattr__(self, 'facts', facts)
        if type(self.evidence_refs) is not tuple or len(self.evidence_refs) > MAX_REFS:
            raise PrepareValueError('evidence_refs must be a bounded tuple')
        for ref in self.evidence_refs:
            _text(ref, 'evidence ref')
        if self.error is not None and type(self.error) is not EndpointError:
            raise PrepareValueError('error must be an EndpointError or None')
        # The shared observation value carries the common rule only. Which
        # actions need a process endpoint is action-specific (see
        # `validate_launch_observation`): a detach or a stop reports completed
        # without one, and a refusal may name the endpoint it refused to use.
        if self.status in ('accepted', 'completed'):
            if self.error is not None:
                raise PrepareValueError('accepted/completed observations carry no error')
        elif self.error is None:
            raise PrepareValueError('refused/unknown observations must be explained by an EndpointError')

    def projection(self):
        return {'schemaVersion': 'endpoint-operation/1', 'operationRef': self.operation_ref,
                'status': self.status,
                'processEndpointRef': (None if self.process_endpoint_ref is None
                                       else self.process_endpoint_ref.projection()),
                'facts': _thaw(self.facts), 'evidenceRefs': list(self.evidence_refs),
                'error': None if self.error is None else self.error.projection()}

    @classmethod
    def decode(cls, value) -> 'LaunchObservation':
        if type(value) is not dict or set(value) != {
                'schemaVersion', 'operationRef', 'status', 'processEndpointRef',
                'facts', 'evidenceRefs', 'error'}:
            raise PrepareValueError('observation is not the closed projection')
        if value['schemaVersion'] != 'endpoint-operation/1':
            raise PrepareValueError('observation schemaVersion is not endpoint-operation/1')
        endpoint = value['processEndpointRef']
        error = value['error']
        return cls(
            operation_ref=value['operationRef'], status=value['status'],
            process_endpoint_ref=None if endpoint is None else EndpointRef.decode(endpoint),
            facts=value['facts'],
            evidence_refs=tuple(value['evidenceRefs']),
            error=None if error is None else EndpointError(error['code'], error['diagnostic']))


def validate_launch_observation(observation) -> 'LaunchObservation':
    """Launch-specific rule: a completed launch names the process it created.

    Accepting an observation, refusing one or completing an operational receipt
    (stop/detach) does not require a process endpoint; only a *completed launch*
    does, and that check belongs to the launch action, not to the shared DTO.
    """
    if type(observation) is not LaunchObservation:
        raise PrepareValueError('launch observation is not a LaunchObservation')
    if observation.status == 'completed' and observation.process_endpoint_ref is None:
        raise PrepareValueError('a completed launch must name its process endpoint')
    return observation


def validate_lifecycle_observation(action, observation) -> 'LaunchObservation':
    """Action-specific receipt rules for stop/detach; frozen DTO unchanged.

    A terminate receipt means requested/attempted, never proven exit; only a
    separately granted original observe can yield "stopped". Detach closes only
    its granted association: it must report the association detached and must
    not claim exit or a Use release.
    """
    if action not in ('stop', 'detach'):
        raise PrepareValueError('lifecycle action invalid')
    if type(observation) is not LaunchObservation:
        raise PrepareValueError('lifecycle observation is not a LaunchObservation')
    if observation.status not in ('accepted', 'completed', 'refused', 'unknown'):
        raise PrepareValueError('lifecycle observation status invalid')
    facts=observation.facts or {}
    if action=='stop':
        if facts.get('exitClaimed') is True or facts.get('processExited') is True:
            raise PrepareValueError('a terminate receipt cannot claim process exit')
        if observation.status=='completed' and (facts.get('action')!='terminate'
                or facts.get('cancellation') not in ('requested','unsupported','unknown')
                or facts.get('processState') not in ('running','exited','unknown')):
            raise PrepareValueError('completed terminate facts required')
        return observation
    if facts.get('exitClaimed') is True or facts.get('released') is True:
        raise PrepareValueError('detach cannot claim exit or resource release')
    if observation.status=='completed' and (facts.get('action')!='detach'
            or facts.get('associationDetached') is not True or facts.get('exitClaimed') is not False):
        raise PrepareValueError('completed detach facts required')
    return observation


def _prepared_from(value):
    return PreparedConfigurationRef(value['issuer'], value['configurationId'], value['revision'],
                                    value['digest'], value['mediaType'], value['byteLength'],
                                    BoundPath(value['location']['rootKey'],
                                              value['location']['relativePath']))


def _material_from(value):
    location = value['location']
    return MaterialRef(value['issuer'], value['materialId'], value['revision'], value['digest'],
                       value['mediaType'], value['byteLength'],
                       None if location is None else BoundPath(location['rootKey'],
                                                               location['relativePath']))


def _depth(value, level=0):
    if isinstance(value, Mapping):
        return max([level] + [_depth(item, level + 1) for item in value.values()])
    if isinstance(value, (list, tuple)):
        return max([level] + [_depth(item, level + 1) for item in value])
    return level


__all__ = ['CAPABILITIES', 'SESSION_MODES', 'PrepareValueError', 'canonical_digest',
           'validate_launch_observation',
           'canonical_json', 'BoundPath', 'CredentialRef', 'SecretBinding',
           'PreparedConfigurationRef', 'MaterialRef', 'ConfigurationArtifact',
           'SessionBootstrap', 'LaunchPlan', 'EndpointError', 'LaunchObservation']
