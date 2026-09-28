// T021: the root JS test entry really aggregates every JS suite of this repo instead of
// pointing at one package. Every suite runs even after a failure and keeps its own exit
// code; workspace packages that carry a `test` script are discovered and must all appear;
// the non-workspace roots are presence-checked; prerequisites (typecheck, real builds)
// run first because the Electron gates read built output. Nothing here starts the real
// Server, calls a real model, or touches run data — the gates drive fake/loopback peers.
import { spawn } from 'node:child_process'
import { access, readdir, readFile } from 'node:fs/promises'
import path from 'node:path'

const repoRoot = path.resolve(import.meta.dirname, '..')

function patternToRegExp(pattern) {
  const source = pattern
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')
    .replace(/\*\*/g, '\u0001')
    .replace(/\*/g, '[^/]+')
    .replace(/\u0001/g, '.*')
  return new RegExp(`^${source}$`)
}

async function packageDirs(current = repoRoot, acc = []) {
  for (const entry of await readdir(current, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name === 'node_modules' || entry.name === 'dist' || entry.name.startsWith('.')) continue
    const dir = path.join(current, entry.name)
    const rel = path.relative(repoRoot, dir).split(path.sep).join('/')
    if (await exists(path.join(dir, 'package.json'))) acc.push(rel)
    await packageDirs(dir, acc)
  }
  return acc
}

const exists = dir => access(dir).then(() => true, () => false)

/** Every workspace package that declares its own `test` script. */
async function discoveredWorkspaceSuites() {
  const patterns = JSON.parse(await readFile(path.join(repoRoot, 'package.json'), 'utf8')).workspaces ?? []
  const include = patterns.filter(p => !p.startsWith('!')).map(patternToRegExp)
  const exclude = patterns.filter(p => p.startsWith('!')).map(p => patternToRegExp(p.slice(1)))
  const found = []
  for (const rel of await packageDirs()) {
    if (!include.some(re => re.test(rel)) || exclude.some(re => re.test(rel))) continue
    const pkg = JSON.parse(await readFile(path.join(repoRoot, rel, 'package.json'), 'utf8'))
    if (pkg.scripts?.test) found.push({ name: `workspace:${rel}`, command: ['npm', 'run', '--workspace', rel, 'test'] })
  }
  return found.sort((a, b) => a.name.localeCompare(b.name))
}

const PREREQUISITES = [
  { name: 'typecheck', command: ['npm', 'run', 'typecheck'] },
  { name: 'build:examples', command: ['npm', 'run', 'build:examples'] },
  { name: 'build:foundations', command: ['npm', 'run', 'build:foundations'] },
  { name: 'build:app', command: ['npm', 'run', 'build'] },
]

// Roots that are not npm workspaces with a test script: the product guard and the ACP
// rig (its own package.json + lockfile). Presence-checked below so a moved suite fails
// loudly instead of dropping out of the aggregate.
const EXTRA_ROOTS = [
  { name: 'node-test:products/desktop', probe: 'products/desktop/tests', command: ['node', '--test', 'products/desktop/tests/'] },
  { name: 'rig:tests/integration/acp-connector', probe: 'tests/integration/acp-connector', command: ['npx', 'vitest', 'run', '--root', 'tests/integration/acp-connector'] },
]

const ELECTRON_GATES = ['test:electron', 'test:extensions', 'test:agent-ui', 'test:agent-shell', 'test:ui-service', 'test:ui-foundations', 'test:ui-preview']
  .map(name => ({ name: `electron:${name}`, command: ['npm', 'run', name] }))

const run = command => new Promise(resolve => {
  const child = spawn(command[0], command.slice(1), { cwd: repoRoot, stdio: 'inherit' })
  child.on('close', code => resolve(code ?? 1))
})

const filter = process.argv.slice(2).find(arg => !arg.startsWith('-'))
const workspaces = await discoveredWorkspaceSuites()
if (workspaces.length < 4) throw Error(`discovered only ${workspaces.length} workspace test suites — the pattern matcher or the ` +
  'workspace `test` scripts regressed, and an empty aggregate would pass vacuously')

const missing = []
for (const suite of EXTRA_ROOTS) if (!await exists(path.join(repoRoot, suite.probe))) missing.push(`${suite.name} → ${suite.probe}`)
if (missing.length) throw Error(`aggregated roots are gone (a moved suite must be re-declared, not dropped): ${missing.join(', ')}`)

const suites = [...PREREQUISITES, ...workspaces, ...EXTRA_ROOTS, ...ELECTRON_GATES]
  .filter(suite => !filter || suite.name.includes(filter))
if (!suites.length) throw Error(`no suite matches filter ${JSON.stringify(filter)} — nothing was verified`)

// `--list` prints what would run without running it, so the aggregate itself can be
// audited (which suites are covered) without paying for a full gate cycle.
if (process.argv.includes('--list')) {
  console.log(suites.map(s => `${s.name}  ${s.command.join(' ')}`).join('\n'))
  console.log(`${suites.length} suites`)
  process.exit(0)
}

const results = []
for (const suite of suites) {
  const started = Date.now()
  console.log(`\n\u001b[1m▶ ${suite.name}\u001b[0m ${suite.command.join(' ')}`)
  const code = await run(suite.command)
  results.push({ ...suite, code, seconds: ((Date.now() - started) / 1000).toFixed(1) })
}

console.log('\n===== root JS aggregation summary =====')
for (const r of results) console.log(`${r.code === 0 ? 'PASS' : 'FAIL'} exit=${r.code} ${r.seconds.padStart(7)}s  ${r.name}`)
const failed = results.filter(r => r.code !== 0)
console.log(`\n${results.length - failed.length}/${results.length} suites green`)
if (failed.length) {
  console.log(`Failed: ${failed.map(f => `${f.name} (exit ${f.code})`).join(', ')}`)
  process.exitCode = 1
}
