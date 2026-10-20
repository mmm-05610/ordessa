"""Seed two fixed Profile revisions through the current authenticated registry.

No runtime/service/channel is started. Native model resources and credentials
must already be represented by the caller's validated Profile content. This
probe never imports keys, deletes credentials, or claims native application.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys
from ordessa_system_access_client import (CapabilityClient,ClientError,load_service,parse_json,
    profile_ref_valid,MAX_BYTES)


def _entry_valid(entry, namespace):
    required = {'profileId', 'catalogRevision', 'displayName', 'archivedAt', 'currentManifestRef'}
    if type(entry) is not dict or set(entry) != required:
        return False
    ref = entry['currentManifestRef']
    return (type(entry['profileId']) is str and bool(entry['profileId'])
            and type(entry['catalogRevision']) is int and entry['catalogRevision'] > 0
            and type(entry['displayName']) is str and bool(entry['displayName'])
            and (entry['archivedAt'] is None or type(entry['archivedAt']) is str)
            and profile_ref_valid(ref)
            and ref['environmentNamespace'] == namespace
            and ref['profileId'] == entry['profileId'])


def _content(path,namespace):
    raw=Path(path).read_bytes()
    if len(raw)>MAX_BYTES:raise ValueError('Profile content exceeds bound')
    value=parse_json(raw)
    if (type(value) is not dict or value.get('schemaVersion')!='1'
            or type(value.get('harnessDefinitionRef')) is not dict
            or value['harnessDefinitionRef'].get('environmentNamespace')!=namespace
            or type(value.get('declarations')) is not list):
        raise ValueError('explicit current Profile content required')
    return value


def seed(client,*,namespace,first,next_content,request_prefix):
    if (type(namespace) is not str or not namespace.startswith('ordessa-profile-ui-')
            or not re.fullmatch(r'[a-z][a-z0-9._-]{0,63}',namespace) or type(request_prefix) is not str or not re.fullmatch(r'[a-z][a-z0-9._-]{0,49}',request_prefix)):
        raise ValueError('explicit disposable namespace and stable request prefix required')
    capabilities=client.profile_capabilities(request_prefix+'-capabilities','profiles.create')
    if capabilities['environmentNamespace']!=namespace:
        raise ValueError('Profile namespace differs from explicit disposable scope')
    outputs=[]
    for suffix,content in (('current',first),('next',next_content)):
        value=client.invoke('profiles.create',{'profileId':'ui-'+suffix,'displayName':'UI '+suffix+' probe',
            'manifest':content},request_prefix+'-'+suffix)
        if value['status']!='completed':return {'status':value['status'],'completedProfiles':len(outputs),'modelCalls':0}
        entry=value['data']
        if not _entry_valid(entry, namespace) or entry['profileId']!='ui-'+suffix:
            raise ClientError('OUTCOME_UNKNOWN','Exact created Profile identity unavailable',6)
        canonical=json.dumps(content,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode()
        if entry['currentManifestRef']['contentDigest']!='sha256:'+hashlib.sha256(canonical).hexdigest():
            raise ClientError('OUTCOME_UNKNOWN','Created Profile content digest mismatch',6)
        outputs.append(entry['currentManifestRef'])
    return {'status':'completed','profileCount':2,'profileRefs':outputs,'modelCalls':0,
        'credentialImported':False,'nativeApplied':'unobserved'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for option in ('config','service','namespace','first-content','next-content','request-prefix'):
        parser.add_argument('--'+option,required=True)
    args=parser.parse_args(argv)
    try:
        first=_content(args.first_content,args.namespace);second=_content(args.next_content,args.namespace)
        client=CapabilityClient(load_service(args.config,args.service))
        result=seed(client,namespace=args.namespace,first=first,next_content=second,request_prefix=args.request_prefix)
        print(json.dumps(result,ensure_ascii=False));return 0 if result['status']=='completed' else 2
    except (ValueError,OSError,ClientError):
        print('PROFILE_UI_SEED_REFUSED',file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
