"""Pure demand-side Agent refs, exact read-only history, no execution dependency."""
import hashlib
import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.common.models.execution_refs import (
    agent_instance_ref_bytes, read_agent_instance_ref, agent_instance_identity,
    read_historical_unit_ref,
)
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError


def new_ref(**changes):
    return {'schemaVersion':'agent-instance/1','namespace':'existing-namespace',
            'instanceId':'agent-instance','bindingDigest':'sha256:'+'a'*64,**changes}


def old_ref():
    return {'environmentNamespace':'existing-namespace','unitId':'old-unit',
            'ownerProviderRef':{'provider':'original','metadata':{'items':[1,2]}},'sourceRevision':'original-revision'}


def test_new_ref_roundtrip_and_no_execution_package_import():
    value=new_ref();raw=agent_instance_ref_bytes(value)
    assert dict(read_agent_instance_ref(raw))==value
    assert agent_instance_ref_bytes(read_agent_instance_ref(raw))==raw
    assert agent_instance_identity(value)==('existing-namespace','agent-instance')
    with pytest.raises(TypeError):read_agent_instance_ref(raw)['instanceId']='another'


def test_historical_bytes_digest_unchanged_and_metadata_read_only():
    raw=canonical_bytes(old_ref());before=hashlib.sha256(raw).hexdigest()
    result=read_historical_unit_ref(raw)
    assert result['unitId']=='old-unit'
    assert hashlib.sha256(raw).hexdigest()==before
    with pytest.raises(TypeError):result['ownerProviderRef']['metadata']['items'][0]=3
    with pytest.raises(ReferenceError):agent_instance_ref_bytes(result)
    with pytest.raises(ReferenceError):read_agent_instance_ref(raw)


@pytest.mark.parametrize('change',[
    {'schemaVersion':'agent-instance/2'}, {'bindingDigest':'sha256:ABC'},
    {'bindingDigest':'sha256:'+'A'*64}, {'namespace':''}, {'instanceId':'bad\nidentity'},
    {'unitId':'hidden-alias'}, {'grant':'copied-authority'},
])
def test_malformed_and_extra_authority_fields_refused(change):
    with pytest.raises(ReferenceError):agent_instance_ref_bytes(new_ref(**change))


def test_noncanonical_unknown_and_mixed_versions_refused():
    raw=agent_instance_ref_bytes(new_ref())
    with pytest.raises(ReferenceError):read_agent_instance_ref(b' '+raw)
    with pytest.raises(ReferenceError):read_historical_unit_ref(raw)
    with pytest.raises(ReferenceError):read_agent_instance_ref(canonical_bytes({**new_ref(),'useRef':'forbidden'}))
    with pytest.raises(ReferenceError):read_historical_unit_ref(canonical_bytes({**old_ref(),'schemaVersion':'agent-instance/1'}))


def test_binding_change_cannot_evade_author_reviewer_actor_distinction():
    a=new_ref();b=new_ref(bindingDigest='sha256:'+'b'*64)
    assert agent_instance_ref_bytes(a)!=agent_instance_ref_bytes(b)
    assert agent_instance_identity(a)==agent_instance_identity(b)
