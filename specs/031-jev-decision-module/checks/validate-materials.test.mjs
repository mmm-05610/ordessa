import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadSnapshot, validate } from './validate-materials.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const original = loadSnapshot(root);
assert.deepEqual(validate(original).errors, []);
const failures = [
  ['missing module', f=>{ delete f['modules/M02-runtime.md']; }],
  ['missing acceptance row', f=>{ f['acceptance.md'] = f['acceptance.md'].replace(/^\| T65 \|.*\n/m, ''); }],
  ['missing counterexample cells', f=>{ f['acceptance.md'] = f['acceptance.md'].replace(/^\| T01 \|.*$/m, '| T01 | M01 | codec |'); }],
  ['dependency cycle', f=>{ const m=JSON.parse(f['manifest.json']); m.tasks[0].dependsOn=['JD009']; f['manifest.json']=JSON.stringify(m); }],
  ['broken link', f=>{ f['README.md']+='\n[bad](missing.md)\n'; }],
  ['false execution claim', f=>{ const m=JSON.parse(f['manifest.json']); m.acceptance[0].state='DONE'; f['manifest.json']=JSON.stringify(m); }],
  ['missing trace', f=>{ const m=JSON.parse(f['manifest.json']); delete m.requirements.R06; f['manifest.json']=JSON.stringify(m); }],
  ['missing manifest', f=>{ delete f['manifest.json']; }],
];
for (const [name, mutate] of failures) {
  const f={...original}; mutate(f);
  assert.ok(validate(f).errors.length, 'guard failed to detect: '+name);
}
process.stdout.write('material guard: baseline + '+failures.length+' injected counterexamples passed; not product tests\n');

