"""The demo preview renders the original page from synthetic in-memory data only.

Environment-specific to this machine: it runs
``tooling/checks/server_product/local_library_demo_preview.py`` with the recovered
check runtime against the unmodified demo project. Run it explicitly:

    .venv-nightly/bin/python -m pytest \
        tooling/checks/server_product/test_local_library_demo_preview.py -q

It is not collected by the default suites. Missing runtime/project is a real
failure with a remedy, never a skip. Nothing here starts a preview server, writes
the demo tree, reads its database or simulates the pending search change.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import pytest

REPO = Path(__file__).resolve().parents[3]
PREVIEW = REPO / 'tooling/checks/server_product/local_library_demo_preview.py'
RUNTIME_PYTHON = REPO / '.nightly-cache/local-library-runtime-20261017/bin/python'
DEMO = Path('/home/maoqh/projects/ordessa-demo-local-library')
BUSINESS_PATHS = (
    'catalog/views.py',
    'catalog/templates/catalog/book_list.html',
    'catalog/tests/test_views.py',
)


def _require(path: Path, remedy: str) -> Path:
    if not path.exists():
        raise AssertionError(f'missing {path}; {remedy}')
    return path


def _run(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    _require(RUNTIME_PYTHON, 're-run the D3-runtime recovery before using the demo preview')
    _require(PREVIEW, 'restore tooling/checks/server_product/local_library_demo_preview.py')
    return subprocess.run(
        ['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', str(RUNTIME_PYTHON), '-I', '-B', str(PREVIEW), *args],
        capture_output=True, text=True, timeout=timeout,
    )


def _hashes() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for relative in BUSINESS_PATHS:
        path = DEMO / relative
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return result


@pytest.fixture(scope='module')
def run():
    _require(DEMO, 'the unmodified Local Library demo project must exist at this path')
    before = _hashes()
    database_before = (DEMO / 'db.sqlite3').exists()
    optional_test_before = (DEMO / 'catalog/tests/test_search.py').exists()
    with tempfile.TemporaryDirectory(prefix='ordessa-demo-preview-test-') as dump:
        completed = _run('--project-root', str(DEMO), '--json', '--dump-html', dump)
        report = json.loads(completed.stdout) if completed.returncode == 0 else None
        dumped = {path.stem: path for path in Path(dump).glob('*.html')} if report else {}
        yield {
            'completed': completed,
            'report': report,
            'dumped': {name: path.read_bytes() for name, path in dumped.items()},
            'before': before,
            'after': _hashes(),
            'database_before': database_before,
            'database_after': (DEMO / 'db.sqlite3').exists(),
            'optional_test_before': optional_test_before,
            'optional_test_after': (DEMO / 'catalog/tests/test_search.py').exists(),
        }


def test_the_preview_renders_the_original_book_list(run):
    completed, report = run['completed'], run['report']
    assert completed.returncode == 0, completed.stderr
    assert report['preview_format'] == 'ordessa-local-library-demo-preview/1'
    assert report['ok'] is True
    assert all(report['checks'].values()), report['checks']
    assert [render['status'] for render in report['renders']] == [200, 200, 200, 404]
    assert [render['book_links'] for render in report['renders'][:3]] == [10, 10, 3]
    assert report['renders'][0]['page_label'] == 'Page 1 of 3.'
    assert report['renders'][0]['pagination']['next_link'] is True
    assert report['renders'][2]['pagination']['next_link'] is False
    assert report['empty_state']['present'] is True
    assert report['synthetic_data']['seeded'] == {'authors': 3, 'books': 23}
    django_pin = [line for line in (DEMO / 'requirements.txt').read_text().splitlines()
                  if line.lower().startswith('django==')][0].split('==')[1]
    assert report['django_version'] == django_pin


def test_the_preview_uses_the_isolated_settings_and_memory_database(run):
    report = run['report']
    assert report['settings_source'].endswith('local_library_catalog_check_runner.py::isolated_django_settings')
    assert report['imports'] == {'demo_settings_imported': False, 'dotenv_imported': False}
    assert report['database']['configured_name'] == ':memory:'
    assert report['database']['allowed_sqlite_targets'] == [':memory:']
    assert report['database']['denied_connections'] == 0
    assert report['database']['denied_attach_detach'] == 0
    assert report['scratch']['removed'] is True


def test_the_preview_allows_loopback_hosts_without_touching_the_shared_runner(run):
    report = run['report']
    assert report['hosts_allowed'] == ['testserver', 'localhost', '127.0.0.1']
    assert '0.0.0.0' not in report['hosts_allowed']

    # The shared runner keeps its own narrow allowlist; only the preview's local
    # copy is widened, so the preview cannot quietly change the catalog check.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'local_library_catalog_check_runner',
        REPO / 'tooling/checks/server_product/local_library_catalog_check_runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    shared = runner.isolated_django_settings(DEMO, Path('/tmp/ordessa-unused-scratch'))
    assert shared['ALLOWED_HOSTS'] == ['testserver', 'localhost']


def test_the_raw_wsgi_request_is_accepted_on_loopback_and_serves_the_full_list(run):
    probe = run['report']['wsgi_probe']
    assert probe['status'] == '200 OK', 'a real WSGIHandler request with Host 127.0.0.1 must not be refused'
    assert probe['host'] == '127.0.0.1:8000'
    assert probe['path'] == '/catalog/books/'
    assert probe['bytes'] == run['report']['renders'][0]['bytes']
    assert probe['sha256'] == run['report']['renders'][0]['sha256']
    assert probe['matches_restored_page'] is True


def test_the_empty_state_probe_is_rolled_back_before_anything_is_served(run):
    report = run['report']
    assert report['checks']['empty_state'] is True
    assert report['checks']['synthetic_data_restored'] is True
    assert report['checks']['restored_page_is_the_full_list'] is True
    assert report['serve']['dataset_state'] == 'restored'
    restored = report['restored_after_empty_state']
    assert restored['sha256'] == report['renders'][0]['sha256']
    assert restored['book_links'] == 10
    assert restored['titles_present'] == report['renders'][0]['titles_present']
    # The empty state really was rendered (proof the probe ran) and it is not
    # what page_1 now contains (proof the rollback happened).
    assert b'There are no books in the library.' in run['dumped']['empty_state']
    assert b'There are no books in the library.' not in run['dumped']['page_1']


def test_the_preview_reports_search_as_not_implemented_instead_of_faking_it(run):
    search = run['report']['search']
    assert search['implemented'] is False
    assert search['form_present'] is False
    assert search['q_effect'] == 'none'
    assert {probe['same_bytes_as_page_1'] for probe in search['probes'].values()} == {True}
    assert {probe['status'] for probe in search['probes'].values()} == {200}
    pending = run['report']['pending_real_unit_checks']
    assert len(pending) == 8
    assert any('LL-SEARCH-001' in item for item in pending)
    assert any('VS-007' in item for item in pending)


def test_the_preview_leaves_the_demo_tree_and_database_alone(run):
    assert run['before'] == run['after']
    assert run['database_after'] is False
    assert run['database_before'] is False
    assert run['optional_test_before'] == run['optional_test_after']
    assert all(path is not None for path in run['after'].values())


def test_the_dumped_pages_are_the_rendered_original_page(run):
    dumped = run['dumped']
    assert set(dumped) == {'page_1', 'page_2', 'page_3', 'empty_state'}
    for name, payload in dumped.items():
        recorded = run['report']['html_dump']['pages'][name]
        assert hashlib.sha256(payload).hexdigest() == recorded['sha256']
        assert len(payload) == recorded['bytes']
    page_1 = dumped['page_1'].decode('utf-8')
    assert 'Book List' in page_1 and 'Page 1 of 3.' in page_1
    assert 'name="q"' not in page_1
    assert 'There are no books in the library.' in dumped['empty_state'].decode('utf-8')


def test_the_preview_server_stays_explicit_and_loopback_only():
    non_loopback = _run('--project-root', str(DEMO), '--serve', '--host', '0.0.0.0')
    assert non_loopback.returncode != 0
    assert 'loopback only' in non_loopback.stderr
    bad_port = _run('--project-root', str(DEMO), '--serve', '--port', '0')
    assert bad_port.returncode != 0
    assert '--port must be 1..65535' in bad_port.stderr


def test_the_preview_refuses_a_missing_project_root():
    refused = _run('--project-root', '/tmp/ordessa-no-such-demo-root')
    assert refused.returncode == 2
    payload = json.loads(refused.stdout)
    assert payload['ok'] is False
    assert 'unavailable' in payload['refused']
