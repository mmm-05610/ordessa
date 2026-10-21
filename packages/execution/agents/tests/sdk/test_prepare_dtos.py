"""F1.1 launch/artifact DTOs: closed projections, digests and refusals.

No `ordessa_units` and no `pacthold` import: these values are the Agent/Profile
distribution's own SDK surface.
"""
import hashlib

import pytest

from ordessa_agents.sdk.prepare import (
    BoundPath, ConfigurationArtifact, CredentialRef, EndpointError, LaunchObservation,
    LaunchPlan, MaterialRef, PreparedConfigurationRef, PrepareValueError, SecretBinding,
    SessionBootstrap, canonical_digest, canonical_json, validate_launch_observation,
)
from ordessa_agents.sdk.instances import EndpointRef


def _path(relative='config/app.json'):
    return BoundPath(root_key='workdir', relative_path=relative)


def _plan(**overrides):
    values = dict(
        argv=('/usr/bin/env', 'python', '-V'),
        cwd_ref=_path('.'),
        environment_values={'LANG': 'C.UTF-8'},
        secret_bindings=(),
        configuration_artifacts=(),
        prepared_configuration_refs=(),
        material_refs=(),
        session_bootstrap=SessionBootstrap(mode='none'),
        required_capabilities=('launcher',),
    )
    values.update(overrides)
    return LaunchPlan(**values)


def test_bound_path_accepts_canonical_relative_paths_only():
    assert _path().relative_path == 'config/app.json'
    assert _path('.').relative_path == '.'
    for bad in ('/abs/path', '../escape', 'a//b', 'a/./b', 'a\\b', ''):
        with pytest.raises(PrepareValueError):
            _path(bad)
    for bad_root in ('Work', '_work', 'work dir', 'a' * 65):
        with pytest.raises(PrepareValueError):
            BoundPath(root_key=bad_root, relative_path='.')


def test_secret_binding_destinations_are_typed_and_unique():
    secret = SecretBinding(target='env', destination='API_TOKEN',
                           credential_ref=CredentialRef('issuer-1', 'ref-1', 'rev-1'))
    assert secret.projection()['destination'] == 'API_TOKEN'
    file_secret = SecretBinding(target='file', destination=_path('token'),
                                credential_ref=CredentialRef('issuer-1', 'ref-1', 'rev-1'))
    assert file_secret.projection()['destination']['schemaVersion'] == 'bound-path/1'
    with pytest.raises(PrepareValueError):
        SecretBinding(target='socket', destination='X',
                      credential_ref=CredentialRef('i', 'r', '1'))
    with pytest.raises(PrepareValueError):
        SecretBinding(target='env', destination='not a name',
                      credential_ref=CredentialRef('i', 'r', '1'))
    with pytest.raises(PrepareValueError):
        SecretBinding(target='file', destination='plain-path',
                      credential_ref=CredentialRef('i', 'r', '1'))
    # A secret env slot may not also appear as a plaintext environment value.
    with pytest.raises(PrepareValueError, match='secret env destination'):
        _plan(environment_values={'API_TOKEN': 'plaintext'},
              secret_bindings=(secret,))
    with pytest.raises(PrepareValueError, match='duplicate secret'):
        _plan(secret_bindings=(secret, secret))


def test_artifact_digest_is_derived_from_its_own_utf8_bytes():
    artifact = ConfigurationArtifact(target=_path('agent.toml'), media_type='application/toml',
                                     text_utf8='[agent]\nname = "x"\n')
    expected = 'sha256:' + hashlib.sha256(artifact.text_utf8.encode('utf-8')).hexdigest()
    assert artifact.digest == expected
    assert artifact.mode == 384
    with pytest.raises(PrepareValueError, match='does not match'):
        ConfigurationArtifact(target=_path('a'), media_type='text/plain', text_utf8='x',
                              digest='sha256:' + 'a' * 64)
    with pytest.raises(PrepareValueError):
        ConfigurationArtifact(target=_path('a'), media_type='text/plain', text_utf8='x', mode=0o777)


def test_session_bootstrap_modes_keep_their_existing_rules():
    assert SessionBootstrap('none').location is None
    for mode in ('fresh', 'resume'):
        with pytest.raises(PrepareValueError):
            SessionBootstrap(mode)
        assert SessionBootstrap(mode, 'opaque-location').location == 'opaque-location'
    with pytest.raises(PrepareValueError):
        SessionBootstrap('none', 'unexpected')
    with pytest.raises(PrepareValueError):
        SessionBootstrap('invented', 'x')


def test_launch_plan_digest_covers_every_field_and_rejects_tampering():
    plan = _plan()
    assert plan.plan_digest == canonical_digest(plan.projection(without_digest=True))
    assert plan.projection()['planDigest'] == plan.plan_digest
    # Everything order sensitive or identity bearing changes the digest.
    other = _plan(argv=('/usr/bin/env', 'python', '-V', '-E'))
    assert other.plan_digest != plan.plan_digest
    assert _plan(session_bootstrap=SessionBootstrap('fresh', 'bootstrap-1')).plan_digest != plan.plan_digest
    assert _plan(cwd_ref=_path('sub')).plan_digest != plan.plan_digest
    # A supplied digest that does not match is refused, not silently repaired.
    with pytest.raises(PrepareValueError, match='does not match the plan'):
        LaunchPlan(**{**plan.__dict__, 'plan_digest': 'sha256:' + 'b' * 64})


