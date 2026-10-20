"""Read-only validation of design assets; not an Ordessa runtime implementation."""
from pathlib import Path
import json,hashlib
from decimal import Decimal
import yaml
from jsonschema import Draft202012Validator
REPO_ROOT=Path(__file__).resolve().parents[3]
R=REPO_ROOT/'methods'/'incremental-engineering'
checks=0

def assert_(condition,message):
 global checks
 checks+=1
 if not condition: raise AssertionError(message)
def pairs(items):
 d={}
 for k,v in items:
  if k in d:raise ValueError('Duplicate key: '+k)
  d[k]=v
 return d
class StrictLoader(yaml.SafeLoader):pass
def mapping(loader,node,deep=False):return pairs([(loader.construct_object(k,deep=deep),loader.construct_object(v,deep=deep)) for k,v in node.value])
StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
def read(p):
 text=(R/p).read_text()
 return json.loads(text,object_pairs_hook=pairs) if p.endswith('.json') else yaml.load(text,Loader=StrictLoader)
def canon(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def hash_(v,domain):return hashlib.sha256(('ordessa/'+domain+'/v1\n').encode()+canon(v)).hexdigest()
def raw(p):return hashlib.sha256((R/p).read_bytes()).hexdigest()
def walk(v):
 yield v
 if isinstance(v,dict):
  for child in v.values():yield from walk(child)
 elif isinstance(v,list):
  for child in v:yield from walk(child)

parsed={str(p.relative_to(R)):read(str(p.relative_to(R))) for p in R.rglob('*') if p.suffix in ['.json','.yaml']}
manifest=read('method.yaml');catalog=read('contracts/capability-catalog.json');lock=read('bundle-lock.json')
resources={r['id']:r for r in manifest['resources']}
assert_(len(resources)==len(manifest['resources']),'Duplicate resource ID')
assert_(len({r['path'] for r in resources.values()})==len(resources),'Duplicate resource path')
for id,r in resources.items():
 p=Path(r['path']);assert_(not p.is_absolute() and '..' not in p.parts,'Escaping path')
 assert_(raw(r['path'])==r['sha256'],'Digest mismatch: '+id)
assert_(lock['manifest_sha256']==raw('method.yaml'),'Manifest hash mismatch')
assert_(lock['host_catalog_sha256']==raw('contracts/capability-catalog.json'),'Catalog hash mismatch')
assert_(hash_(read(lock['compiled_plan_path']),'compiled-method-program')==lock['compiled_plan_digest']['hex'],'Compiled program digest mismatch')
assert_(lock['snapshot_payload']['compiled_plan_digest']==lock['compiled_plan_digest'],'Frozen compiled program not bound')
mutated_program=read(lock['compiled_plan_path']);mutated_program['workflow']['entry']='accepted'
assert_(hash_(mutated_program,'compiled-method-program')!=lock['compiled_plan_digest']['hex'],'Compiled program mutation undetected')
assert_(hash_(lock['snapshot_payload'],'method-snapshot')==lock['method_ref']['snapshot_digest']['hex'],'Snapshot mismatch')
assert_(lock['snapshot_payload']['manifest_sha256']==raw('method.yaml'),'Snapshot manifest mismatch')
assert_(lock['snapshot_payload']['required_capabilities']==manifest['requires'],'Snapshot capabilities mismatch')
assert_(lock['snapshot_payload']['resource_digests']==[{'id':r['id'],'sha256':r['sha256']} for r in manifest['resources']],'Snapshot resources mismatch')
capabilities={x['capability_id']:x for x in catalog['capabilities']}
assert_(len(capabilities)==len(catalog['capabilities']),'Duplicate capability')
for req in manifest['requires']:
 c=capabilities[req['capability_id']]
 assert_(hash_(c['contract'],'capability-contract')==c['contract_digest'],'Catalog contract mismatch')
 assert_(all(req[k]==c[k] for k in req),'Required capability mismatch')
for path,v in parsed.items():
 if path.startswith(('workflows/','standards/','decisions/')) or path=='method.yaml':
  for x in walk(v):
   if isinstance(x,dict) and 'resource' in x:assert_(x['resource'] in resources,'Unknown resource in '+path)
criteria={}
for id,r in resources.items():
 if r['kind']=='standard':
  std=read(r['path'])
  for c in std['criteria']:
   assert_((id,c['criterion_id']) not in criteria,'Duplicate criterion')
   criteria[(id,c['criterion_id'])]=c
   assert_(c['policy']['unknown']!='pass','Unknown cannot pass')
   for check in c['checks']:assert_(capabilities[check['capability_id']]['kind']=='check','Bad check kind')
for id,r in resources.items():
 if r['kind']=='question_set':
  qset=read(r['path']);qids=set()
  for x in walk(qset):
   if isinstance(x,dict):assert_(not any(k in x for k in ['threshold','decision_policy','minimum_selected_probability','minimum_expected_index','maximum_p_true']),'Threshold duplicated outside standard')
  for q in qset['questions']:
   assert_(q['question_id'] not in qids,'Duplicate question');qids.add(q['question_id'])
   for cr in q['criterion_refs']:assert_((cr['resource'],cr['criterion_id']) in criteria,'Unknown criterion')
   cr=q['answer_definition']['from_criterion'];c=criteria[(cr['resource'],cr['criterion_id'])]
   assert_(q['kind']==c['answer_vocabulary']['kind'],'Question vocabulary type mismatch')
flow=read('workflows/change-cycle.yaml');steps={s['id']:s for s in flow['steps']};edges={id:set() for id in steps}
assert_(len(steps)==len(flow['steps']),'Duplicate step')
for id,s in steps.items():
 if s['kind']=='operation':
  c=capabilities[s['operation']];assert_(c['kind']=='operation','Not operation')
  assert_(set(s['outcomes'])==set(c['contract']['workflow_outcomes']),'Missing outcome '+id)
  for t in s['outcomes'].values():
   assert_(len(t)==1,'Ambiguous transition')
   if 'next' in t:edges[id].add(t['next'])
   if 'wait' in t:assert_(t['wait'] in flow['wait_kinds'],'Unknown wait')
   if 'stop' in t:assert_(t['stop'] in flow['stop_outcomes'],'Unknown stop')
 elif s['kind']=='wait':edges[id].add(s['next'])
 else:assert_(s['kind']=='stop','Unsupported step')
 for target in edges[id]:assert_(target in steps,'Missing transition target')
seen=set();pending=[flow['entry']]
while pending:
 n=pending.pop()
 if n not in seen:seen.add(n);pending.extend(edges[n])
assert_(seen==set(steps),'Unreachable step')
visiting=set();visited=set()
def acyclic(node):
 assert_(node not in visiting,'Unsupported workflow cycle')
 if node in visited:return
 visiting.add(node)
 for target in edges[node]:acyclic(target)
 visiting.remove(node);visited.add(node)
acyclic(flow['entry'])
for name in ['did','implementation-package','submission']:
 schema=read('documents/'+name+'/schema.json');Draft202012Validator.check_schema(schema)
 Draft202012Validator(schema).validate(read('examples/minimal-change/'+name+'.json'));checks+=1
for envelope in read('examples/minimal-change/method-content-envelopes.json')['method_contents']:
 schema_ref=envelope['schema_ref'];assert_(schema_ref['method_ref']==lock['method_ref'],'MethodContent method mismatch')
 resource=resources[schema_ref['resource_id']];assert_(schema_ref['resource_digest']['hex']==resource['sha256'],'MethodContent schema digest mismatch')
 Draft202012Validator(read(resource['path'])).validate(envelope['value']);checks+=1
refs=read('examples/minimal-change/fixture-refs.json');known=set()
for value in refs['records'].values():
 x=dict(value);digest=x.pop('digest');assert_(hash_(x,'fixture-record')==digest,'Fixture digest mismatch');known.add(digest)
for x in walk(refs):
 if isinstance(x,dict) and x.get('realm_id')=='realm-fixture' and 'id' in x:assert_(x['digest'] in known,'Unresolved fixture ref')
assert_(refs['method_ref']==lock['method_ref'],'Fixture method mismatch')
for inv in read('examples/minimal-change/decision-invocations.json')['invocations']:
 req,res=inv['request'],inv['result']
 assert_(req['invocation_id'] is None or req['invocation_id']==res['invocation_id'],'Invocation mismatch')
 assert_(hash_(inv['input_snapshot'],'decision-input')==req['input_ref']['digest'],'Input digest mismatch')
 assert_(req['input_ref']['digest']==res['input_receipt']['input_ref']['digest'],'Receipt mismatch')
 assert_(set(q['identity']['question_id'] for q in req['questions'])==set(res['answers']),'Answer coverage mismatch')
 assert_(hash_(inv['question_set_snapshot'],'decision-question-set')==req['question_set_ref']['digest'],'Resolved question set digest mismatch')
 assert_(hash_(req,'decision-request')==res['input_receipt']['request_digest'],'Request digest mismatch')
 mapping=res['input_receipt']['provider_question_mapping'];assert_(set(mapping)==set(res['answers']) and len(set(mapping.values()))==len(mapping),'Provider question mapping not bijective')
 for cr in req['state']['resolved_criteria']:assert_(set(cr)=={'criterion_ref','statement','answer_vocabulary','evidence_requirements'},'Threshold or policy leaked into model criteria')
 for q in req['questions']:
  q0=json.loads(json.dumps(q));digest=q0['identity'].pop('digest');assert_(hash_(q0,'decision-question')==digest,'Question digest mismatch')
  wrapper=res['answers'][q['identity']['question_id']];assert_(wrapper['question_identity']==q['identity'],'Answer identity mismatch');a=wrapper['answer'];assert_(q['kind']==a['kind'],'Wrong answer type')
  assert_('rationale' not in a,'Free-text answer disallowed')
  if a['kind'] in ['choice','score']:
   p={k:Decimal(str(v)) for k,v in a['probabilities'].items()}
   assert_(all(Decimal(0)<=v<=Decimal(1) for v in p.values()),'Probability out of range')
   assert_(sum(p.values())==Decimal(1),'Probabilities not normalized')
   if a['kind']=='choice':assert_(set(p)==set(x['option_id'] for x in q['options']) and a['selected_option_id'] in p,'Bad choice options')
   else:
    assert_(set(p)==set(x['level_id'] for x in q['levels']),'Bad score levels')
    assert_(sum(Decimal(x['index'])*p[x['level_id']] for x in q['levels'])==Decimal(str(a['expected_index'])),'Score expectation mismatch')
  else:assert_(Decimal(0)<=Decimal(str(a['p_true']))<=Decimal(1),'Invalid Noul p_true')
golden=read('contracts/hash-golden.json')
assert_(bytes.fromhex(golden['prefix_utf8_hex'])==b'ordessa/method-snapshot/v1\n','Hash prefix mismatch')
assert_(bytes.fromhex(golden['canonical_utf8_hex'])==canon(golden['canonical_payload']),'Canonical golden mismatch')
assert_(hashlib.sha256(bytes.fromhex(golden['complete_input_hex'])).hexdigest()==golden['expected_sha256'],'Golden hash mismatch')
fixture_lock=R/'fixture-lock.json'
assert_(fixture_lock.is_file(),'Fixture lock absent')
for entry in read('fixture-lock.json')['files']:
 if 'repository_path' in entry:
  repository_path=Path(entry['repository_path'])
  assert_(not repository_path.is_absolute() and '..' not in repository_path.parts,'Escaping repository path: '+entry['path'])
  resolved=(REPO_ROOT/repository_path).resolve()
  assert_(REPO_ROOT.resolve() in resolved.parents,'Repository path escapes repository: '+entry['path'])
  assert_(resolved.is_file(),'Missing repository file: '+entry['path'])
  actual=hashlib.sha256(resolved.read_bytes()).hexdigest()
 else:
  actual=raw(entry['path'])
 assert_(actual==entry['sha256'],'Fixture lock mismatch '+entry['path'])
print(json.dumps({'status':'passed','static_assertions':checks,'parsed_json_yaml_files':len(parsed),'authoritative_resources':len(resources),'domain_runtime_tests':'not_run','harness_integration':'not_run','real_model_evaluation':'not_run','trusted_human_approval':'not_run'},ensure_ascii=False))
