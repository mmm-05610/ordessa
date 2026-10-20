"""Architecture gate: migrated native protocols have one independent owner."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAMILIES = {'codex': ('ordessa_harness_codex', 'client.py', 'provider.py'),
            'pi': ('ordessa_harness_pi', 'client.py', 'acp_preparation.py'),
            'claude-code': ('ordessa_harness_claude_code', 'stream_json.py', 'provider.py')}


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
    package, protocol, provider = FAMILIES[family]
    source = ROOT / 'plugins/harness' / family / 'src' / package
    protocol_source = source / protocol
    provider_source = source / provider
    assert protocol_source.is_file() and protocol_source.stat().st_size > 0
    assert provider_source.is_file() and provider_source.stat().st_size > 0
    if family == 'pi':
        assert not (source / 'provider.py').exists(), 'retired Pi provider path must stay absent'
        provider_tree = ast.parse(provider_source.read_text())
        assert any(isinstance(node, ast.ClassDef) and node.name == 'PiAcpHarnessPreparation'
                   for node in provider_tree.body)
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
    brand_clients = {
        'codex': ROOT / 'plugins/harness/codex/src/ordessa_harness_codex/client.py',
        'claude-code': ROOT / 'plugins/harness/claude-code/src/ordessa_harness_claude_code/stream_json.py',
        'pi': ROOT / 'plugins/harness/pi/src/ordessa_harness_pi/client.py',
        'copilot': ROOT / 'plugins/harness/copilot/src/ordessa_harness_copilot/client.py',
        'gemini-cli': ROOT / 'plugins/harness/gemini_cli/src/ordessa_harness_gemini_cli/client.py',
        'goose': ROOT / 'plugins/harness/goose/src/ordessa_harness_goose/client.py',
        'kimi': ROOT / 'plugins/harness/kimi/src/ordessa_harness_kimi/client.py',
        'opencode': ROOT / 'plugins/harness/opencode/src/ordessa_harness_opencode/client.py',
        'qwen': ROOT / 'plugins/harness/qwen/src/ordessa_harness_qwen/client.py',
        'vibe': ROOT / 'plugins/harness/vibe/src/ordessa_harness_vibe/client.py',
    }
    assert set(brand_clients) >= {'copilot', 'gemini-cli', 'goose', 'kimi', 'opencode', 'qwen', 'vibe'}
    for path in brand_clients.values():
        assert path.is_file() and path.stat().st_size > 0
    protocols = ROOT / 'packages/execution/agents/src/ordessa_execution_agents/harness/protocols/acp'
    acp_protocol = protocols / '__init__.py'
    assert acp_protocol.is_file() and acp_protocol.stat().st_size > 0
    transport = ROOT / 'packages/execution/agents/src/ordessa_execution_agents/harness/transport'
    for name in ('http.py', 'channel.py'):
        path = transport / name
        assert path.is_file() and path.stat().st_size > 0
    retired = ROOT / 'products/agent-tools/src/ordessa_agent_tools/native_clients'
    assert not retired.exists(), 'staged client and transport implementations must have one owner'


#: 032: brand packages may not import the kernel internals, and the retired
#: root super-package name may not come back under any spelling.
FORBIDDEN_IMPORT_ROOTS = ('pacthold.harness_kit', 'ordessa_harness', 'ordessa_harness_api')
#: Retired module spellings inside the surviving brand packages (the real
#: module is ``acp_attachments``; the short name is the planted legacy import).
LEGACY_MODULE_SPELLINGS = ('ordessa_harness_claude_code.attachments',)


def legacy_harness_imports(source):
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import): names = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom): names = [node.module or '']
        else: continue
        found.extend(name for name in names
                     if any(name == root or name.startswith(root + '.')
                            for root in FORBIDDEN_IMPORT_ROOTS + LEGACY_MODULE_SPELLINGS))
    return found


def test_claude_acp_attachment_has_one_owner_and_no_legacy_exports():
    independent = ROOT / 'plugins/harness/claude-code'
    assert (independent / 'src/ordessa_harness_claude_code/acp_attachments.py').is_file()
    assert (independent / 'tests/test_acp_attachments.py').is_file()
    # 032: the legacy claude dir merged into the claude-code package; the
    # continuation id stays its only legacy export and no attachments copy exists.
    legacy = ROOT / 'plugins/harness/src/ordessa_harness'
    assert not legacy.exists(), 'the retired root super-package tree must stay absent'
    assert not (independent / 'attachments.py').exists()
    tree = ast.parse((independent / 'src/ordessa_harness_claude_code/__init__.py').read_text())
    export_names = [alias.name for node in tree.body if isinstance(node, ast.ImportFrom)
                    for alias in node.names]
    # 032: the continuation id moved to a module-level import (importing the
    # package must not drag the retired compat chain).
    assert 'ClaudeContinuationV1' not in export_names
    assert 'ClaudePreparedAttachment' not in export_names
    contracts = ast.parse((independent / 'src/ordessa_harness_claude_code/contracts.py').read_text())
    assert any(isinstance(node, ast.ClassDef) and node.name == 'ClaudeContinuationV1'
               for node in contracts.body)
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


@pytest.mark.parametrize('source', ['import pacthold.harness_kit',
    'from ordessa_harness_claude_code.attachments import ClaudePreparedAttachment'])
def test_planted_legacy_harness_dependency_is_detected(source):
    assert legacy_harness_imports(source)


def test_claude_model_compiler_and_compilation_contracts_have_one_owner():
    independent = ROOT / 'plugins/harness/claude-code/src/ordessa_harness_claude_code'
    assert (independent / 'acp_model_configuration.py').is_file()
    assert (independent / 'acp_model_facts.py').is_file()
    assert not (ROOT / 'packages/execution/kernel/src/pacthold/BRANDDIR_claude/configuration/model.py').exists()
    assert not (ROOT / 'packages/execution/kernel/src/pacthold/harness_kit/configuration/model/types.py').exists()
    contracts = ROOT / 'packages/execution/agents/src/ordessa_execution_agents/harness/definitions/model_compilation.py'
    assert contracts.is_file()
    for path in (independent / 'acp_model_configuration.py', independent / 'acp_model_facts.py', contracts):
        source = path.read_text()
        assert not legacy_harness_imports(source), path
        assert not product_imports(source), path


def test_codex_model_compiler_and_facts_have_one_independent_owner():
    source = ROOT / 'plugins/harness/codex/src/ordessa_harness_codex'
    assert not (ROOT / 'plugins/harness/src/ordessa_harness').exists()
    for name in ('acp_model_configuration.py', 'acp_model_facts.py'):
        path = source / name
        assert path.is_file()
        assert not legacy_harness_imports(path.read_text()), path
        assert not product_imports(path.read_text()), path


def test_pi_model_compiler_and_facts_have_one_independent_owner():
    source = ROOT / 'plugins/harness/pi/src/ordessa_harness_pi'
    assert not (ROOT / 'plugins/harness/src/ordessa_harness').exists()
    for name in ('acp_model_configuration.py', 'acp_model_facts.py'):
        path = source / name
        assert path.is_file()
        assert not legacy_harness_imports(path.read_text()), path
        assert not product_imports(path.read_text()), path


def test_deployment_records_have_one_independent_source_owner():
    source = ROOT / 'packages/execution/units/src/ordessa_units/records'
    assert not (ROOT / 'plugins/harness/records').exists()
    assert not (ROOT / 'packages/execution/agents/src/ordessa_execution_agents/harness/records').exists()
    assert not (ROOT / 'packages/execution/agents/src/ordessa_execution_agents/units/records').exists()
    for name in ('operation_journal.py', 'unit_records.py'):
        assert not (ROOT / 'packages/execution/kernel/src/pacthold/harness_kit/application' / name).exists()
        path = source / name
        assert path.is_file() and path.stat().st_size > 0
        assert not legacy_harness_imports(path.read_text()), path
        assert not product_imports(path.read_text()), path