def test_required_capabilities_are_only_the_six_member_names():
    assert _plan(required_capabilities=('launcher', 'observe')).required_capabilities == ('launcher', 'observe')
    for bad in (('launcher', 'launcher'), ('launcher', 'environment'), ('write',), ()):
        if bad == ():
            assert _plan(required_capabilities=()).required_capabilities == ()
            continue
        with pytest.raises(PrepareValueError):
            _plan(required_capabilities=bad)


def test_launch_plan_enforces_bounded_argv_env_and_inline_artifacts():
    with pytest.raises(PrepareValueError):
        _plan(argv=())
    with pytest.raises(PrepareValueError):
        _plan(argv=tuple('a' for _ in range(257)))
    with pytest.raises(PrepareValueError):
        _plan(argv=('x' * 8193,))
    with pytest.raises(PrepareValueError):
        _plan(environment_values={f'K{i}': 'v' for i in range(129)})
    with pytest.raises(PrepareValueError):
        _plan(environment_values={'LANG': 'v' * 8193})
    with pytest.raises(PrepareValueError):
        _plan(environment_values={'bad-key': 'v'})
    big = ConfigurationArtifact(target=_path('big'), media_type='text/plain',
                                text_utf8='x' * (256 * 1024))
    assert _plan(configuration_artifacts=(big,)).configuration_artifacts == (big,)
    with pytest.raises(PrepareValueError, match='256KiB'):
        ConfigurationArtifact(target=_path('big'), media_type='text/plain',
                              text_utf8='x' * (256 * 1024 + 1))


def test_material_and_prepared_refs_keep_immutable_issuer_proof():
    material = MaterialRef('issuer-1', 'material-1', 'rev-1', 'sha256:' + 'c' * 64,
                           'text/plain', 12, _path('m.txt'))
    prepared = PreparedConfigurationRef('issuer-1', 'config-1', 'rev-1', 'sha256:' + 'd' * 64,
                                        'application/toml', 34, _path('c.toml'))
    plan = _plan(material_refs=(material,), prepared_configuration_refs=(prepared,))
    assert plan.projection()['materialRefs'][0]['schemaVersion'] == 'agent-material-ref/1'
    assert plan.projection()['preparedConfigurationRefs'][0]['schemaVersion'] == 'prepared-configuration-ref/1'
    with pytest.raises(PrepareValueError):
        MaterialRef('issuer-1', 'material-1', 'rev-1', 'not-a-digest', 'text/plain', 1)
    with pytest.raises(PrepareValueError):
        PreparedConfigurationRef('issuer-1', 'config-1', 'rev-1', 'sha256:' + 'd' * 64,
                                 'application/toml', -1, _path('c.toml'))
    with pytest.raises(PrepareValueError):
        _plan(prepared_configuration_refs=tuple(prepared for _ in range(129)))


def test_launch_observation_refuses_unknown_status_and_unexplained_refusal():
    endpoint = EndpointRef('issuer-1', 'endpoint-1', 'rev-1', 'sha256:' + 'e' * 64)
    observation = LaunchObservation(operation_ref='op-1', status='accepted',
                                    process_endpoint_ref=endpoint)
    assert observation.projection()['schemaVersion'] == 'endpoint-operation/1'
    assert LaunchObservation(operation_ref='op-1', status='refused',
                             error=EndpointError('LAUNCH_REFUSED', 'endpoint refused before spawn')) \
        .error.code == 'LAUNCH_REFUSED'
    with pytest.raises(PrepareValueError, match='must be explained by an EndpointError'):
        LaunchObservation(operation_ref='op-1', status='refused')
    with pytest.raises(PrepareValueError):
        LaunchObservation(operation_ref='op-1', status='maybe')
    with pytest.raises(PrepareValueError):
        LaunchObservation(operation_ref='op-1', status='accepted',
                          process_endpoint_ref=endpoint, facts={f'k{i}': i for i in range(65)})
    with pytest.raises(PrepareValueError):
        LaunchObservation(operation_ref='op-1', status='accepted',
                          process_endpoint_ref=endpoint,
                          facts={'a': {'b': {'c': {'d': {'e': {'f': {'g': {'h': {'i': {'j': {'k': {'l': 1}}}}}}}}}}}})


def test_values_are_deeply_immutable_after_digesting():
    from types import MappingProxyType
    plan = _plan(environment_values={'LANG': 'C.UTF-8'})
    assert isinstance(plan.environment_values, MappingProxyType)
    with pytest.raises(TypeError):
        plan.environment_values['INJECTED'] = 'x'
    obs = LaunchObservation(operation_ref='op-1', status='accepted',
                            process_endpoint_ref=EndpointRef('issuer-1', 'endpoint-1', 'rev-1',
                                                             'sha256:' + 'e' * 64),
                            facts={'a': {'b': 1}})
    assert isinstance(obs.facts, MappingProxyType)
    with pytest.raises(TypeError):
        obs.facts['a']['b'] = 2
    with pytest.raises(TypeError):
        obs.facts['new'] = 1
    # The digest still describes the value: freezing changed no serialized field.
    assert plan.plan_digest == canonical_digest(plan.projection(without_digest=True))


