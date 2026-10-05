import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export function loadSnapshot(root) {
  const files = {};
  function walk(dir) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isSymbolicLink()) throw new Error('symlink in material tree');
      if (e.isDirectory()) walk(p);
      else if (/\.(md|json|mjs|txt|xml)$/.test(e.name)) files[path.relative(root, p).split(path.sep).join('/')] = fs.readFileSync(p, 'utf8');
    }
  }
  walk(root);
  return files;
}

export function validate(files) {
  const errors = [];
  let m;
  try { m = JSON.parse(files['manifest.json']); } catch { return { errors: ['missing or invalid manifest'], stats: {} }; }
  const required = ['README.md','spec.md','architecture.md','data-model.md','contracts/public-api.md',
    'contracts/ordessa-read-seams.md','research.md','plan.md','tasks.md','acceptance.md','review.md',
    'status.md','prompt.md','quickstart.md','checks/validate-materials.mjs','checks/validate-materials.test.mjs'];
  for (const f of required) if (!files[f] || !files[f].trim()) errors.push('missing file: ' + f);
  for (const f of m.requiredFiles ?? []) if (!files[f] || !files[f].trim()) errors.push('manifest required file missing: ' + f);
  if (m.implementationAuthorized !== false) errors.push('design package must not claim implementation authorization');
  const mods = m.modules ?? [], tasks = m.tasks ?? [], ac = m.acceptance ?? [];
  if (mods.length !== 6 || new Set(mods.map(x=>x.id)).size !== 6) errors.push('six unique modules required');
  for (const mod of mods) if (!files[mod.document]) errors.push('missing module: ' + mod.id);
  if (tasks.length !== 10 || new Set(tasks.map(x=>x.id)).size !== 10) errors.push('ten unique tasks required');
  if (ac.length !== 68 || new Set(ac.map(x=>x.id)).size !== 68) errors.push('68 unique acceptance IDs required');
  const taskIds = new Set(tasks.map(x=>x.id)), acIds = new Set(ac.map(x=>x.id)), modIds = new Set(mods.map(x=>x.id));
  const rows = [...(files['acceptance.md'] ?? '').matchAll(/^\| (T\d{2}) \| ([^\n]+)$/gm)];
  if (rows.length !== 68 || new Set(rows.map(x=>x[1])).size !== 68) errors.push('acceptance matrix count/duplicates');
  for (const row of rows) {
    const cells = row[2].split('|').map(x=>x.trim()).filter(Boolean);
    if (cells.length !== 4) errors.push('acceptance assertion/counterexample/absent cells missing: ' + row[1]);
    if (!acIds.has(row[1])) errors.push('unregistered acceptance ID: ' + row[1]);
  }
  const coverage = new Set();
  for (const t of tasks) {
    if (!(files['tasks.md'] ?? '').includes('## ' + t.id + ' ·')) errors.push('task body missing: ' + t.id);
    if (t.state !== 'NOT_RUN') errors.push('design task not NOT_RUN: ' + t.id);
    for (const d of t.dependsOn ?? []) if (!taskIds.has(d)) errors.push('unknown dependency: ' + d);
    for (const mm of t.modules ?? []) if (!modIds.has(mm)) errors.push('unknown module: ' + mm);
    for (const a of t.acceptance ?? []) {
      if (!acIds.has(a)) errors.push('unknown acceptance ref: ' + a);
      coverage.add(a);
    }
    if (!(t.acceptance ?? []).length) errors.push('task without acceptance: ' + t.id);
    if (!(files['tasks.md'] ?? '').includes(t.id + '-G1')) errors.push('task gate missing: ' + t.id);
  }
  for (const a of ac) {
    if (!coverage.has(a.id)) errors.push('acceptance uncovered: ' + a.id);
    if (a.state !== 'NOT_RUN') errors.push('acceptance not NOT_RUN: ' + a.id);
    if (!modIds.has(a.module)) errors.push('acceptance owner unknown: ' + a.id);
  }
  const visiting = new Set(), visited = new Set(), byId = new Map(tasks.map(x=>[x.id,x]));
  function visit(id) {
    if (visiting.has(id)) { errors.push('dependency cycle: ' + id); return; }
    if (visited.has(id)) return;
    visiting.add(id);
    for (const dep of byId.get(id)?.dependsOn ?? []) if (byId.has(dep)) visit(dep);
    visiting.delete(id); visited.add(id);
  }
  for (const t of tasks) visit(t.id);
  for (let i=1; i<=14; i++) {
    const id = 'R' + String(i).padStart(2,'0');
    if (!(files['spec.md'] ?? '').includes('| ' + id + ' |')) errors.push('requirement missing: ' + id);
    const refs = m.requirements?.[id];
    if (!Array.isArray(refs) || !refs.length || refs.some(a=>!acIds.has(a))) errors.push('requirement trace invalid: ' + id);
  }
  for (const [f, body] of Object.entries(files)) {
    if (!f.endsWith('.md')) continue;
    for (const link of body.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)) {
      let href = link[1].split('#')[0];
      if (!href || /^(https?:|mailto:|\/)/.test(href)) continue;
      const target = path.posix.normalize(path.posix.join(path.posix.dirname(f), href));
      if (!files[target]) errors.push('broken link: ' + f + ' -> ' + target);
    }
    if (/YOUR_TOKEN|<填写|TODO_IMPLEMENT|API_KEY\s*=\s*["'][^"']+["']/.test(body)) errors.push('placeholder/credential example: ' + f);
  }
  return { errors, stats: { modules: mods.length, tasks: tasks.length, acceptance: ac.length,
    requirements: 14, markdownFiles: Object.keys(files).filter(x=>x.endsWith('.md')).length } };
}

const here = fileURLToPath(import.meta.url);
if (process.argv[1] && path.resolve(process.argv[1]) === here) {
  try {
    const root = path.resolve(process.argv[2] ?? path.join(path.dirname(here), '..'));
    const result = validate(loadSnapshot(root));
    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
    process.exitCode = result.errors.length ? 1 : 0;
  } catch (e) { process.stderr.write(String(e.message) + '\n'); process.exitCode = 1; }
}
