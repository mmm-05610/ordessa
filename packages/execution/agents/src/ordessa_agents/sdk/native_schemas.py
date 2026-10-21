"""Data-only JSON Schema for native-operation/1; digests require typed codecs too."""
from copy import deepcopy
S={'type':'string','minLength':1,'maxLength':512}
TEXT={'type':'string','minLength':1,'maxLength':4096}
DIGEST={'type':'string','pattern':'^sha256:[0-9a-f]{64}$'}
HEX={'type':'string','pattern':'^[0-9a-f]{64}$'}


def closed(properties,required=None):
    return {'type':'object','properties':properties,'required':list(properties) if required is None else required,'additionalProperties':False}


def ref(name):return {'$ref':'#/$defs/'+name}

PARAMS=closed({'sessionId':TEXT,'operationId':{'type':'string','minLength':1,'maxLength':128},
    'expectedGeneration':TEXT,'expectedConfigDigest':HEX,'configId':{'enum':['model','thinkingLevel']},
    'value':TEXT,'actionManifest':ref('Manifest')},['sessionId','operationId','expectedGeneration','expectedConfigDigest','configId','value'])
DEFS={
 'Instance':closed({'schemaVersion':{'const':'agent-instance/1'},'namespace':S,'instanceId':S,'bindingDigest':DIGEST}),
 'Endpoint':closed({'schemaVersion':{'const':'agent-endpoint/1'},'issuer':S,'endpointId':S,'revision':S,'descriptorDigest':DIGEST}),
 'Manifest':closed({'target':closed({'server_id':TEXT,'session_id':TEXT,'channel_id':TEXT,'runtime_generation':{'type':'integer','minimum':0,'maximum':9007199254740991}}),
    'scope':{'const':'session'},'actions':{'type':'array','minItems':1,'maxItems':1,'items':closed({'publicationOwner':TEXT,'publicationToken':TEXT,
        'source':closed({'facet_id':TEXT,'item_id':TEXT,'contribution_version':TEXT}),
        'actionId':{'const':'acp.session.set-config-option'},'schemaVersion':{'const':'1'},
        'input':closed({'configId':{'enum':['model','thinkingLevel']},'value':TEXT}),'expectedObservation':TEXT})}}),
 'FrozenNativeRequest':closed({'schemaVersion':{'const':'agent-frozen-native-request/1'},'instanceRef':ref('Instance'),
    'endpointRef':ref('Endpoint'),'sessionId':S,'sourceRevision':S,'protocolId':{'const':'acp'},'purpose':{'enum':['apply','query']},
    'method':{'enum':['_ordessa/session/configuration/apply','_ordessa/session/configuration/operation']},'paramsBytes':{'type':'object'},'inputDigest':DIGEST}),
 'NativeOperationRef':closed({'schemaVersion':{'const':'agent-native-operation-ref/1'},'instanceRef':ref('Instance'),'requestKey':DIGEST,'agentOperationRef':S}),
 'NativeWriteBinding':closed({'schemaVersion':{'const':'agent-native-write-binding/1'},'operationRef':ref('NativeOperationRef'),
    'request':ref('FrozenNativeRequest'),'frameDigest':DIGEST,'endpointRequestId':DIGEST}),
 'NativeOperationReceipt':closed({'schemaVersion':{'const':'agent-native-operation-receipt/1'},'binding':ref('NativeWriteBinding'),
    'state':{'enum':['reserved','possibly-written','completed','failed','unknown']},'revision':{'type':'integer','minimum':1},
    'endpointOperationRef':{'anyOf':[S,{'type':'null'}]},'observationBytes':{'type':'object'},'observationDigest':DIGEST})}
DEFS['FrozenNativeRequest']['allOf']=[{'if':{'properties':{'purpose':{'const':'apply'}}},
 'then':{'properties':{'method':{'const':'_ordessa/session/configuration/apply'},'paramsBytes':PARAMS}},
 'else':{'properties':{'method':{'const':'_ordessa/session/configuration/operation'},
 'paramsBytes':closed({'sessionId':TEXT,'operationId':{'type':'string','minLength':1,'maxLength':128}})}}}]


def native_contract_schema(kind='NativeOperationReceipt'):
    if kind not in ('FrozenNativeRequest','NativeOperationRef','NativeWriteBinding','NativeOperationReceipt'):raise ValueError('unknown native contract')
    return deepcopy({'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:ordessa:agent-native-contracts:1',
        '$ref':'#/$defs/'+kind,'$defs':DEFS})
