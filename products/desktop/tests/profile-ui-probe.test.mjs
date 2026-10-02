import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { probeOptions } from '../probe-profile-ui.mjs'
import { sameSessionProfileReceipts, safeAlertDiagnostic } from '../probe-profile-ui-driver.mjs'

test('brand selection refuses accidental API inference and false evidence flags', () => {
  assert.equal(probeOptions([]).brand,'codex')
  for(const brand of ['pi','claude-code']) {
    assert.equal(probeOptions(['--brand='+brand]).allowModelCalls,false)
    assert.throws(()=>probeOptions(['--brand='+brand,'--allow-model-calls']),/absolute/)
    assert.throws(()=>probeOptions(['--brand='+brand,'--allow-model-calls','--key-file=relative']),/absolute/)
    assert.equal(probeOptions(['--brand='+brand,'--allow-model-calls','--key-file=/private/key.txt']).keyFile,'/private/key.txt')
  }
  assert.throws(()=>probeOptions(['--brand=unknown']),/Unsupported/)
  assert.throws(()=>probeOptions(['--during-output']),/require/)
  assert.equal(probeOptions(['--brand=pi','--allow-model-calls','--inventory-only','--key-file=/private/key.txt']).inventoryOnly,true)
  assert.throws(()=>probeOptions(['--allow-model-calls','--inventory-only','--during-output']),/Inventory-only/)
})

test('UI alert diagnostics emit only closed categories, never messages or credential fragments', () => {
  const secret='sensitive-example-key-DO_NOT_PRINT'
  assert.deepEqual(safeAlertDiagnostic({message:'Credential load: CREDENTIAL_UNRESOLVED '+secret,location:'chat'}),
    {code:'CREDENTIAL_UNRESOLVED',location:'chat'})
  assert.deepEqual(safeAlertDiagnostic({message:'Session list failed. Refresh to try again.',location:'sidebar'}),
    {code:'SESSION_CATALOG_FAILED',location:'sidebar'})
  assert.equal(safeAlertDiagnostic('连接已断开。正在运行的任务结果未知').code,'CONNECTION_DISCONNECTED')
  const diagnostic=safeAlertDiagnostic({message:secret,location:secret})
  assert.deepEqual(diagnostic,{code:'UNCLASSIFIED_UI_ALERT',location:'other'})
  assert.equal(JSON.stringify(diagnostic).includes(secret),false)
})

test('cleanup deletes only API-key locators read from the disposable database', async () => {
  const seed=fileURLToPath(new URL('../../server/scripts/seed-profile-ui-probe.py',import.meta.url))
  const privateRoot=await mkdtemp(tmpdir()+'/ordessa-profile-ui-')
  try {
    const result=execFileSync('python3',['-c',`
import runpy, sys, types, json, subprocess
deleted=[]
database=object()
class Records:
 def __init__(self, db): assert db is database
 def list(self): return [{'credentialId':'own','kind':'api-key'},{'credentialId':'other-kind','kind':'token'}]
 def get(self, cid, kind):
  assert cid=='own' and kind=='api-key'
  return {'secret_locator':'exact-own-locator'}
credentials=types.ModuleType('ordessa_server.credentials'); credentials.CredentialRecords=Records
sys.modules['ordessa_server.credentials']=credentials
runtime=types.SimpleNamespace(start=lambda:None,stop=lambda:None,database=database,
 secret_store=types.SimpleNamespace(delete=lambda locator:deleted.append(locator)))
module=types.ModuleType('ordessa_server_product.composition')
module.create_composition=lambda:types.SimpleNamespace(native_runtime=lambda *a,**k:runtime)
sys.modules['ordessa_server_product.composition']=module
subprocess.check_output=lambda *a,**k:json.dumps(['--native-adapter-command','adapter'])
seed,private=sys.argv[1:]
sys.argv=[seed,private,'--cleanup','--brand=pi']
try: runpy.run_path(seed,run_name='__main__')
except SystemExit as error: assert error.code==0
assert deleted==['exact-own-locator']
print('EXACT_CLEANUP_CHECKED')
`,seed,privateRoot],{encoding:'utf8'})
    assert.match(result,/EXACT_CLEANUP_CHECKED/)
  } finally { await rm(privateRoot,{recursive:true,force:true}) }
})

test('changed Profile receipt requires same session and matching selected brand', () => {
  for(const brand of ['codex','pi','claude-code']) {
    const receipts=[{profileId:'first',configDigest:'one',sessionRef:{sessionId:'s'}},
      {profileId:'second',configDigest:'two',sessionRef:{sessionId:'s'}}]
    assert.equal(sameSessionProfileReceipts(receipts,brand,brand+'::first',brand+'::second'),true)
    assert.equal(sameSessionProfileReceipts(receipts,brand,'wrong::first',brand+'::second'),false)
    assert.equal(sameSessionProfileReceipts([{...receipts[0]}, {...receipts[1],sessionRef:{sessionId:'other'}}],brand,brand+'::first',brand+'::second'),false)
    assert.equal(sameSessionProfileReceipts([{...receipts[0]}, {...receipts[1],configDigest:'one'}],brand,brand+'::first',brand+'::second'),false)
    assert.equal(sameSessionProfileReceipts([{...receipts[0],sessionRef:null}, {...receipts[1],sessionRef:null}],brand,brand+'::first',brand+'::second'),false)
  }
})

test('no-model seed creates two real-shaped presets without opening credential source or native channel', async () => {
  const seed=fileURLToPath(new URL('../../server/scripts/seed-profile-ui-probe.py',import.meta.url))
  for(const brand of ['codex','pi','claude-code']) {
    const privateRoot=await mkdtemp(tmpdir()+'/ordessa-profile-ui-')
    try {
      const result=execFileSync('python3',['-c',`
import runpy, sys, types, json, subprocess
calls=[]
class Wire:
 def dispatch(self, method, params):
  calls.append((method, params))
  if method=='workspaces.open': return {'workspace':{'id':'workspace'}}
  if method=='providerModels.create': return {'providerModel':{'id':'provider'}}
  if method=='profiles.v2.createProfile': return {'data':{'profileId':params['displayName']}}
  if method=='profiles.v2.saveProfile': return {'data':{}}
  raise AssertionError('Forbidden seed operation: '+method)
class Runtime:
 wire=Wire()
 def start(self): pass
 def stop(self): pass
runtime=Runtime()
module=types.ModuleType('ordessa_server_product.composition')
module.create_composition=lambda:types.SimpleNamespace(native_runtime=lambda *a,**k:runtime)
sys.modules['ordessa_server_product.composition']=module
subprocess.check_output=lambda *a,**k:json.dumps(['--native-adapter-command','adapter','--native-adapter-arg=entry'])
seed,private,brand=sys.argv[1:]
sys.argv=[seed,private,'--brand='+brand,'--key-file=/does-not-exist/key.txt']
runpy.run_path(seed,run_name='__main__')
providers=[p for m,p in calls if m=='providerModels.create']
assert providers[0]['credentialId'] is None
saves=[p for m,p in calls if m=='profiles.v2.saveProfile']
assert len(saves)==2 and all(p['patches'][0]['value']['harnessId']==brand for p in saves)
assert saves[0]['patches'][0]['value']['modelId']!=saves[1]['patches'][0]['value']['modelId']
print('NO_MODEL_SEED_CHECKED')
`,seed,privateRoot,brand],{encoding:'utf8'})
      assert.match(result,/NO_MODEL_SEED_CHECKED/)
    } finally { await rm(privateRoot,{recursive:true,force:true}) }
  }
})
