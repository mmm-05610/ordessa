"""Qoder registration cannot turn unknown native facts into executable support."""
import asyncio
from dataclasses import replace
from pathlib import Path
import ast
import pytest
from ordessa_agents.sdk import HarnessError
from ordessa_agents.profiles import decode_content
from ordessa_harness_qoder import factory,registered_keys

PIN={'environmentNamespace':'test','definitionId':'qoder','revision':'1'}

def test_actual_factory_pin_and_existing_native_key_registry():
    provider=factory.build({'definition_ref':PIN,'implementation_digest':'sha256:'+'a'*64})
    content=decode_content({'schemaVersion':'1','harnessDefinitionRef':PIN,'declarations':[]},'test')
    provider.validate_profile(content)
    assert provider.descriptor.provider_id=='qoder' and provider.descriptor.protocol_id is None
    assert registered_keys()
    with pytest.raises(HarnessError,match='PROFILE_HARNESS_PIN_MISMATCH'):
        provider.validate_profile(replace(content,harness_definition_ref={**PIN,'revision':'2'}))
    with pytest.raises(HarnessError,match='NATIVE_LAUNCH_UNAVAILABLE'):provider.prepare(content,object())
    with pytest.raises(HarnessError,match='NATIVE_PROTOCOL_BOOTSTRAP_UNAVAILABLE'):
        asyncio.run(provider.open_session(object(),object()))


def test_factory_never_accepts_authority_and_source_imports_only_sdk():
    with pytest.raises(HarnessError,match='HARNESS_BINDINGS_INVALID'):factory.build({'grant':object()})
    import ordessa_harness_qoder.provider as module
    for node in ast.walk(ast.parse(Path(module.__file__).read_text())):
        if isinstance(node,ast.ImportFrom) and (node.module or '').startswith('ordessa_'):
            assert node.module=='ordessa_agents.sdk'
