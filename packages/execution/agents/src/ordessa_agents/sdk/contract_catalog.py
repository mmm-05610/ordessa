"""Pure schema catalog of current SDK values; no execution or transport facade.

Profile JSON retains its historical stored field names. The Profile fragment is
not the retired agent-assembly/3 runtime wire contract. Native operations have
independent schemas and no RuntimeProvider/Unit protocol projection.
"""
from copy import deepcopy
import hashlib
import json
from .native_schemas import KINDS as NATIVE_ENVELOPES, native_schema
from ..profiles.definitions.schemas.profile_wire import profile_wire_sections


def contract_catalog():
    return {'schemaVersion':'agent-sdk-contract-catalog/1',
        'profileFormat':{'schemaVersion':'profile-json/1',**{k:deepcopy(v) for k,v in profile_wire_sections().items() if k!='methods'}},
        'native':{name:native_schema(name) for name in NATIVE_ENVELOPES}}


def contract_catalog_digest():
    encoded=json.dumps(contract_catalog(),sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    return 'sha256:'+hashlib.sha256(encoded).hexdigest()


def profile_contract():
    schema=contract_catalog()["profileFormat"]
    encoded=json.dumps(schema,sort_keys=True,separators=(",", ":"),ensure_ascii=False,allow_nan=False).encode("utf-8")
    return {"contractVersion":schema["schemaVersion"],"schema":schema,"schemaDigest":"sha256:"+hashlib.sha256(encoded).hexdigest()}
