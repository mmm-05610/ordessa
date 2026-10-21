"""Isolated import-boundary proof for the extracted Agent owner package."""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def test_public_owner_imports_only_from_current_tree_and_keeps_core_identity():
    script = f"""
import importlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path({str(ROOT)!r})

# The editable installation must already resolve to this checkout. Probe the
# retired namespace before installing any guard that could mask its presence.
try:
    old_owner_spec = importlib.util.find_spec('pacthold.agents')
except ModuleNotFoundError:
    old_owner_spec = None
assert old_owner_spec is None, old_owner_spec
for old_module in ('pacthold.agents.public', 'pacthold.agents.schema',
                   'pacthold.agents.managed_input', 'pacthold.agents.profiles.catalog',
                   'pacthold.agents.runtime', 'pacthold.agents.assembly.agent'):
    try:
        old_module_spec = importlib.util.find_spec(old_module)
    except ModuleNotFoundError:
        old_module_spec = None
    assert old_module_spec is None, (old_module, old_module_spec)

class ForbiddenImportError(ImportError):
    def __init__(self, fullname):
        self.fullname = fullname
        super().__init__('blocked forbidden import: ' + fullname)

FORBIDDEN = (
    'pacthold.agents',
    'apps', 'products',
    'ordessa_server', 'ordessa_server_product', 'ordessa_cli',
    'ordessa_harness_claude_code', 'ordessa_harness_codex',
    'ordessa_harness_copilot', 'ordessa_harness_dsh',
    'ordessa_harness_gemini_cli', 'ordessa_harness_goose',
    'ordessa_harness_grok_build', 'ordessa_harness_hermes',
    'ordessa_harness_kilo', 'ordessa_harness_kimi',
    'ordessa_harness_opencode', 'ordessa_harness_pi',
    'ordessa_harness_qoder', 'ordessa_harness_qwen',
    'ordessa_harness_vibe',
)

def forbidden(fullname):
    return any(fullname == prefix or fullname.startswith(prefix + '.')
               for prefix in FORBIDDEN)

class ImportBoundary:
    def __init__(self):
        self.seen = []
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            self.seen.append(fullname)
            raise ForbiddenImportError(fullname)

boundary = ImportBoundary()
sys.meta_path.insert(0, boundary)

import ordessa_units.public as public
from ordessa_agents.harness.definitions.runtime_providers import RuntimeProviderDescriptor
from ordessa_agents.harness.definitions.configuration_providers import ConfigurationProviderDescriptor

expected_public = ROOT / 'packages/execution/agents/src/ordessa_agents/public.py'
assert Path(public.__file__).resolve() == expected_public.resolve()
assert public.RuntimeProviderDescriptor is RuntimeProviderDescriptor
assert public.ConfigurationProviderDescriptor is ConfigurationProviderDescriptor
assert not boundary.seen, boundary.seen

for brand_service in ('ManagedCodexInputService', 'ManagedTextCapture',
                      'ManagedTextCaptureContentPort'):
    assert not hasattr(public, brand_service), brand_service
    assert brand_service not in getattr(public, '__all__', ()), brand_service

management = public.wire_contract(public.AGENT_MANAGEMENT_CONTRACT_VERSION)
assert public.AGENT_MANAGEMENT_CONTRACT_VERSION == 'agent-assembly/3'
assert management['contractVersion'] == 'agent-assembly/3'
assert management['transport'] == 'wire/1'
assert management['methods']['agents.operations.read']['action'] == 'operationRead'

# The old owner ID remains reserved by the existing Environment authority.
from pacthold.core.registration import RegistrationConflictError
from pacthold.environment import Environment
try:
    Environment('owner-cutover-check').stage_activation('pacthold.agents')
except RegistrationConflictError:
    pass
else:
    raise AssertionError('pacthold.agents must remain a reserved core owner ID')

# Negative probes must be refused by our dedicated boundary exception, so an
# ordinary missing-module ImportError cannot make the boundary test pass.
for name in ('pacthold.agents', 'pacthold.agents.public',
             'pacthold.agents.schema', 'pacthold.agents.managed_input',
             'ordessa_server', 'ordessa_server_product', 'ordessa_cli',
             'ordessa_harness_codex', 'ordessa_harness_pi'):
    try:
        importlib.import_module(name)
    except ForbiddenImportError as error:
        expected_blocked_name = 'pacthold.agents' if name.startswith('pacthold.agents.') else name
        assert error.fullname == expected_blocked_name
    else:
        raise AssertionError('forbidden import unexpectedly succeeded: ' + name)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
