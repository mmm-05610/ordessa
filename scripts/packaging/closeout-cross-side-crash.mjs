#!/usr/bin/env node
// Five durable-boundary crash probes against extracted Electron and Python
// artifacts. External effects are supplied only by controlled_native_fixture.
import { spawn, spawnSync } from 'node:child_process'
import { access, copyFile, mkdtemp, mkdir, readFile, readdir, realpath, rm, stat, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const argv=process.argv.slice(2), opt=n=>{const i=argv.indexOf(n);return i<0?undefined:argv[i+1]}, assert=(v,m)=>{if(!v)throw Error(m)}
const within=(f,r)=>{const x=path.relative(r,f);return x===''||(!x.startsWith(`..${path.sep}`)&&x!=='..'&&!path.isAbsolute(x))}
async function checkTree(p,b,seen=new Set()){const x=await realpath(p);assert(within(x,b),`artifact path escapes prefix: ${x}`);if(seen.has(x))return;seen.add(x);if(!(await stat(x)).isDirectory())return;for(const e of await readdir(x)){const c=await realpath(path.join(x,e));assert(within(c,b),`artifact member escapes prefix: ${c}`);if((await stat(c)).isDirectory())await checkTree(c,b,seen)}}

const py=String.raw`import dataclasses,enum,importlib.util,json,os,sqlite3,sys,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
prefix,fixture,data,effects,barrier,boundary,phase=sys.argv[1:8]
prefix=Path(prefix).resolve(strict=True);fixture=Path(fixture).resolve(strict=True);data=Path(data);effects=Path(effects);barrier=Path(barrier)
sys.path.insert(0,str(fixture.parent));spec=importlib.util.spec_from_file_location('ordessa_closeout_controlled_fixture',fixture);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
native=m.ControlledNativeFixture(effects,mode='existing');comp=m.controlled_product_composition(native_submit_port=native,fingerprint_port=m.test_protected_fingerprint(),submission_policy=m.controlled_submission_policy());runtime=comp.default_runtime(data,include_profile=False);runtime.start()
if phase=='submit':
  resolved=runtime.wire.dispatch('agent.session.resolve',{'location':{'kind':'draft','connectionId':'cross-side-qa','draftId':'cross-side-crash-draft'}});target=resolved['target'];generation=resolved['generation'];native.bind_backend_target(target);scope=runtime.wire.dispatch('agent.submission.scope',{});conditions=runtime.wire.dispatch('agent.submission.capture.read',{'target':target,'mode':'existing'})
else:
  target=sys.argv[8];expected_namespace=sys.argv[9];native.bind_backend_target(target)
  resolved=runtime.wire.dispatch('agent.session.resolve',{'location':{'kind':'draft','connectionId':'cross-side-qa','draftId':'cross-side-crash-draft'}})
  if resolved['target']!=target:raise RuntimeError('cold product runtime resolved another target')
  generation=resolved['generation'];scope=runtime.wire.dispatch('agent.submission.scope',{})
  if scope['namespace']!=expected_namespace:raise RuntimeError('cold actor scope differs from original journal namespace')
  conditions=runtime.wire.dispatch('agent.submission.capture.read',{'target':target,'mode':'existing'})
product_roots=('ordessa_agent','ordessa_environment_api','ordessa_persistence_sqlite','ordessa_server_product','pacthold')
origins={}
for name,module in list(sys.modules.items()):
  if not any(name==root or name.startswith(root+'.') for root in product_roots):continue
  origin=getattr(module,'__file__',None)
  if origin:
    resolved_origin=Path(origin).resolve(strict=True)
    if not resolved_origin.is_relative_to(prefix):raise RuntimeError('product module escaped artifact Python prefix: '+name+' -> '+str(resolved_origin))
    origins[name]=str(resolved_origin)
required=('ordessa_agent.submission_service','ordessa_environment_api','ordessa_persistence_sqlite','ordessa_server_product.composition')
if any(name not in sys.modules for name in required):raise RuntimeError('actual packaged product modules were not imported')
def pause(stage):
  barrier.write_text(json.dumps({'stage':stage,'pid':os.getpid()}),encoding='utf8');print('CROSS_PY_BARRIER '+stage,flush=True)
  while True:time.sleep(30)
if phase=='submit' and boundary=='backend-intent':
  from ordessa_persistence_sqlite import SqliteStorePort
  old=SqliteStorePort.claim_dispatch
  def wrapped(self,*a,**k):
    v=old(self,*a,**k);pause('backend-intent');return v
  SqliteStorePort.claim_dispatch=wrapped
if phase=='submit' and boundary=='native-effect':
  old=m.ControlledNativeFixture.submit_existing
  def wrapped(self,*a,**k):
    v=old(self,*a,**k);pause('native-effect');return v
  m.ControlledNativeFixture.submit_existing=wrapped
if phase=='submit' and boundary=='domain-result':
  from ordessa_agent.submission_journal import SubmissionJournal
  old=SubmissionJournal.record_completed
  def wrapped(self,*a,**k):
    v=old(self,*a,**k);pause('domain-result');return v
  SubmissionJournal.record_completed=wrapped
calls=[]
def plain(v):
  if v is None or isinstance(v,(str,int,float,bool)):return v
  if isinstance(v,enum.Enum):return v.value
  if dataclasses.is_dataclass(v):return plain(dataclasses.asdict(v))
  if isinstance(v,dict):return {str(k):plain(x) for k,x in v.items()}
  if isinstance(v,(tuple,list)):return [plain(x) for x in v]
  f=getattr(v,'model_dump',None)
  if callable(f):return plain(f(mode='json'))
  if hasattr(v,'__dict__'):return plain(vars(v))
  return str(v)
def reply(h,n,v):
  b=json.dumps(v,separators=(',',':'),default=str).encode();h.send_response(n);h.send_header('Content-Type','application/json');h.send_header('Access-Control-Allow-Origin','*');h.send_header('Access-Control-Allow-Headers','content-type');h.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS');h.send_header('Content-Length',str(len(b)));h.end_headers();h.wfile.write(b)
class H(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def do_OPTIONS(self):reply(self,200,{})
  def do_GET(self):
    if self.path=='/setup':reply(self,200,{'target':target,'generation':generation,'conditions':conditions,'namespace':scope['namespace'],'moduleOrigins':origins});return
    if self.path=='/calls':reply(self,200,{'calls':calls});return
    if self.path=='/stats':reply(self,200,{'effectCounts':[{'key':list(k),'count':v} for k,v in native.all_effect_counts().items()]});return
    reply(self,404,{})
  def do_POST(self):
    try:
      b=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or b'{}');method=b['method'];params=b['params']
      if phase=='recover' and method!='agent.submission.query':raise RuntimeError('recovery is query-only')
      if method=='agent.submission.query' and (params.get('target')!=target or params.get('submissionId')!='cross-side-'+boundary):raise RuntimeError('query differs from original target/key')
      calls.append(method);reply(self,200,{'kind':'Accepted','result':plain(runtime.wire.dispatch(method,params))})
    except BaseException as e:reply(self,200,{'kind':'Refused','reason':type(e).__name__+': '+str(e),'code':getattr(e,'code',None)})
server=ThreadingHTTPServer(('127.0.0.1',0),H);server.daemon_threads=True
print('CROSS_PY_READY '+json.dumps({'port':server.server_address[1],'target':target,'generation':generation,'namespace':scope['namespace'],'moduleOrigins':origins}),flush=True)
try:server.serve_forever(poll_interval=.1)
finally:
  server.server_close()
  if runtime.started:runtime.stop()
`

function page({port,db,id,boundary,recovery,state,originalKey,originalTarget,originalGeneration}){
 const map={imports:{'@extensions/ordessa.agent-contracts/':'/agent/','@extensions/ordessa.contracts/':'/contracts/','@ordessa/extension-api':'/shared/api.js','@ordessa/ui-components/api':'/shared/ui-components-api.js'}}
 return `<!doctype html><meta charset=utf-8><script type=importmap>${JSON.stringify(map)}</script><script>window.__errs=[];window.__phase='importing';addEventListener('error',e=>__errs.push({kind:'error',message:e.message,filename:e.filename}));addEventListener('unhandledrejection',e=>__errs.push({kind:'rejection',reason:String(e.reason?.stack||e.reason)}))</script><script type=module>
import * as a from '@extensions/ordessa.agent-contracts/contract.js';const base='http://127.0.0.1:${port}',id=${JSON.stringify(id)},boundary=${JSON.stringify(boundary)},recovery=${recovery},state=${JSON.stringify(state)},db=${JSON.stringify(db)},originalKey=${JSON.stringify(originalKey)},originalTarget=${JSON.stringify(originalTarget)},originalGeneration=${JSON.stringify(originalGeneration)};
const get=async p=>{const r=await fetch(base+p);const v=await r.json();if(!r.ok)throw Error(JSON.stringify(v));return v},post=async(p,b)=>{const r=await fetch(base+p,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b)});return r.json()};
try{if(typeof a.createFrontendSubmissionJournal!=='function'||typeof a.createDurableSubmissionClient!=='function')throw Error('artifact public Agent exports missing');const setup=await get('/setup'),key=recovery?originalKey:{namespace:setup.namespace,principalScope:'local',requestId:id};const real=a.createFrontendSubmissionJournal({databaseName:db});
if(!recovery){const c=setup.conditions,cap={key,target:setup.target,guarantee:'reliable',generation:setup.generation,binding:{target:setup.target,generation:setup.generation,expectedConditions:c},inputSchema:'agent-input/v1',submissionMode:'existing',draft:{draftId:'cross-side-crash-draft',draftRevision:1,text:'controlled boundary request',attachmentIds:[],attachmentRefs:[]},configOperationIds:[]};
const journal=new Proxy(real,{get(t,p){if(p==='capture')return async(...args)=>{const v=await t.capture(...args);if(boundary==='frontend-mapping'){window.__barrier={state:'captured',requestId:id,key,target:setup.target,generation:setup.generation};await new Promise(()=>{})}return v};if(p==='markPossiblySubmitted')return async(...args)=>{const v=await t.markPossiblySubmitted(...args);if(boundary==='frontend-possibly-submitted'){window.__barrier={state:'possibly-submitted',requestId:id,key,target:setup.target,generation:setup.generation};await new Promise(()=>{})}return v};const v=Reflect.get(t,p,t);return typeof v==='function'?v.bind(t):v}});
const client=a.createDurableSubmissionClient({journal,wire:async(method,params)=>post('/dispatch',{method,params})});const answer=await client.submit(cap);window.__result={ok:true,answer};
}else{const rec=await real.get(key);if(!rec||rec.state!==state||rec.target!==originalTarget||rec.key.namespace!==originalKey.namespace||rec.key.principalScope!==originalKey.principalScope||rec.key.requestId!==originalKey.requestId||rec.generation!==originalGeneration)throw Error('cold IDB original key/target/generation/state mismatch');const client=a.createDurableSubmissionClient({journal:real,wire:async(method,params)=>post('/dispatch',{method,params})});const answer=await client.reconcile(key),after=await real.get(key),stats=await get('/stats'),calls=await get('/calls');if(after?.key.requestId!==originalKey.requestId||after.key.namespace!==originalKey.namespace||after.key.principalScope!==originalKey.principalScope||after.target!==originalTarget||after.generation!==originalGeneration)throw Error('cold query changed original identity');window.__result={ok:true,answer,stateBefore:rec.state,stateAfter:after.state,requestId:id,target:rec.target,generation:rec.generation,key:rec.key,stats,calls};}
}catch(e){window.__result={ok:false,phase:window.__phase,error:String(e.stack||e),rendererErrors:window.__errs}}</script>`
}
function mainSource({page,roots,userData}){return `const {app,BrowserWindow,protocol}=require('electron'),fs=require('node:fs/promises'),path=require('node:path');protocol.registerSchemesAsPrivileged([{scheme:'ordessa',privileges:{standard:true,secure:true,supportFetchAPI:true,corsEnabled:true}}]);app.setPath('userData',${JSON.stringify(userData)});const roots=${JSON.stringify(roots)},html=${JSON.stringify(page)};const send=async(b,r)=>{const p=path.resolve(b,r);if(p!==b&&!p.startsWith(b+path.sep))return new Response('denied',{status:403});try{return new Response(await fs.readFile(p),{headers:{'content-type':'text/javascript; charset=utf-8'}})}catch{return new Response('missing',{status:404})}};let done=false;const finish=x=>{if(done)return;done=true;console.log('CROSS_RESULT '+JSON.stringify(x));app.quit()};app.whenReady().then(async()=>{protocol.handle('ordessa',async r=>{const u=new URL(r.url);if(u.pathname==='/'||u.pathname==='/index.html')return new Response(html,{headers:{'content-type':'text/html'}});for(const [prefix,key] of [['/agent/','agent'],['/contracts/','contracts'],['/shared/','shared']])if(u.pathname.startsWith(prefix))return send(roots[key],decodeURIComponent(u.pathname.slice(prefix.length)));return new Response('denied',{status:403})});const w=new BrowserWindow({show:false,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true,backgroundThrottling:false}});const errors=[];w.webContents.on('console-message',(_e,d)=>{if(d?.level===2)errors.push({message:d.message,line:d.lineNumber})});w.webContents.on('render-process-gone',(_e,d)=>finish({ok:false,error:'renderer-gone',details:d,errors}));await w.loadURL('ordessa://desktop/');const end=Date.now()+30000;while(!done&&Date.now()<end){const s=await w.webContents.executeJavaScript('({barrier:window.__barrier||null,result:window.__result||null,errors:window.__errs||[]})').catch(e=>({error:String(e)}));if(s.barrier){console.log('CROSS_FRONT_BARRIER '+JSON.stringify(s.barrier));await new Promise(()=>{})}if(s.result){finish(s.result);return}if(s.errors?.length){finish({ok:false,error:'renderer errors',errors:s.errors,consoleErrors:errors});return}await new Promise(r=>setTimeout(r,20))}if(!done)finish({ok:false,error:'renderer deadline',consoleErrors:errors})}).catch(e=>finish({ok:false,error:String(e.stack||e)}));`}
function checkGeneratedJavaScript(filename,label){const result=spawnSync(process.execPath,['--check',filename],{encoding:'utf8'});assert(result.status===0,`${label} generated JavaScript syntax failed (status=${result.status}): ${result.stderr||result.stdout}`)}
function checkGeneratedPython(python,filename,environment,label){const result=spawnSync(python,['-I','-c',"import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())",filename],{encoding:'utf8',env:environment});assert(result.status===0,`${label} generated Python syntax failed (status=${result.status}): ${result.stderr||result.stdout}`)}
async function checkGeneratedPage(html,filename,label){const match=html.match(/<script type=module>\s*([\s\S]*?)<\/script>/);assert(match,`${label} generated renderer module is missing`);await writeFile(filename,match[1],{mode:0o600});checkGeneratedJavaScript(filename,label)}
class Proc{constructor(p,label){this.p=p;this.label=label;this.out='';this.waiters=[];this.ended=false;this.closed=new Promise(r=>p.once('close',(code,signal)=>{this.ended=true;r({code,signal})}));for(const s of [p.stdout,p.stderr])s.on('data',b=>{this.out+=b.toString();for(const w of [...this.waiters]){const l=this.out.split(/\r?\n/).find(x=>x.startsWith(w.prefix));if(l){this.waiters.splice(this.waiters.indexOf(w),1);w.resolve(l.slice(w.prefix.length))}}})}wait(prefix,ms=30000){const l=this.out.split(/\r?\n/).find(x=>x.startsWith(prefix));if(l)return Promise.resolve(l.slice(prefix.length));let timer;return Promise.race([new Promise((resolve,reject)=>{this.waiters.push({prefix,resolve});timer=setTimeout(()=>reject(Error(`${this.label} timeout ${prefix}: ${this.out.slice(-2500)}`)),ms)}),this.closed.then(x=>{throw Error(`${this.label} exited ${JSON.stringify(x)}: ${this.out.slice(-2500)}`)})]).finally(()=>clearTimeout(timer))}async kill(){if(this.ended)return this.closed;try{process.kill(-this.p.pid,'SIGKILL')}catch(e){if(e.code!=='ESRCH')throw e}return this.closed}}
const owned=[];const launch=(exe,args,cwd,env,label)=>{const p=new Proc(spawn(exe,args,{cwd,env,detached:process.platform!=='win32',stdio:['ignore','pipe','pipe']}),label);owned.push(p);return p}
const partial=[]
function env(home){const e={PATH:process.env.PATH||'',HOME:home,USERPROFILE:home,PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1'};for(const k of ['DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','LANG','LD_LIBRARY_PATH'])if(process.env[k])e[k]=process.env[k];delete e.PYTHONPATH;delete e.ELECTRON_RUN_AS_NODE;return e}

async function main(){
const input=opt('--artifact-root')||process.env.ORDESSA_ARTIFACT_ROOT;assert(input,'use --artifact-root <unpacked deb root>');assert(!argv.includes('--electron')&&!argv.includes('--python'),'external runtime overrides are rejected');
const root=await realpath(path.resolve(input)),prefix=await realpath(path.join(root,'opt/ordessa'));assert(within(prefix,root)&&path.basename(prefix)==='ordessa','artifact must contain canonical opt/ordessa');
const p={electron:await realpath(path.join(prefix,'app/electron')),python:await realpath(path.join(prefix,'python/bin/python3.12')),agent:await realpath(path.join(prefix,'app/dist/extensions/ordessa.agent-contracts')),chat:await realpath(path.join(prefix,'app/dist/extensions/ordessa.chat')),contracts:await realpath(path.join(prefix,'app/dist/extensions/ordessa.contracts')),shared:await realpath(path.join(prefix,'app/dist/renderer/shared'))};
for(const x of Object.values(p))assert(within(x,prefix),`outside artifact prefix ${x}`);for(const x of [p.agent,p.chat,p.contracts,p.shared])await checkTree(x,prefix);await access(path.join(p.agent,'contract.js'));await access(path.join(p.chat,'submission.js'));
const fixtureSource=await realpath(path.join(path.dirname(fileURLToPath(import.meta.url)),'controlled_native_fixture.py')),tmp=await mkdtemp(path.join(os.tmpdir(),'ordessa-cross-crash-')),report=partial;
try{for(const boundary of ['frontend-mapping','frontend-possibly-submitted','backend-intent','native-effect','domain-result']){const dir=path.join(tmp,boundary),data=path.join(dir,'data'),profile=path.join(dir,'user-data'),home=path.join(dir,'home'),effects=path.join(dir,'effects.sqlite'),barrier=path.join(dir,'barrier.json'),worker=path.join(dir,'worker.py'),fixture=path.join(dir,'controlled_native_fixture.py'),id='cross-side-'+boundary,state=boundary==='frontend-mapping'?'captured':'possibly-submitted',row={boundary,requestId:id,status:'started'};report.push(row);await Promise.all([mkdir(dir,{recursive:true,mode:0o700}),mkdir(profile,{recursive:true,mode:0o700}),mkdir(home,{recursive:true,mode:0o700})]);await copyFile(fixtureSource,fixture);await writeFile(worker,py,{mode:0o600});const e=env(home);checkGeneratedPython(p.python,worker,e,`${boundary} worker`);row.pythonSyntax='pass';let server=launch(p.python,['-I',worker,prefix,fixture,data,effects,barrier,boundary,'submit'],dir,e,`${boundary} Python`);const ready=JSON.parse(await server.wait('CROSS_PY_READY '));row.artifactOrigins=ready.moduleOrigins;row.target=ready.target;row.originalGeneration=ready.generation;row.namespace=ready.namespace;assert(ready.moduleOrigins&&Object.keys(ready.moduleOrigins).length>0,'artifact module provenance list missing');const originalKey={namespace:ready.namespace,principalScope:'local',requestId:id};const html=page({port:ready.port,db:`ordessa.cross.${boundary}`,id,boundary,recovery:false,state,originalKey,originalTarget:ready.target,originalGeneration:ready.generation});const main=path.join(dir,'main.cjs');await writeFile(main,mainSource({page:html,roots:{agent:p.agent,chat:p.chat,contracts:p.contracts,shared:p.shared},userData:profile}),{mode:0o600});await checkGeneratedPage(html,path.join(dir,'renderer-submit.mjs'),`${boundary} renderer submit`);checkGeneratedJavaScript(main,`${boundary} Electron main`);row.submitJavaScriptSyntax='pass';let browser=launch(p.electron,['--no-sandbox','--disable-gpu','--disable-dev-shm-usage',main],dir,e,`${boundary} Electron`);
if(boundary.startsWith('frontend-')){const b=JSON.parse(await browser.wait('CROSS_FRONT_BARRIER '));assert(b.state===state&&b.key?.namespace===originalKey.namespace&&b.key?.principalScope===originalKey.principalScope&&b.key?.requestId===originalKey.requestId&&b.target===ready.target&&b.generation===ready.generation,`wrong frontend stage/identity ${JSON.stringify(b)}`);row.frontendBarrier=b}else{const until=Date.now()+30000;let marker;while(Date.now()<until){try{marker=JSON.parse(await readFile(barrier,'utf8'));break}catch{}await new Promise(r=>setTimeout(r,25))}assert(marker?.stage===boundary,`backend durable barrier absent: ${JSON.stringify(marker)}`);row.backendBarrier=marker}
const [bk,sk]=await Promise.all([browser.kill(),server.kill()]);assert(bk.signal==='SIGKILL'&&sk.signal==='SIGKILL',`both owner processes must receive SIGKILL: ${JSON.stringify([bk,sk])}`);
server=launch(p.python,['-I',worker,prefix,fixture,data,effects,barrier,boundary,'recover',ready.target,ready.namespace],dir,e,`${boundary} cold Python`);const coldReady=JSON.parse(await server.wait('CROSS_PY_READY '));assert(coldReady.target===ready.target&&coldReady.namespace===originalKey.namespace,'cold product target or actor scope changed');row.coldArtifactOrigins=coldReady.moduleOrigins;row.coldRuntimeGeneration=coldReady.generation;row.generationComparison={original:ready.generation,coldRuntime:coldReady.generation,journalQueryMustUse:ready.generation};const coldHtml=page({port:coldReady.port,db:`ordessa.cross.${boundary}`,id,boundary,recovery:true,state,originalKey,originalTarget:ready.target,originalGeneration:ready.generation});const coldMain=path.join(dir,'cold.cjs');await writeFile(coldMain,mainSource({page:coldHtml,roots:{agent:p.agent,contracts:p.contracts,shared:p.shared},userData:profile}),{mode:0o600});await checkGeneratedPage(coldHtml,path.join(dir,'renderer-recovery.mjs'),`${boundary} renderer recovery`);checkGeneratedJavaScript(coldMain,`${boundary} cold Electron main`);row.recoveryJavaScriptSyntax='pass';browser=launch(p.electron,['--no-sandbox','--disable-gpu','--disable-dev-shm-usage',coldMain],dir,e,`${boundary} cold Electron`);const result=JSON.parse(await browser.wait('CROSS_RESULT '));const exit=await browser.closed;row.coldResult=result;assert(exit.code===0&&result.ok,`${boundary} recovery failed ${JSON.stringify(result)}`);const expectedOutcome=boundary==='native-effect'||boundary==='domain-result'?'accepted':'unknown',expectedEffects=expectedOutcome==='accepted'?1:0;assert(result.answer?.status===expectedOutcome,`${boundary} unexpected recovery outcome: ${JSON.stringify(result.answer)}`);assert(result.calls?.calls?.length===1&&result.calls.calls[0]==='agent.submission.query',`${boundary} recovery was not exactly one query: ${JSON.stringify(result.calls)}`);assert(result.key?.namespace===originalKey.namespace&&result.key?.principalScope===originalKey.principalScope&&result.key?.requestId===originalKey.requestId&&result.target===ready.target&&result.generation===ready.generation,'cold browser did not use the original durable identity and captured generation');const effectRows=result.stats?.effectCounts||[];assert(effectRows.reduce((n,x)=>n+x.count,0)===expectedEffects&&effectRows.every(x=>x.key[0]===originalKey.namespace&&x.key[1]===originalKey.principalScope&&x.key[2]===originalKey.requestId&&x.count===1),`${boundary} native effect namespace/principal/request/count mismatch: ${JSON.stringify(effectRows)}`);await server.kill();row.killSignals=[bk.signal,sk.signal];row.expectedOutcome=expectedOutcome;row.expectedNativeEffects=expectedEffects;row.status='pass';row.sandbox='unproven; Electron launched with --no-sandbox'}}
finally{for(const p of owned)await p.kill().catch(()=>undefined);await rm(tmp,{recursive:true,force:true})}console.log(JSON.stringify({schema:'ordessa.closeout-cross-side-crash.v1',artifactPrefix:prefix,productRuntimeFromArtifact:true,pythonIsolation:{interpreter:p.python,flag:'-I',pythonpath:'unset',home:'isolated temporary directory'},qaFixture:'copied controlled_native_fixture.py in each owned temporary case directory (test seam only)',stages:report,controlledSeams:['SQLite-backed controlled native submit','test-only HMAC fingerprint fixture','explicit local test policy','loopback HTTP QA bridge'],notExercised:['real Harness behavior','real model','system install','user data','Chromium sandbox'],status:'pass'},null,2))}
main().catch(e=>{console.log(JSON.stringify({schema:'ordessa.closeout-cross-side-crash.v1',status:'fail',completedAndPartialStages:partial,error:String(e.stack||e)}));process.exitCode=1})