def test_observation_status_matrix_and_typed_endpoint():
    endpoint = EndpointRef('issuer-1', 'endpoint-1', 'rev-1', 'sha256:' + 'e' * 64)
    # The shared value carries the common rule only: accepted/completed never
    # carry an error, and the endpoint is optional here (stop/detach report
    # completed without one).
    for status in ('accepted', 'completed'):
        assert LaunchObservation('op-1', status, process_endpoint_ref=endpoint).status == status
        assert LaunchObservation('op-1', status).status == status
        with pytest.raises(PrepareValueError):
            LaunchObservation('op-1', status, endpoint, error=EndpointError('E', 'x'))
    # A refusal is explained, and it may name the endpoint it refused to use.
    assert LaunchObservation('op-1', 'refused', endpoint, error=EndpointError('E', 'x')).status == 'refused'
    with pytest.raises(PrepareValueError):
        LaunchObservation('op-1', 'refused')
    # Only a completed *launch* must name its process endpoint.
    validate_launch_observation(LaunchObservation('op-1', 'completed', endpoint))
    with pytest.raises(PrepareValueError, match='completed launch'):
        validate_launch_observation(LaunchObservation('op-1', 'completed'))
    validate_launch_observation(LaunchObservation('op-1', 'accepted'))
    validate_launch_observation(LaunchObservation('op-1', 'refused',
                                                  error=EndpointError('E', 'x')))
    # unknown must be explained.
    with pytest.raises(PrepareValueError):
        LaunchObservation('op-1', 'unknown')
    assert LaunchObservation('op-1', 'unknown', error=EndpointError('E', 'x')).error.code == 'E'
    # An untyped mapping is not an endpoint reference.
    with pytest.raises(PrepareValueError):
        LaunchObservation('op-1', 'accepted', process_endpoint_ref={'anything': True})
    # Round trip through the closed projection.
    value = LaunchObservation('op-1', 'completed', endpoint, {'k': 'v'}, ('evidence-1',)).projection()
    assert LaunchObservation.decode(value) == LaunchObservation('op-1', 'completed', endpoint, {'k': 'v'},
                                                               ('evidence-1',))


def test_integer_excluding_bool_and_float_is_enforced():
    with pytest.raises(PrepareValueError):
        ConfigurationArtifact(target=_path('a'), media_type='text/plain', text_utf8='x', mode=384.0)
    with pytest.raises(PrepareValueError):
        ConfigurationArtifact(target=_path('a'), media_type='text/plain', text_utf8='x', mode=True)
    with pytest.raises(PrepareValueError):
        MaterialRef('issuer-1', 'm', 'rev-1', 'sha256:' + 'c' * 64, 'text/plain', True)


def test_facts_require_string_json_keys():
    with pytest.raises(PrepareValueError, match='string JSON keys'):
        LaunchObservation('op-1', 'accepted', EndpointRef('i', 'e', 'r', 'sha256:' + 'e' * 64),
                          facts={1: 'x'})
    with pytest.raises(PrepareValueError, match='string JSON keys'):
        LaunchObservation('op-1', 'accepted', EndpointRef('i', 'e', 'r', 'sha256:' + 'e' * 64),
                          facts={'a': {2: 'x'}})


def test_utf8_byte_limits_not_character_limits():
    with pytest.raises(PrepareValueError, match='8192 UTF-8 bytes'):
        _plan(argv=('\u00e9' * 5000,))          # 10000 bytes, 5000 characters
    assert _plan(argv=('\u00e9' * 4096,)).argv[0] == '\u00e9' * 4096   # exactly 8192 bytes


def test_paths_and_ids_reject_control_characters():
    for bad in ('a\nb', 'a\tb', 'a\x7fb'):
        with pytest.raises(PrepareValueError):
            BoundPath('workdir', bad)
        with pytest.raises(PrepareValueError):
            LaunchObservation('op\x01', 'accepted', EndpointRef('i', 'e', 'r', 'sha256:' + 'e' * 64))


def test_decode_recomputes_the_digest_and_refuses_a_mismatch():
    plan = _plan()
    value = plan.projection()
    assert LaunchPlan.decode(value).plan_digest == plan.plan_digest
    tampered = {**value, 'planDigest': 'sha256:' + 'b' * 64}
    with pytest.raises(PrepareValueError, match='does not match the plan'):
        LaunchPlan.decode(tampered)
    with pytest.raises(PrepareValueError):
        LaunchPlan.decode({k: v for k, v in value.items() if k != 'planDigest'})
    with pytest.raises(PrepareValueError):
        LaunchPlan.decode({**value, 'extra': 1})
