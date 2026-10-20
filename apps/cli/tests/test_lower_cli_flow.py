"""End-to-end source CLI: environments, decisions and Profile/harness surface."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from ordessa_agent_tools.cli import main


def run_cli(argv, stdin=b''):
    out, err = io.StringIO(), io.StringIO()
    import sys
    previous = sys.stdin
    sys.stdin = io.TextIOWrapper(io.BytesIO(stdin), encoding='utf-8')
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = main([str(item) for item in argv])
    finally:
        sys.stdin = previous
    return code, out.getvalue(), err.getvalue()


def admitted_harness_state(state):
    """Admit every installed harness provider explicitly, then return the state.

    No provider is loaded without an allowlist entry, so a test that wants a
    real catalog must write the admission itself — the same thing an operator
    does in ``<state>/harness.json``.
    """
    from importlib.metadata import entry_points
    installed = sorted(point.name for point in entry_points(group='ordessa.harness_providers'))
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    (state / 'harness.json').write_text(json.dumps({'allowlist': installed}))
    return installed


def envelope(output):
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) == 1, output
    return json.loads(lines[0])


def test_help_opens_no_state(tmp_path):
    state = tmp_path / 'never-created'
    code, output, error = run_cli(['--state', state, '--help'])
    assert code == 0 and 'environments' in output and error == ''
    assert not state.exists()


def test_environments_one_shot_exec_and_files(tmp_path):
    state = tmp_path / 'state'
    code, output, _ = run_cli(['--state', state, 'environments', 'create', 'local',
                               '--root', str(state / 'work'), '--alias', 'demo',
                               '--request-id', 'env-1', '--json'])
    assert code == 0 and envelope(output)['status'] == 'completed'

    code, output, error = run_cli(['--state', state, 'environments', 'exec', 'demo',
                                   '--request-id', 'exec-1', '--', '/usr/bin/printf',
                                   'hello-'])
    assert code == 0 and output == 'hello-' and error == ''

    code, _, _ = run_cli(['--state', state, 'environments', 'files', 'demo', 'write',
                          'kept.txt', 'kept', '--json'])
    assert code == 0
    code, output, _ = run_cli(['--state', state, 'environments', 'files', 'demo',
                               'cat', 'kept.txt', '--json'])
    assert code == 0 and envelope(output)['data']['content'] == 'kept'

    code, output, _ = run_cli(['--state', state, 'environments', 'list', '--json'])
    assert code == 0 and envelope(output)['data']['resources'][0]['activeUses'] == 0


def test_decisions_validate_run_query_evidence(tmp_path):
    state = tmp_path / 'state'
    job = tmp_path / 'job.json'
    job.write_text(json.dumps({
        'spec_version': 'decision-job/1', 'job_id': 'cli-job', 'version': 1,
        'input': {'score': 7},
        'limits': {'max_model_calls': 0, 'max_steps': 4,
                   'max_value_bytes': 4096, 'timeout_seconds': 5.0},
        'steps': [{'id': 'gate', 'type': 'rules', 'engine': None,
                   'when': {'fact': 'input.score', 'op': 'gte', 'value': 1},
                   'payload': {'checks': [{'id': 'high', 'when': 'input.score >= 5'}],
                               'default': {'answer': 'accept'}}}],
        'result': {'from': 'gate', 'path': ['values', 'default']}}))
    code, output, _ = run_cli(['--state', state, 'decisions', 'validate', '--job', job, '--json'])
    assert code == 0 and envelope(output)['data']['job_id'] == 'cli-job'

    result_file = tmp_path / 'decision.json'
    code, output, _ = run_cli(['--state', state, 'decisions', 'run', '--job', job,
                               '--request-id', 'decision-1', '--save-result', result_file,
                               '--json'])
    run = envelope(output)
    assert code == 0 and run['status'] == 'completed'
    assert run['data']['result'] == {'answer': 'accept'}
    assert json.loads(result_file.read_text()) == run

    code, output, _ = run_cli(['--state', state, 'decisions', 'query',
                               '--original-request-id', 'decision-1', '--job', job, '--json'])
    queried = envelope(output)
    assert code == 0 and queried['data'] == run['data']
    assert queried['operationRef'] == run['operationRef']

    digest = run['evidenceRefs'][0].split(':', 1)[1]
    code, output, _ = run_cli(['--state', state, 'decisions', 'get',
                               '--digest', digest, '--json'])
    assert code == 0 and envelope(output)['data']['summary']['job_digest']

    code, output, _ = run_cli(['--state', state, 'decisions', 'query',
                               '--original-request-id', 'missing', '--job', job, '--json'])
    assert code == 2 and envelope(output)['error']['code'] == 'INVALID_INPUT'


def test_profile_and_harness_surface(tmp_path):
    state = tmp_path / 'state'
    installed = admitted_harness_state(state)
    if not installed:
        pytest.skip('no harness provider is installed in this environment')
    code, output, _ = run_cli(['--state', state, 'agents', 'harness', 'list', '--json'])
    harnesses = envelope(output)['data']['harnesses']
    assert [item['definitionRef']['definitionId'] for item in harnesses] == installed
    pin = harnesses[0]['definitionRef']
    manifest = tmp_path / 'profile.json'
    manifest.write_text(json.dumps({'schemaVersion': '1', 'harnessDefinitionRef': pin,
                                    'declarations': []}))
    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'create',
                               'demo-profile', '--name', 'Demo', '--manifest', manifest,
                               '--request-id', 'profile-1', '--json'])
    profile = envelope(output)
    assert code == 0 and profile['data']['profileId'] == 'demo-profile'
    revision = profile['data']['currentManifestRef']

    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'list', '--json'])
    assert [entry['profileId'] for entry in envelope(output)['data']['entries']] == ['demo-profile']
    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'readEntry',
                               'demo-profile', '--json'])
    assert envelope(output)['data']['displayName'] == 'Demo'

    # A missing revision is refused; no hidden fallback to another Profile.
    bad = dict(revision)
    bad['manifestRevision'] = 99
    revision_file = tmp_path / 'bad-ref.json'
    revision_file.write_text(json.dumps(bad))
    code, output, _ = run_cli(['--state', state, 'call', 'profiles.read', '--input', '-',
                               '--json'], stdin=json.dumps({'profileRef': bad}).encode())
    assert code == 2 and envelope(output)['status'] == 'refused'


def test_harness_allowlist_admits_nothing_and_never_loads_unauthorized_points(tmp_path, monkeypatch):
    """A planted, side-effecting entry point outside the allowlist is never loaded."""
    state = tmp_path / 'state'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    (state / 'harness.json').write_text(json.dumps({'allowlist': []}))
    loaded = []

    class Planted:
        name = 'planted-harness'
        dist = None

        def load(self):
            loaded.append(self.name)
            raise AssertionError('an unadmitted entry point must never be loaded')

    import importlib.metadata as metadata
    real = metadata.entry_points

    def entry_points(*, group=None, **kwargs):
        if group == 'ordessa.harness_providers':
            return [Planted()]
        return real(group=group, **kwargs)

    monkeypatch.setattr(metadata, 'entry_points', entry_points)
    code, output, _ = run_cli(['--state', state, 'agents', 'harness', 'list', '--json'])
    value = envelope(output)
    assert code == 4 and value['status'] == 'refused'
    assert value['error']['code'] == 'CAPABILITY_UNSUPPORTED'
    assert value['data']['harnesses'] == []
    assert value['data']['notAdmitted'] == [
        {'definitionId': 'planted-harness', 'reason': 'not admitted by the harness allowlist'}]
    assert loaded == [], 'unadmitted entry point was imported'


def test_harness_allowlist_entry_for_an_uninstalled_provider_is_reported(tmp_path):
    state = tmp_path / 'state'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    (state / 'harness.json').write_text(json.dumps({'allowlist': ['not-installed-brand']}))
    code, output, _ = run_cli(['--state', state, 'agents', 'harness', 'list', '--json'])
    value = envelope(output)
    assert code == 4
    reported = {item['definitionId']: item['reason'] for item in value['data']['notAdmitted']}
    assert reported['not-installed-brand'] == 'allowlisted provider is not installed'


def test_profile_and_harness_commands_do_not_open_the_environment_owner(tmp_path):
    """A Profile read must not build the Environment store it does not address."""
    state = tmp_path / 'state'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'list', '--json'])
    assert code == 0 and envelope(output)['data']['entries'] == []
    assert not (state / 'environments.sqlite').exists(), 'Profile read opened the Environment store'
    code, output, _ = run_cli(['--state', state, 'agents', 'harness', 'list', '--json'])
    assert code == 4  # nothing admitted yet
    assert not (state / 'environments.sqlite').exists(), 'harness list opened the Environment store'


def test_unknown_command_and_invalid_input_are_deterministic(tmp_path):
    state = tmp_path / 'state'
    code, output, _ = run_cli(['--state', state, 'unknown', 'thing', '--json'])
    assert code == 4 and envelope(output)['error']['code'] == 'CAPABILITY_UNSUPPORTED'
    code, output, _ = run_cli(['--state', state, 'environments', 'create', 'local', '--json'])
    assert code == 2 and envelope(output)['error']['code'] == 'INVALID_INPUT'
    code, _, error = run_cli(['environments', 'list', '--json'])
    assert code == 2 and '--state' in error


def test_ask_without_a_provider_is_an_explicit_refusal(tmp_path):
    state = tmp_path / 'state'
    job = tmp_path / 'ask.json'
    job.write_text(json.dumps({
        'spec_version': 'decision-job/1', 'job_id': 'cli-ask', 'version': 1,
        'input': {'score': 7},
        'limits': {'max_model_calls': 1, 'max_steps': 2,
                   'max_value_bytes': 4096, 'timeout_seconds': 5.0},
        'steps': [{'id': 'ask', 'type': 'ask', 'engine': None,
                   'when': {'fact': 'input.score', 'op': 'gte', 'value': 1},
                   'payload': {'question': {'kind': 'choice', 'text': 'Proceed?',
                                            'options': {'yes': 'Yes', 'no': 'No'}}}}],
        'result': {'from': 'ask', 'path': ['answer']}}))
    code, output, _ = run_cli(['--state', state, 'decisions', 'validate', '--job', job, '--json'])
    assert code == 0
    code, output, _ = run_cli(['--state', state, 'decisions', 'run', '--job', job,
                               '--request-id', 'ask-1', '--json'])
    assert code == 4
    value = envelope(output)
    assert value['status'] == 'refused' and value['error']['code'] == 'PROVIDER_UNAVAILABLE'


def test_full_profile_lifecycle_edit_clone_rename_archive_restore_cas(tmp_path):
    state = tmp_path / 'state'
    first = tmp_path / 'first.json'
    second = tmp_path / 'second.json'
    installed = admitted_harness_state(state)
    if not installed:
        pytest.skip('no harness provider is installed in this environment')
    code, output, _ = run_cli(['--state', state, 'agents', 'harness', 'list', '--json'])
    harnesses = envelope(output)['data']['harnesses']
    pin = harnesses[0]['definitionRef']
    first.write_text(json.dumps({'schemaVersion': '1', 'harnessDefinitionRef': pin,
                                 'declarations': []}))
    second.write_text(json.dumps({'schemaVersion': '1', 'harnessDefinitionRef': pin,
                                  'declarations': [],
                                  'metadata': {'note': 'second-revision'}}))
    profile_file = tmp_path / 'profile.json'
    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'create',
                               'p1', '--name', 'P1', '--manifest', first,
                               '--request-id', 'create-1', '--save-result', profile_file,
                               '--json'])
    created = envelope(output)
    assert code == 0 and created['data']['catalogRevision'] == 1
    revision1 = created['data']['currentManifestRef']

    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'read',
                               str(profile_file) + '#/data/currentManifestRef', '--json'])
    assert code == 0 and envelope(output)['data']['ref'] == revision1

    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'edit', 'p1',
                               '--manifest', second, '--expected-catalog-revision', '1',
                               '--base-manifest-ref',
                               str(profile_file) + '#/data/currentManifestRef',
                               '--request-id', 'edit-1', '--json'])
    edited = envelope(output)
    assert code == 0 and edited['data']['catalogRevision'] == 2
    revision2 = edited['data']['currentManifestRef']
    assert revision2['manifestRevision'] == 2 and revision2 != revision1
    revision2_file = tmp_path / 'revision2.json'
    revision2_file.write_text(json.dumps(revision2))

    # Stale CAS is refused and does not change the current revision.
    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'edit', 'p1',
                               '--manifest', second, '--expected-catalog-revision', '1',
                               '--base-manifest-ref',
                               str(profile_file) + '#/data/currentManifestRef',
                               '--request-id', 'edit-stale', '--json'])
    assert code == 5 and envelope(output)['error']['code'] == 'CONFLICT'
    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'readEntry',
                               'p1', '--json'])
    assert envelope(output)['data']['catalogRevision'] == 2

    # Same request id and input replays the original result without a new revision.
    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'edit', 'p1',
                               '--manifest', second, '--expected-catalog-revision', '1',
                               '--base-manifest-ref',
                               str(profile_file) + '#/data/currentManifestRef',
                               '--request-id', 'edit-1', '--json'])
    assert code == 0 and envelope(output)['data'] == edited['data']
    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'readEntry',
                               'p1', '--json'])
    assert envelope(output)['data']['catalogRevision'] == 2

    # Clone to a second Profile.
    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'clone',
                               '--profile-ref', revision2_file, '--profile-id', 'p2',
                               '--name', 'P2', '--request-id', 'clone-1', '--json'])
    cloned = envelope(output)
    assert code == 0 and cloned['data']['profileId'] == 'p2'
    assert cloned['data']['catalogRevision'] == 1

    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'rename', 'p2',
                               '--name', 'P2-renamed', '--expected-catalog-revision', '1',
                               '--request-id', 'rename-1', '--json'])
    renamed = envelope(output)
    assert code == 0 and renamed['data']['displayName'] == 'P2-renamed'
    assert renamed['data']['catalogRevision'] == 2

    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'archive', 'p2',
                               '--expected-catalog-revision', '2',
                               '--request-id', 'archive-1', '--json'])
    archived = envelope(output)
    assert code == 0 and archived['data']['archivedAt']
    assert archived['data']['catalogRevision'] == 3

    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'list', '--json'])
    assert [entry['profileId'] for entry in envelope(output)['data']['entries']] == ['p1']
    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'list',
                               '--include-archived', '--json'])
    assert sorted(entry['profileId'] for entry in envelope(output)['data']['entries']) == ['p1', 'p2']

    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'restore', 'p2',
                               '--expected-catalog-revision', '3',
                               '--request-id', 'restore-1', '--json'])
    restored = envelope(output)
    assert code == 0 and restored['data']['archivedAt'] is None
    assert restored['data']['catalogRevision'] == 4

    code, output, _ = run_cli(['--state', state, 'agents', 'profiles', 'preview',
                               revision2_file, '--json'])
    preview = envelope(output)
    assert code == 4 and preview['status'] == 'refused'
    assert preview['error']['code'] == 'CAPABILITY_UNSUPPORTED'
    assert preview['data']['ready'] is False and preview['data']['status'] == 'unresolved'
