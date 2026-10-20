#!/usr/bin/env python3
"""Preview the original Local Library book list page from synthetic in-memory data.

The third block will change ``catalog/views.py``, ``book_list.html`` and
``catalog/tests/*``. This script is the repeatable way to look at that page
*before* any of that lands, so a demo cannot be confused with an implementation.

What it does and does not do:

- Settings: reuses ``isolated_django_settings`` from
  ``tooling/checks/server_product/local_library_catalog_check_runner.py``. The
  demo's own ``locallibrary.settings`` and ``.env`` are never imported.
- Database: in-memory SQLite only, guarded by the same ``SQLiteMemoryGuard``
  that refuses disk SQLite and reports every denial. No real database is read.
- Data: explicit synthetic authors/books seeded through the ORM, 23 books so the
  existing paginator produces 10/10/3.
- Search: *not implemented and not simulated*. ``?q=`` has no effect today, the
  book list template has no search form, and this script records exactly that
  instead of faking a hit/no-hit distinction. The pending verification items for
  the real Unit implementation are listed in the output.
- ``--serve``: opt-in, loopback only, foreground only. This check does not use
  it and never starts a server by itself.
- Cleanup: the only scratch resources are the temporary static/media roots, which
  are removed before exit; the in-memory database disappears with the process.

Usage (the recovered check runtime is the interpreter that has Django):

    .nightly-cache/local-library-runtime-20261017/bin/python -I -B \\
        tooling/checks/server_product/local_library_demo_preview.py \\
        --project-root /home/maoqh/projects/ordessa-demo-local-library
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import sys
import tempfile
from typing import Any

# Never write .pyc into the demo tree or this checkout while previewing.
sys.dont_write_bytecode = True

RUNNER_PATH = Path(__file__).resolve().parent / 'local_library_catalog_check_runner.py'
SYNTHETIC_AUTHORS = (('Ada', 'Lovelace'), ('Grace', 'Hopper'), ('Alan', 'Turing'))
TITLE_HIT_BOOK = 'The Django Search Handbook'
AUTHOR_HIT_BOOK = 'Author Hopper in Practice'
NO_MATCH_QUERY = 'zzz-synthetic-no-match'
HIT_QUERIES = ('django', 'hopper')
PAGE_SIZE = 10
PENDING_REAL_UNIT_CHECKS = (
    'LL-SEARCH-001 .. LL-SEARCH-010 (candidate requirements in the demo docs/ordessa-did/candidate-search package)',
    'VS-001 empty/blank q returns the same list as the baseline',
    'VS-002 title/first_name/last_name substring match, case-insensitive, one field is enough',
    'VS-003 %, _ and quote queries stay literal; null-author title still matches; no-match is an empty result, not the full list',
    'VS-004 21 matching rows paginate 10/10/1 with the query carried across pages',
    'VS-005 new query drops the old page parameter; input and empty states stay auto-escaped',
    'VS-006 anonymous/logged-in/GET/HEAD/OPTIONS unchanged, POST stays 405, invalid page stays 404',
    'VS-007 no model/migration/settings/dependency change; database contents unchanged by searching',
)
GUARDED_URLS = (
    ('page_1', '/catalog/books/'),
    ('page_2', '/catalog/books/?page=2'),
    ('page_3', '/catalog/books/?page=3'),
    ('page_beyond_last', '/catalog/books/?page=99'),
)


class PreviewRefused(RuntimeError):
    """A bounded, non-secret preview configuration failure."""


class PreviewMismatch(RuntimeError):
    """The original page did not render what the preview claims."""


def load_runner():
    """Load the check runner as a module: single source for settings and guards."""
    spec = importlib.util.spec_from_file_location('local_library_catalog_check_runner', RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_spec() -> dict[str, Any]:
    """Return the exact seed spec, so the preview data itself is verifiable."""
    books = [
        {'title': AUTHOR_HIT_BOOK, 'author': ['Grace', 'Hopper']},
        {'title': TITLE_HIT_BOOK, 'author': ['Ada', 'Lovelace']},
    ]
    books += [
        {'title': f'Synthetic Library Volume {number:02d}',
         'author': list(SYNTHETIC_AUTHORS[number % len(SYNTHETIC_AUTHORS)])}
        for number in range(1, 22)
    ]
    return {
        'authors': [list(author) for author in SYNTHETIC_AUTHORS],
        'books': books,
        'book_count': len(books),
        'page_size': PAGE_SIZE,
        'expected_page_sizes': [PAGE_SIZE, PAGE_SIZE, len(books) - 2 * PAGE_SIZE],
        'title_hit': {'title': TITLE_HIT_BOOK, 'query': 'django'},
        'author_hit': {'title': AUTHOR_HIT_BOOK, 'query': 'hopper'},
        'no_match_query': NO_MATCH_QUERY,
    }


def seed(project_root: Path) -> dict[str, int]:
    from catalog.models import Author, Book

    authors = {}
    for first_name, last_name in SYNTHETIC_AUTHORS:
        authors.setdefault((first_name, last_name), Author.objects.get_or_create(
            first_name=first_name, last_name=last_name)[0])
    spec = synthetic_spec()
    for index, item in enumerate(spec['books'], start=1):
        Book.objects.create(
            title=item['title'],
            author=authors[tuple(item['author'])],
            summary=f'Synthetic preview row {index}; not demo or user data.',
            isbn=f'978000000{index:04d}',
        )
    return {'authors': len(authors), 'books': Book.objects.count()}


def wsgi_get(path: str, host: str) -> dict[str, Any]:
    """One real WSGI request in-process: no socket, no server, no reload."""
    import io

    from django.core.wsgi import get_wsgi_application

    application = get_wsgi_application()
    server_name, _, server_port = host.partition(':')
    environ = {
        'REQUEST_METHOD': 'GET', 'SCRIPT_NAME': '', 'PATH_INFO': path, 'QUERY_STRING': '',
        'SERVER_NAME': server_name, 'SERVER_PORT': server_port or '80', 'HTTP_HOST': host,
        'SERVER_PROTOCOL': 'HTTP/1.1', 'REMOTE_ADDR': '127.0.0.1',
        'wsgi.version': (1, 0), 'wsgi.url_scheme': 'http',
        'wsgi.input': io.BytesIO(b''), 'wsgi.errors': io.StringIO(),
        'wsgi.multithread': False, 'wsgi.multiprocess': False, 'wsgi.run_once': False,
    }
    captured: dict[str, Any] = {}

    def start_response(status, headers, exc_info=None):
        captured['status'] = status
        captured['headers'] = dict(headers)
        return lambda chunk: None

    body = b''.join(application(environ, start_response))
    return {'status': captured['status'], 'bytes': len(body),
            'sha256': hashlib.sha256(body).hexdigest(), 'body': body}


def render(client, label: str, url: str) -> dict[str, Any]:
    response = client.get(url)
    if response.status_code >= 500:
        raise PreviewMismatch(f'{label} answered {response.status_code}')
    body = response.content
    text = body.decode('utf-8', errors='strict')
    page_label = ''
    for candidate in (1, 2, 3):
        marker = f'Page {candidate} of '
        if marker in text:
            page_label = text[text.index(marker):text.index(marker) + 40].split('<')[0].strip()
            break
    return {
        'label': label,
        'url': url,
        'status': response.status_code,
        'bytes': len(body),
        'sha256': hashlib.sha256(body).hexdigest(),
        'book_links': text.count('href="/catalog/book/'),
        'page_label': page_label,
        'pagination': {
            'previous_link': '>previous<' in text,
            'next_link': '>next<' in text,
        },
        'titles_present': {
            TITLE_HIT_BOOK: TITLE_HIT_BOOK in text,
            AUTHOR_HIT_BOOK: AUTHOR_HIT_BOOK in text,
        },
        'search_form_present': 'name="q"' in text,
        'html': text,
    }


def run_preview(project_root: str) -> tuple[dict[str, Any], dict[str, str]]:
    runner = load_runner()
    try:
        root = runner.validate_project_root(project_root)
    except runner.RunnerConfigurationError as error:
        raise PreviewRefused(str(error)) from None
    if root != Path(project_root):
        raise PreviewRefused('project root must be the exact absolute demo path')
    sys.path.insert(0, str(root))

    import django
    if django.get_version() != runner.DJANGO_VERSION:
        raise PreviewRefused(f'requires Django {runner.DJANGO_VERSION}, found {django.get_version()}')

    from django.conf import settings
    if settings.configured:
        raise PreviewRefused('Django settings were already configured')
    if 'locallibrary.settings' in sys.modules or any(n.startswith('locallibrary.settings.') for n in sys.modules):
        raise PreviewRefused('the demo settings module must not be imported')
    if any(n == 'dotenv' or n.startswith('dotenv.') for n in sys.modules):
        raise PreviewRefused('dotenv must not be imported; no .env is read')

    with tempfile.TemporaryDirectory(prefix='ordessa-local-library-demo-preview-') as scratch:
        config = runner.isolated_django_settings(root, Path(scratch))
        # Preview-local host allowlist only: the loopback preview server and the WSGI
        # probe send Host: 127.0.0.1[:port], which the shared runner settings (built for
        # the test client's "testserver") answer with 400. The shared runner module is
        # not modified, and --serve still binds loopback only.
        config['ALLOWED_HOSTS'] = ['testserver', 'localhost', '127.0.0.1']
        Path(config['STATIC_ROOT']).mkdir(parents=True, exist_ok=True)
        Path(config['MEDIA_ROOT']).mkdir(parents=True, exist_ok=True)
        settings.configure(**config)
        guard = runner.SQLiteMemoryGuard()
        guard.install()
        django.setup()

        from django.core.management import call_command
        call_command('migrate', run_syncdb=True, verbosity=0, interactive=False)

        counts = seed(root)

        from django.test import Client
        client = Client()
        renders = [render(client, label, url) for label, url in GUARDED_URLS]
        page_1 = renders[0]
        baseline_html = page_1.pop('html')
        html_pages = {'page_1': baseline_html,
                      'page_2': renders[1].pop('html'),
                      'page_3': renders[2].pop('html')}

        probes = {}
        for label, url in (('q_title_hit', f'/catalog/books/?q={HIT_QUERIES[0]}'),
                           ('q_author_hit', f'/catalog/books/?q={HIT_QUERIES[1]}'),
                           ('q_no_match', f'/catalog/books/?q={NO_MATCH_QUERY}')):
            response = client.get(url)
            probes[label] = {
                'status': response.status_code,
                'book_links': response.content.count(b'href="/catalog/book/'),
                'same_bytes_as_page_1': response.content == baseline_html.encode('utf-8'),
            }
        search_form_present = 'name="q"' in baseline_html

        from django.db import transaction

        from catalog.models import Book
        # The empty-state probe runs inside a rolled-back transaction: a preview
        # server must never end up serving the empty list the probe produced.
        with transaction.atomic():
            Book.objects.all().delete()
            empty = client.get('/catalog/books/')
            empty_text = empty.content.decode('utf-8', errors='strict')
            transaction.set_rollback(True)
        html_pages['empty_state'] = empty_text

        restored_counts = {'books': Book.objects.count()}
        restored = render(client, 'page_1_restored', '/catalog/books/')
        restored.pop('html')
        wsgi = wsgi_get('/catalog/books/', '127.0.0.1:8000')
        wsgi.pop('body')

        expected_sizes = synthetic_spec()['expected_page_sizes']
        observed_sizes = [item['book_links'] for item in renders[:3]]
        demo_settings_imported = any(
            name == 'locallibrary.settings' or name.startswith('locallibrary.settings.') for name in sys.modules)
        dotenv_imported = any(name == 'dotenv' or name.startswith('dotenv.') for name in sys.modules)
        checks = {
            'all_renders_ok': all(item['status'] == 200 for item in renders[:3]),
            'page_sizes': observed_sizes == expected_sizes,
            'pagination_links': page_1['pagination']['next_link'] is True
                                and renders[2]['pagination']['next_link'] is False,
            'empty_page_404': renders[3]['status'] == 404,
            'empty_state': 'There are no books in the library.' in empty_text,
            'synthetic_data_restored': restored_counts['books'] == synthetic_spec()['book_count']
                                       and restored['book_links'] == PAGE_SIZE,
            'restored_page_is_the_full_list': restored['sha256'] == page_1['sha256']
                                              and restored['page_label'] == 'Page 1 of 3.',
            'wsgi_loopback_host_accepted': wsgi['status'].startswith('200'),
            'wsgi_body_is_the_restored_list': wsgi['sha256'] == restored['sha256'],
            'no_search_form_yet': search_form_present is False,
            'no_disk_database': guard.denied_connections == 0 and guard.denied_attach_detach == 0,
            'no_demo_settings': demo_settings_imported is False,
            'no_dotenv': dotenv_imported is False,
        }
        search_implemented = search_form_present or not all(
            probe['same_bytes_as_page_1'] for probe in probes.values())

        report = {
            'preview_format': 'ordessa-local-library-demo-preview/1',
            'project_root': str(root),
            'django_version': django.get_version(),
            'settings_source': 'tooling/checks/server_product/local_library_catalog_check_runner.py::isolated_django_settings',
            'hosts_allowed': list(config['ALLOWED_HOSTS']),
            'imports': {'demo_settings_imported': demo_settings_imported,
                        'dotenv_imported': dotenv_imported},
            'database': {
                'engine': config['DATABASES']['default']['ENGINE'],
                'configured_name': config['DATABASES']['default']['NAME'],
                'allowed_sqlite_targets': sorted(guard.allowed_targets),
                'allowed_connections': guard.allowed_connections,
                'denied_connections': guard.denied_connections,
                'denied_attach_detach': guard.denied_attach_detach,
            },
            'synthetic_data': {
                **synthetic_spec(),
                'seeded': counts,
                'digest': hashlib.sha256(json.dumps(synthetic_spec(), sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            },
            'renders': [{key: value for key, value in item.items() if key != 'html'} for item in renders],
            'restored_after_empty_state': {key: value for key, value in restored.items() if key != 'html'},
            'wsgi_probe': {
                **wsgi,
                'host': '127.0.0.1:8000',
                'path': '/catalog/books/',
                'matches_restored_page': wsgi['sha256'] == restored['sha256'],
                'note': 'one real WSGIHandler request in-process; no socket, no server, no reload',
            },
            'empty_state': {
                'status': empty.status_code,
                'marker': 'There are no books in the library.',
                'present': 'There are no books in the library.' in empty_text,
            },
            'search': {
                'implemented': search_implemented,
                'form_present': search_form_present,
                'q_effect': 'none' if all(probe['same_bytes_as_page_1'] for probe in probes.values()) else 'changed',
                'probes': probes,
                'note': ('The book list page ignores q today and has no search form: this preview shows the page as it '
                         'is, it does not implement or imitate the pending search change.'),
            },
            'pending_real_unit_checks': list(PENDING_REAL_UNIT_CHECKS),
            'serve': {'requested': False,
                      'dataset_state': 'restored' if checks['synthetic_data_restored'] else 'not_restored'},
            'scratch': {'root': scratch, 'removed': False},
            'checks': checks,
        }
    report['scratch']['removed'] = not Path(report['scratch']['root']).exists()
    report['ok'] = all(checks.values()) and report['scratch']['removed']
    return report, html_pages


def serve(report: dict[str, Any], host: str, port: int) -> None:
    """Foreground loopback preview; never started unless --serve is explicit."""
    if host != '127.0.0.1':
        raise PreviewRefused('--serve is loopback only')
    from django.core.wsgi import get_wsgi_application
    from wsgiref.simple_server import make_server

    application = get_wsgi_application()
    url = f'http://{host}:{port}/catalog/books/'
    print(f'preview server (foreground, loopback only): {url}', flush=True)
    print('Ctrl-C to stop; this check never starts it for you.', flush=True)
    with make_server(host, port, application) as httpd:
        httpd.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Render the original Local Library book list page from synthetic in-memory data.')
    parser.add_argument('--project-root', required=True,
                        help='absolute path to the unmodified Local Library demo project')
    parser.add_argument('--serve', action='store_true',
                        help='keep an explicit foreground loopback preview server alive after rendering')
    parser.add_argument('--host', default='127.0.0.1', help='loopback host for --serve (default 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8000, help='port for --serve (default 8000)')
    parser.add_argument('--json', action='store_true', help='print the full report instead of the summary')
    parser.add_argument('--dump-html', metavar='DIR',
                        help='write the rendered original pages into DIR as review evidence (created if missing)')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.host != '127.0.0.1':
        raise SystemExit('refused: the preview server is loopback only (--host 127.0.0.1)')
    if not 1 <= args.port <= 65535:
        raise SystemExit('refused: --port must be 1..65535')
    try:
        report, html_pages = run_preview(args.project_root)
    except (PreviewRefused, PreviewMismatch) as error:
        print(json.dumps({'ok': False, 'refused': str(error)}, sort_keys=True))
        return 2
    if args.dump_html:
        target = Path(args.dump_html)
        target.mkdir(parents=True, exist_ok=True)
        dumped = {}
        for name, html in html_pages.items():
            path = target / f'{name}.html'
            path.write_text(html, encoding='utf-8')
            dumped[name] = {'path': str(path), 'bytes': len(html.encode('utf-8')),
                            'sha256': hashlib.sha256(html.encode('utf-8')).hexdigest()}
        report['html_dump'] = {'directory': str(target), 'pages': dumped}
    if args.serve:
        if not report['ok']:
            raise SystemExit('refused: the page did not render as expected; fix the preview before serving it')
        report['serve'] = {'requested': True, 'url': f'http://{args.host}:{args.port}/catalog/books/'}
        print(json.dumps({k: v for k, v in report.items() if k != 'scratch'}, indent=2, sort_keys=True))
        serve(report, args.host, args.port)
        return 0
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps({k: v for k, v in report.items() if k != 'synthetic_data'}, indent=2, sort_keys=True))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
