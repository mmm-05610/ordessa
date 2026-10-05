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


def legacy_harness_imports(source):
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import): names = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom): names = [node.module or '']
        else: continue
        found.extend(name for name in names if name == 'ordessa_harness' or name.startswith('ordessa_harness.'))
    return found


def test_claude_acp_attachment_has_one_owner_and_no_legacy_exports():
    independent = ROOT / 'plugins/harness/claude-code'
    assert (independent / 'src/ordessa_harness_claude_code/acp_attachments.py').is_file()
    assert (independent / 'tests/test_acp_attachments.py').is_file()
    legacy = ROOT / 'plugins/harness/src/ordessa_harness/claude'
    assert not (legacy / 'attachments.py').exists()
    tree = ast.parse((legacy / '__init__.py').read_text())
    exports = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
    assert len(exports) == 1 and exports[0].module == 'contracts'
    assert [alias.name for alias in exports[0].names] == ['ClaudeContinuationV1']
    # This gate owns source independence and the migrated pure attachment tests.
    # Lifecycle integration tests deliberately exercise the original store/issuer.
    files = tuple((independent / 'src').rglob('*.py')) + (
        independent / 'tests/test_acp_attachments.py',
        independent / 'tests/test_acp_attachments_distribution.py',
    )
    assert files
    for path in files:
        assert not legacy_harness_imports(path.read_text()), path
        assert not product_imports(path.read_text()), path


@pytest.mark.parametrize('source', ['import ordessa_harness',
    'from ordessa_harness.claude.attachments import ClaudePreparedAttachment'])
def test_planted_legacy_harness_dependency_is_detected(source):
    assert legacy_harness_imports(source)


def test_claude_model_compiler_and_compilation_contracts_have_one_owner():
    independent = ROOT / 'plugins/harness/claude-code/src/ordessa_harness_claude_code'
    assert (independent / 'acp_model_configuration.py').is_file()
    assert (independent / 'acp_model_facts.py').is_file()
    assert not (ROOT / 'plugins/harness/src/ordessa_harness/claude/configuration/model.py').exists()
    assert not (ROOT / 'plugins/harness/src/ordessa_harness/configuration/model/types.py').exists()
    contracts = ROOT / 'plugins/harness/api/src/ordessa_harness_api/model_compilation.py'
    assert contracts.is_file()
    for path in (independent / 'acp_model_configuration.py', independent / 'acp_model_facts.py', contracts):
        source = path.read_text()
        assert not legacy_harness_imports(source), path
        assert not product_imports(source), path
