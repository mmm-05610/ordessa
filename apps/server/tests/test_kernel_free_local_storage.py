"""Actual local bytes and fresh import negatives; no credential/keyring access."""
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from ordessa_infrastructure.filesystem.blobs import ObjectStore
from ordessa_infrastructure.security.secrets import SecretLocatorUnavailable, MAX_SECRET_BYTES
from ordessa_infrastructure.security.windows_dpapi import WindowsDpapiSecretStore
from ordessa_infrastructure.database import migrations as runner
from ordessa_server.bootstrap.migrations import source_selection


def test_original_cas_layout_digest_and_reopen(tmp_path):
    raw=b'controlled immutable object'
    digest='sha256:'+hashlib.sha256(raw).hexdigest()
    store=ObjectStore(tmp_path/"objects"/"sha256")
    ref=store.publish(raw)
    assert ref.path==tmp_path/'objects'/'sha256'/digest[7:9]/digest[7:]
    assert ref.digest==digest and ref.size==len(raw)
    assert ObjectStore(tmp_path/"objects"/"sha256").read(digest)==raw
    assert store.publish(raw)==ref


def test_corrupted_original_object_is_not_overwritten(tmp_path):
    store=ObjectStore(tmp_path/"objects"/"sha256");ref=store.publish(b'original')
    ref.path.write_bytes(b'corrupted')
    with pytest.raises(IOError,match='digest verification'):store.publish(b'original')
    with pytest.raises(IOError,match='digest mismatch'):store.read(ref.digest)
    assert ref.path.read_bytes()==b'corrupted'


def test_secret_error_contract_and_no_nonwindows_fallback(tmp_path):
    assert MAX_SECRET_BYTES==1024*1024
    assert SecretLocatorUnavailable('fixture-locator').code=='CREDENTIAL_NOT_AVAILABLE'
    if os.name!='nt':
        with pytest.raises(RuntimeError,match='SECRET_STORE_WINDOWS_REQUIRED'):
            WindowsDpapiSecretStore(tmp_path/"secrets"/"credentials", protect_description="AgentBox Server credential")
        assert not list(tmp_path.iterdir())


def test_fresh_local_storage_import_refuses_any_kernel_dependency():
    code='''import importlib.abc,sys
class RefuseKernel(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='pacthold' or fullname.startswith('pacthold.'):raise AssertionError('kernel dependency '+fullname)
sys.meta_path.insert(0,RefuseKernel())
import ordessa_infrastructure.filesystem.blobs
import ordessa_infrastructure.security.secrets
import ordessa_infrastructure.security.windows_dpapi
import ordessa_server.bootstrap.security.secret_service
import ordessa_infrastructure.database.migrations
import ordessa_server.bootstrap.migrations.legacy_source
assert not any(n=='pacthold' or n.startswith('pacthold.') for n in sys.modules)
assert not hasattr(ordessa_infrastructure.database.migrations,'get_conn')
assert not hasattr(ordessa_infrastructure.database.migrations,'configure_database')
'''
    completed=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=15)
    assert completed.returncode==0,completed.stderr


def test_migration_registry_keeps_source_conflicts_refused(tmp_path):
    registry=runner.MigrationRegistry()
    source=runner.MigrationSource('test.history',tmp_path,'test_versions')
    assert runner.register_migration_source(source,registry=registry) is True
    assert runner.register_migration_source(source,registry=registry) is False
    with pytest.raises(ValueError):
        runner.register_migration_source(runner.MigrationSource('test.history',tmp_path/'other','test_versions'),registry=registry)
    with pytest.raises(ValueError):
        runner.register_migration_source(runner.MigrationSource('other',tmp_path,'test_versions'),registry=registry)
