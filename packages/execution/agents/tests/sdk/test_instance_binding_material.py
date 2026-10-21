"""Original binding formula survives control state, rejects self-hashed tamper."""
from copy import deepcopy
import json

import pytest

from interaction_fixtures import original_service,INSTANCE,MATERIAL,DIGEST
from test_interactions import PARAMS_BYTES
from ordessa_agents.instances.contracts import InstanceBindingMaterial
from ordessa_agents.sdk.interactions import _digest_of,InteractionsRefused
from ordessa_agents.sdk.manager import ManagerRefused
from ordessa_agents.sdk.prepare import canonical_digest


def test_full_original_material_uses_unchanged_binding_digest_formula():
    raw=MATERIAL.projection()
    assert InstanceBindingMaterial.decode(raw).projection()==raw
    assert MATERIAL.digest==INSTANCE.binding_digest==canonical_digest(raw)
    assert set(raw)=={'profileRef','harness','endpointRef','planDigest','directoryBindingDigest',
        'protocolId','sessionId','sourceRevision','configurationRefs','materialRefs'}
    assert not any(key in raw for key in ('ownerScope','credentialEpoch','useRef','environmentRef'))


@pytest.mark.parametrize('field',[
    'profileRef','harness','endpointRef','planDigest','directoryBindingDigest',
    'protocolId','sessionId','sourceRevision','configurationRefs','materialRefs',
])
def test_every_original_material_component_is_checked_beyond_control_self_hash(tmp_path,field):
    source,authority,sender,reader=original_service(tmp_path/'records.sqlite')
    try:
        original=source.read_binding(INSTANCE,invocation=reader)
        control,row=source.records.instance_control(INSTANCE)
        changed=deepcopy(row.payload);material=changed['bindingMaterial']
        if field=='profileRef':material[field]['manifestRevision']+=1
        elif field=='harness':material[field]['implementationDigest']='sha256:'+'b'*64
        elif field=='endpointRef':material[field]['endpointId']='foreign-process'
        elif field in ('planDigest','directoryBindingDigest'):material[field]='sha256:'+'b'*64
        elif field=='protocolId':material[field]=None;material['harness']['protocolId']=None;material['sessionId']=None
        elif field in ('sessionId','sourceRevision'):material[field]='foreign-original'
        elif field=='configurationRefs':material[field]=[{'schemaVersion':'prepared-configuration-ref/1',
            'issuer':'fixture','configurationId':'foreign','revision':'1','digest':DIGEST,'mediaType':'application/json',
            'byteLength':0,'location':{'rootKey':'config','relativePath':'new.json'}}]
        else:material[field]=[{'schemaVersion':'agent-material-ref/1','issuer':'fixture','materialId':'foreign',
            'revision':'1','digest':DIGEST,'mediaType':'application/json','byteLength':0,'location':None}]
        # Recompute the row checksum as a hostile/buggy store producer could:
        # authority still needs the ORIGINAL material and provenance identity.
        source.records._db.execute("UPDATE operations SET payload=?,request_digest=? WHERE operation='instance-control'",
            (json.dumps(changed,sort_keys=True),_digest_of(changed)))
        with pytest.raises(ManagerRefused):source.records.instance_control(INSTANCE)
        prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
        with pytest.raises(InteractionsRefused):
            source.reserve_turn(INSTANCE,prompt,request_id='tampered',engineering_attempt_ref='attempt',invocation=sender)
        assert source.read_binding(INSTANCE,invocation=reader)==original
        assert source.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==0
    finally:source.records.close()


def test_control_endpoint_cannot_substitute_another_process_even_with_valid_material(tmp_path):
    source,authority,sender,reader=original_service(tmp_path/'records.sqlite')
    try:
        _,row=source.records.instance_control(INSTANCE);changed=deepcopy(row.payload)
        changed['control']['endpointRef']['endpointId']='other-process'
        source.records._db.execute("UPDATE operations SET payload=?,request_digest=? WHERE operation='instance-control'",
            (json.dumps(changed,sort_keys=True),_digest_of(changed)))
        with pytest.raises(ManagerRefused,match='INSTANCE_BINDING_MISMATCH'):
            source.records.instance_control(INSTANCE)
    finally:source.records.close()


def test_materialless_earlier_control_stays_readable_history_but_cannot_authorize(tmp_path):
    source,authority,sender,reader=original_service(tmp_path/'records.sqlite')
    try:
        binding=source.read_binding(INSTANCE,invocation=reader)
        _,row=source.records.instance_control(INSTANCE);old={'control':row.payload['control']}
        source.records._db.execute("UPDATE operations SET payload=?,request_digest=? WHERE operation='instance-control'",
            (json.dumps(old,sort_keys=True),_digest_of(old)))
        assert source.read_binding(INSTANCE,invocation=reader)==binding
        with pytest.raises(ManagerRefused,match='INSTANCE_CONTROL_MATERIAL_REQUIRED'):
            source.records.writer_epoch(INSTANCE,'principal:test')
        saved=source.records.operation(row.request_id,'instance-control')
        assert saved.payload==old  # no repair/rebind/migration on normal access
    finally:source.records.close()
