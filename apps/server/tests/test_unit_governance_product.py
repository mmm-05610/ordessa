"""Product-selected original stores and role registration, zero native/model IO."""
from ordessa_units.errors import UnitGuaranteeUnavailable
from ordessa_agents.harness.providers.registry.errors import CatalogUnavailable
import hashlib
import pytest
from types import SimpleNamespace
from ordessa_server.composition.product_unit_admission import create_product_unit_admission
from ordessa_server.composition.unit_runtime import UnitRuntimeOwner
from ordessa_server.composition.harness_registration import HarnessDefinitionHandler
from ordessa_agents.harness.providers.registry import (
    HarnessDefinitionDeclaration,HarnessDefinitionDescriptor,HarnessInstallationObservation)
from ordessa_units.persistence.sqlite.store import SqliteUnitStore,WriterLockHeldError
from ordessa_server_plugin_api import ServerPluginDescriptor

class TestFingerprint:
    def describe(self):
        return {"test_only": True}
    def fingerprint(self,request,surface,digest):
        return hashlib.sha256((surface+digest).encode()).hexdigest()


def scope(path):
    return create_product_unit_admission(path,fingerprint_port=TestFingerprint(),
        agent_owner_inputs=None,native_channels_selected=False)


def test_product_preserves_namespace_original_store_and_tombstone_on_reopen(tmp_path):
    path=tmp_path/'state/core.sqlite'
    context=scope(path)
    namespace=context.environment_id
    context.store_port.record_key_tombstone('original-key')
    context.close()
    cold=scope(path)
    assert cold.environment_id==namespace
    assert cold.store_port.has_key_tombstone('original-key')
    cold.close()


def test_unknown_usage_keeps_original_product_writer_and_admission_open(tmp_path):
    path=tmp_path/'state/core.sqlite'
    context=scope(path)
    with context.store_port.transaction() as connection:
        connection.execute("INSERT INTO env_usages(usage_id,environment,state,rights) VALUES(?,?,?,?)",
            ('unknown-use',context.environment_id,'unknown','[]'))
    with pytest.raises(UnitGuaranteeUnavailable,match='pending'):
        context.close()
    context.check_open()
    assert context.pending()['usageIds']==('unknown-use',)
    with pytest.raises(WriterLockHeldError):
        SqliteUnitStore(path)
    context.store_port.close() # explicit fixture teardown; no settlement claimed


def handler(tmp_path):
    runtime=UnitRuntimeOwner(tmp_path/'state/core.sqlite',environment_factory=scope)
    return runtime,HarnessDefinitionHandler(runtime)


def declaration(namespace):
    descriptor=HarnessDefinitionDescriptor('controlled.provider',
        {'environmentNamespace':namespace,'definitionId':'definition','revision':'1'},
        'sha256:'+'a'*64,'acp','1')
    def observe(*args):
        raise AssertionError('registration must never execute installation observation')
    return HarnessDefinitionDeclaration(descriptor,observe)


def test_role_registration_original_generation_and_exact_retirement(tmp_path):
    runtime,consumer=handler(tmp_path)
    descriptor=ServerPluginDescriptor(id='controlled.plugin',display_name='Controlled',version='1',api_version=1)
    token=consumer.begin_owner_activation(descriptor)
    contribution=SimpleNamespace(payload=(declaration(runtime.context.environment_id),))
    prepared=consumer.stage(contribution,descriptor.id)
    consumer.commit(contribution,prepared,descriptor.id)
    assert runtime.context.harness_catalog.list()[0].provider_ref['generation']==token.generation
    consumer.retire_owner_activation(descriptor,token)
    assert runtime.context.harness_catalog.list()==()
    runtime.close()
    runtime.open()
    next_token=consumer.begin_owner_activation(descriptor)
    assert next_token.generation>token.generation
    consumer.rollback_owner_activation(descriptor,next_token)
    runtime.close()


def test_role_unknown_commit_never_replays_or_closes_catalog(tmp_path,monkeypatch):
    runtime,consumer=handler(tmp_path)
    descriptor=ServerPluginDescriptor(id='controlled.plugin',display_name='Controlled',version='1',api_version=1)
    token=consumer.begin_owner_activation(descriptor)
    contribution=SimpleNamespace(payload=(declaration(runtime.context.environment_id),))
    consumer.stage(contribution,descriptor.id)
    calls=[]
    def unknown(*args):
        calls.append(args)
        raise OSError('lost registration outcome')
    monkeypatch.setattr(runtime.context.harness_catalog,'_commit',unknown)
    with pytest.raises(OSError):
        consumer.commit(contribution,token,descriptor.id)
    with pytest.raises(Exception):
        consumer.commit(contribution,token,descriptor.id)
    assert len(calls)==1
    with pytest.raises(CatalogUnavailable,match='unknown'):
        consumer.retire_owner_activation(descriptor,token)
    with pytest.raises(Exception):
        runtime.close()
    runtime.context.store_port.close() # teardown preserves unknown semantic


def test_runtime_unknown_retains_original_writer_and_os_root(tmp_path):
    from ordessa_server.composition.runtime import build_runtime,DataRootOwner
    from ordessa_server.bootstrap.storage.product_database import Database
    from ordessa_server_plugin_api import ServerPluginSelection
    selection=ServerPluginSelection(plugins=(),environment_factory=scope)
    runtime=build_runtime(tmp_path/'root',server_plugins=selection,database_factory=Database)
    runtime.start()
    context=runtime.unit_runtime.context
    with context.store_port.transaction() as connection:
        connection.execute("INSERT INTO env_usages(usage_id,environment,state,rights) VALUES(?,?,?,?)",
            ('unknown-live-use',context.environment_id,'unknown','[]'))
    with pytest.raises(UnitGuaranteeUnavailable,match='pending'):
        runtime.stop()
    assert runtime.owner.acquired
    context.check_open()
    with pytest.raises(Exception):
        DataRootOwner(runtime.data_root).acquire()
    with pytest.raises(WriterLockHeldError):
        SqliteUnitStore(context.store_path)
    # Teardown only, retaining original unresolved row. This does not settle it.
    context.store_port.close()
    runtime.owner.release()
