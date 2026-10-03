import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const walk = dir => fs.readdirSync(dir, {withFileTypes:true}).flatMap(e => e.isDirectory()?walk(path.join(dir,e.name)):[path.join(dir,e.name)]);
const snapshot = Object.fromEntries(walk(root).filter(f=>/\.(md|json)$/.test(f)).map(f=>[path.relative(root,f),fs.readFileSync(f,'utf8')]));
function validate(files) {
 const errors=[]; const requireFile=p=>{if(!(p in files))errors.push('missing:'+p);return files[p]??'';};
 for(const p of ['README.md','spec.md','architecture.md','decisions.md','data-model.md','research.md','plan.md','migration.md','migration-map.md','charter.md','quickstart.md','status.md','acceptance.md','contracts/environment.md','contracts/frontend.md','contracts/submission.md','contracts/recovery.md','contracts/lifecycle-evidence.md','contracts/shipping.md'])requireFile(p);
 let reg;
 try { reg=JSON.parse(requireFile('task-registry.json')); } catch {return ['registry-invalid',...errors];}
 if(reg.orders?.length!==12)errors.push('order-count');
 const orderIds=new Set(),taskIds=new Set();
 for(const o of reg.orders??[]) {
  if(orderIds.has(o.id))errors.push('duplicate-order:'+o.id);orderIds.add(o.id);
  const body=requireFile(o.file);
  let frontDeps=[];
  try {frontDeps=JSON.parse(body.match(/^depends_on: (.*)$/m)?.[1]??'null');if(!Array.isArray(frontDeps))throw Error();}catch{errors.push('front-dependencies:'+o.id);}
  if(Array.isArray(frontDeps)){
   if(JSON.stringify(frontDeps.map(d=>d.order))!==JSON.stringify(o.dependsOn))errors.push('dependency-projection:'+o.id);
   if(frontDeps.some(d=>!d.condition?.includes('codeReady')))errors.push('dependency-grade:'+o.id);
  }
  const gateRows=body.split('\n').filter(l=>l.startsWith('| G'+o.id+'-'));
  if(gateRows.length!==4||gateRows.some(l=>{const cols=l.split('|').slice(1,-1);return cols.length!==4||cols.some(c=>!c.trim());}))errors.push('gate-cells:'+o.id);
  for(const h of ['Objective','Current state','Scope','Requirements','Stages','Parallel units','Gates','Validation','DoD','Acceptance','Batch report'])if(!body.includes('## '+h))errors.push('section:'+o.id+':'+h);
  if(!body.includes('#### Scenario:')||!body.includes('**WHEN**')||!body.includes('**THEN**'))errors.push('scenario:'+o.id);
  if(!body.includes('parallelism: "none"')&&!body.includes('parallel_units:'))errors.push('parallelism:'+o.id);
  for(const id of o.taskIds)if(!body.includes(id))errors.push('missing-order-task:'+id);
  if(!body.includes('| G'+o.id+'-1')||!body.includes('Counter-example')||!body.includes('Absent / unknown'))errors.push('gates:'+o.id);
 }
 const visiting=new Set(),done=new Set(),map=new Map(reg.orders.map(o=>[o.id,o]));
 function visit(id){if(visiting.has(id)){errors.push('cycle:'+id);return;}if(done.has(id))return;visiting.add(id);for(const dep of map.get(id)?.dependsOn??[]){if(!map.has(dep))errors.push('unknown-dependency:'+dep);else visit(dep);}visiting.delete(id);done.add(id);}
 for(const id of orderIds)visit(id);
 const tasks=requireFile('tasks.md');
 for(const t of reg.tasks??[]){
  if(taskIds.has(t.id))errors.push('duplicate-task:'+t.id);taskIds.add(t.id);
  if(!map.get(t.order)?.taskIds.includes(t.id))errors.push('orphan-task:'+t.id);
  if(!tasks.includes('- [ ] '+t.id+' ')&&!tasks.includes('- [x] '+t.id+' '))errors.push('task-projection:'+t.id);
  if(!tasks.includes(t.description)||!requireFile(map.get(t.order)?.file??'unknown').includes(t.description))errors.push('task-description:'+t.id);
 }
 for(const o of reg.orders)for(const id of o.taskIds)if(!taskIds.has(id))errors.push('unknown-task:'+id);
 const ac=requireFile('acceptance.md');
 const caseReg=JSON.parse(requireFile('case-registry.json'));
 if(caseReg.cases.length!==111)errors.push('case-count');
 const caseIds=new Set();
 for(const c of caseReg.cases){if(caseIds.has(c.id))errors.push('duplicate-case:'+c.id);caseIds.add(c.id);if(!ac.includes('| '+c.id+' |'))errors.push('missing-case:'+c.id);if(!orderIds.has(c.order))errors.push('case-order:'+c.id);}
 const infra=requireFile('contracts/frontend-infrastructure.md');
 requireFile('frontend-infrastructure-update.md');
 for(const h of ['状态容器和选择订阅','后端投影和普通查询','异步任务和取消','编辑会话、表单和设置','UI保存和恢复','公共交互、上下文和显示','插入当前队列'])if(!infra.includes(h))errors.push('infra-section:'+h);
 for(const id of ['008','010','012'])if(!requireFile('orders/'+id+'.md').includes('contracts/frontend-infrastructure.md'))errors.push('infra-assignment:'+id);
 for(let n=96;n<=111;n++)if(!caseIds.has('A'+n))errors.push('infra-case:A'+n);
 for(const id of ["T008-11","T008-12","T008-13","T008-14","T008-15","T008-16","T008-17","T008-18","T008-19","T008-20","T010-12","T010-13","T010-14","T012-12","T012-13"])if(!taskIds.has(id))errors.push('infra-task:'+id);
 const approved=requireFile('decisions.md');
 if(!approved.includes('M14'))errors.push('infra-decision');
 for(const id of ['M04 / D4','M05 / D5','M06 / D6'])if(!approved.includes(id))errors.push('decision:'+id);
 if(!requireFile('architecture.md').includes('workbench/'))errors.push('workbench-target');
 const relationships=requireFile('contracts/relationships.md');
 for(const heading of ['一个核心','发布、发现与绑定','单写者','快照与订阅','三种作用域','前端协作','实施分配'])if(!relationships.includes(heading))errors.push('relationship-section:'+heading);
 for(const p of ['contracts/environment.md','contracts/frontend.md',...['002','003','004','006','007','008','009','010','012'].map(id=>'orders/'+id+'.md')])if(!requireFile(p).includes('relationships.md'))errors.push('relationship-link:'+p);
 if(!approved.includes('M10'))errors.push('relationship-decision');
 for(const p of ['plugin-architecture.md','contracts/platform-services.md','contracts/resource-references.md','contracts/agent-domain.md'])requireFile(p);
 if(!approved.includes('M11'))errors.push('plugin-design-decision');
 if(!requireFile('architecture.md').includes('plugin-architecture.md')||requireFile('architecture.md').includes('现有领域路径保留，不顺手扁平化'))errors.push('plugin-layout-conflict');
 for(const id of ['002','004','005','006','007','008','009','010','012'])if(!requireFile('orders/'+id+'.md').includes('platform-services.md'))errors.push('supplement-order:'+id);
 for(const id of ['T002-09','T002-10','T004-08','T005-10','T005-11','T005-12','T006-09','T007-10','T007-11','T007-12','T008-09','T008-10','T009-08','T009-09','T010-10','T010-11','T012-10','T012-11'])if(!taskIds.has(id))errors.push('supplement-task:'+id);
 if(reg.tasks.length!==129)errors.push('task-count');
 for(let n=76;n<=95;n++)if(!caseIds.has('A'+n))errors.push('supplement-case:A'+n);
 const detail=requireFile('execution-detail.md');
 for(let n=1;n<=18;n++){const id='R'+String(n).padStart(2,'0');if(!requireFile('spec.md').includes('### Requirement: '+id+' ')||!detail.includes('| '+id+' '))errors.push('requirement-trace:'+id);}
 for(const o of reg.orders)if(!requireFile(o.file).includes('execution-detail.md'))errors.push('execution-detail-link:'+o.id);
 if(!map.get('005')?.dependsOn.includes('004'))errors.push('persistence-reference-dependency');
 if(requireFile('orders/001.md').includes('001来源与002合同成立'))errors.push('baseline-future-gate');
 if(requireFile('migration-map.md').includes('foundation内HarnessAvailability | plugins/agent/contracts'))errors.push('availability-wrong-owner');
 for(const c of caseReg.cases){const row=ac.split('\n').find(l=>l.startsWith('| '+c.id+' |'));if(!row)continue;const cols=row.split('|').slice(1,-1).map(s=>s.trim());if(cols[1]!==c.order||cols[5]!==c.level||c.required!==true)errors.push('case-projection:'+c.id);}
 try{const q=JSON.parse(requireFile('queue.json'));if(q.single_executor!==true||JSON.stringify(q.orders)!==JSON.stringify(reg.orders.map(o=>o.id))||!q.shared_paths?.length)errors.push('queue-projection');for(const o of reg.orders)for(const dep of o.dependsOn)if(q.orders.indexOf(dep)>=q.orders.indexOf(o.id))errors.push('queue-dependency:'+o.id);}catch{errors.push('queue-invalid');}
 return [...new Set(errors)];
}
const errors=validate(snapshot);
assert.deepEqual(errors,[],errors.join('\n'));
const mutations=[
 ['missing contract', f=>{delete f['contracts/submission.md'];}],
 ['missing predecessor', f=>{const r=JSON.parse(f['task-registry.json']);r.orders[1].dependsOn=['999'];f['task-registry.json']=JSON.stringify(r);}],
 ['cycle', f=>{const r=JSON.parse(f['task-registry.json']);r.orders[0].dependsOn=['012'];f['task-registry.json']=JSON.stringify(r);}],
 ['duplicate task', f=>{const r=JSON.parse(f['task-registry.json']);r.tasks.push(r.tasks[0]);f['task-registry.json']=JSON.stringify(r);}],
 ['missing case', f=>{f['acceptance.md']=f['acceptance.md'].replace('| A48 |','| BAD |');}],
 ['missing task projection', f=>{f['tasks.md']=f['tasks.md'].replace('- [ ] T001-01 ','- [ ] BAD ').replace('- [x] T001-01 ','- [x] BAD ');}],
 ['missing relationship contract', f=>{delete f['contracts/relationships.md'];}],
 ['missing relationship case', f=>{f['acceptance.md']=f['acceptance.md'].replace('| A68 |','| BAD |');}],
 ['missing implementation assignment', f=>{f['orders/004.md']=f['orders/004.md'].replace('relationships.md','removed.md');}],
 ['missing platform contract', f=>{delete f['contracts/platform-services.md'];}],
 ['missing references contract', f=>{delete f['contracts/resource-references.md'];}],
 ['missing agent contract', f=>{delete f['contracts/agent-domain.md'];}],
 ['missing plugin design', f=>{delete f['plugin-architecture.md'];}],
 ['old plugin layout conflict', f=>{f['architecture.md']+='\n现有领域路径保留，不顺手扁平化';}],
 ['missing supplement task', f=>{const r=JSON.parse(f['task-registry.json']);r.tasks=r.tasks.filter(t=>t.id!=='T005-11');f['task-registry.json']=JSON.stringify(r);}],
 ['missing supplement acceptance', f=>{f['acceptance.md']=f['acceptance.md'].replace('| A80 |','| BAD |');}],
 ['missing execution detail', f=>{delete f['execution-detail.md'];}],
 ['missing top requirement', f=>{f['spec.md']=f['spec.md'].replace('### Requirement: R14 ','### Requirement: BAD ');}],
 ['baseline future gate', f=>{f['orders/001.md']+='\n001来源与002合同成立';}],
 ['wrong availability owner', f=>{f['migration-map.md']+='\nfoundation内HarnessAvailability | plugins/agent/contracts';}],
 ['case weakened', f=>{const r=JSON.parse(f['case-registry.json']);r.cases[0].required=false;f['case-registry.json']=JSON.stringify(r);}],
 ['case level drift', f=>{const r=JSON.parse(f['case-registry.json']);r.cases[0].level='P';f['case-registry.json']=JSON.stringify(r);}],
 ['missing frontend infrastructure', f=>{delete f['contracts/frontend-infrastructure.md'];}],
 ['missing infrastructure handoff', f=>{delete f['frontend-infrastructure-update.md'];}],
 ['missing infrastructure section', f=>{f['contracts/frontend-infrastructure.md']=f['contracts/frontend-infrastructure.md'].replace('状态容器和选择订阅','BAD');}],
 ['missing infrastructure assignment', f=>{f['orders/008.md']=f['orders/008.md'].replaceAll('contracts/frontend-infrastructure.md','BAD');}],
 ['missing infrastructure task', f=>{const r=JSON.parse(f['task-registry.json']);r.tasks=r.tasks.filter(t=>t.id!=='T008-12');f['task-registry.json']=JSON.stringify(r);}],
 ['missing infrastructure case', f=>{f['acceptance.md']=f['acceptance.md'].replace('| A96 |','| BAD |');}],
 ['missing infrastructure ruling', f=>{f['decisions.md']=f['decisions.md'].replaceAll('M14','BAD');}],
 ['queue reordered', f=>{const r=JSON.parse(f['queue.json']);r.orders.reverse();f['queue.json']=JSON.stringify(r);}]
];
for(const [name,mutate] of mutations){const copy={...snapshot};mutate(copy);assert.ok(validate(copy).length,'mutation not detected:'+name);}
console.log(JSON.stringify({kind:'design-structure-only',orders:12,tasks:JSON.parse(snapshot['task-registry.json']).tasks.length,acceptanceCases:JSON.parse(snapshot['case-registry.json']).cases.length,mutationsCaught:mutations.length,implementationTestsRun:false,status:'PASS'},null,2));
