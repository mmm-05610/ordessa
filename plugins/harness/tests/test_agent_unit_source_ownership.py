"""Architecture gate: migrated native protocols have one independent owner."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FAMILIES = {'codex': ('ordessa_harness_codex', 'client.py'),
            'pi': ('ordessa_harness_pi', 'client.py'),
            'claude-code': ('ordessa_harness_claude_code', 'stream_json.py')}


def product_imports(source):
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import): names = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom): names = [node.module or '']
        else: continue
        found.extend(name for name in names if name == 'ordessa_agent_tools' or name.startswith('ordessa_agent_tools.'))
    return found


@pytest.mark.parametrize('family', FAMILIES)
def test_independent_family_has_protocol_and_provider_without_product_dependency(family):
    package, protocol = FAMILIES[family]
    source = ROOT / 'plugins/harness' / family / 'src' / package
    assert (source / protocol).is_file() and (source / 'provider.py').is_file()
    files = tuple(source.rglob('*.py')) + tuple((ROOT / 'plugins/harness' / family / 'tests').rglob('*.py'))
    assert files
    for path in files:
        assert not product_imports(path.read_text()), path
    old = ROOT / 'products/agent-tools/src/ordessa_agent_tools/native_clients' / (family.replace('-', '_') + '.py')
    assert not old.exists(), 'Migrated native protocol must not remain in the CLI product'


@pytest.mark.parametrize('source', ['import ordessa_agent_tools', 'from ordessa_agent_tools.native_clients._transport import Message',
    'import ordessa_agent_tools.native_clients.codex as codex'])
def test_planted_product_dependency_is_detected(source):
    assert product_imports(source)


def test_remaining_staged_families_and_shared_transports_still_present():
    staged = ROOT / 'products/agent-tools/src/ordessa_agent_tools/native_clients'
    for name in ('copilot', 'gemini_cli', 'goose', 'kimi', 'opencode', 'qwen', 'vibe', '_transport', '_http', '_acp'):
        path = staged / (name + '.py')
        assert path.is_file() and path.stat().st_size > 0
