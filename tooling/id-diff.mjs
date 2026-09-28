// T024 (FR-012 / SC-005) per-ID ledger gate: re-derive every test ID this lane
// inherited, and diff it name-by-name against the T003 freeze in
// specs/010-platform-core/reports/C-baseline/*.ids.txt. Frozen IDs may only be
// KEPT or MOVED (a move names the file it landed in); a frozen ID that is
// neither is an unexplained loss and exits 1. IDs the lane ADDED are reported
// per file so the report can claim "去向完整" without hand-counting. The
// current full universe is written to --out as the next freeze candidate for
// T025. Run: node tooling/id-diff.mjs
import { execFile } from 'node:child_process'
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'

const run = promisify(execFile)
const repoRoot = path.resolve(import.meta.dirname, '..')
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`)
  return i === -1 ? fallback : process.argv[i + 1]
}
const freezeDir = path.resolve(repoRoot, arg('freeze', 'specs/010-platform-core/reports/C-baseline'))
const outDir = path.resolve(repoRoot, arg('out', '/tmp/ordessa-id-ledger'))
const FROZEN_FILES = ['desktop.ids.txt', 'workbench.ids.txt', 'native-bridge.ids.txt', 'acp-connector.ids.txt']

const tmp = await mkdtemp(path.join(os.tmpdir(), 'ordessa-id-diff-'))

// --- current universe ------------------------------------------------------
// Every vitest suite the root aggregate knows about, plus the product's
// node --test guards, plus the ACP rig. Suite discovery goes through
// test-all.mjs --list so this gate cannot drift away from what `npm test` runs.
const { stdout: listOut } = await run(process.execPath, [path.join(repoRoot, 'tooling/test-all.mjs'), '--list'], { cwd: repoRoot })
const suites = listOut.split('\n').map(line => {
  const [label, ...command] = line.trim().split(/\s+/)
  if (!label) return null
  if (label.startsWith('workspace:') || label.startsWith('rig:')) {
    return { kind: 'vitest', label, root: label.replace(/^(workspace|rig):/, '') }
  }
  // The node-test label names the package, but its IDs live in the directory
  // the aggregator actually points `node --test` at — take it from the command.
  if (label.startsWith('node-test:')) {
    const target = command[command.indexOf('--test') + 1]
    if (!target) throw new Error(`${label}: cannot tell which directory the guard suite runs`)
    return { kind: 'node-test', label, root: target.replace(/\/$/, '') }
  }
  return null
}).filter(Boolean)
if (suites.length < 4) throw new Error(`only ${suites.length} ID-bearing suites discovered — fix this tool, do not let it pass thin`)

/** @type {{file: string, name: string, status: string}[]} */
const current = []
for (const suite of suites) {
  const absRoot = path.join(repoRoot, suite.root)
  if (suite.kind === 'vitest') {
    const json = path.join(tmp, `${suite.label.replace(/[^a-z0-9]+/gi, '_')}.json`)
    await run('npx', ['vitest', 'run', '--root', absRoot, '--maxWorkers=1', '--reporter=json', `--outputFile=${json}`],
      { cwd: repoRoot, maxBuffer: 64 * 1024 * 1024 }).catch(() => null)
    if (!existsSync(json)) throw new Error(`${suite.label}: no JSON report — the suite did not run to completion`)
    const report = JSON.parse(await readFile(json, 'utf8'))
    const before = current.length
    for (const file of report.testResults ?? []) {
      const rel = path.relative(repoRoot, file.name).split(path.sep).join('/')
      for (const assertion of file.assertionResults ?? []) {
        current.push({ file: rel, name: assertion.fullName ?? assertion.title, status: assertion.status })
      }
    }
    if (current.length === before) throw new Error(`${suite.label}: 0 IDs in its own JSON report — fix this tool, do not under-count silently`)
  } else {
    const files = (await readdir(absRoot)).filter(f => f.endsWith('.test.mjs')).sort()
    if (files.length === 0) throw new Error(`${suite.label}: no guard files in ${suite.root} — this gate would under-count`)
    for (const entry of files) {
      const before = current.length
      const { stdout = '' } = await run(process.execPath, ['--test', '--test-reporter=tap', path.join(absRoot, entry)],
        { cwd: repoRoot, maxBuffer: 64 * 1024 * 1024 }).catch(error => error)
      // Top-level TAP results only (nested subtests are indented).
      for (const line of stdout.split('\n')) {
        const pass = /^ok \d+ - (.+)$/.exec(line)
        if (pass) { current.push({ file: `${suite.root}/${entry}`, name: pass[1].trim(), status: 'passed' }); continue }
        const fail = /^not ok \d+ - (.+)$/.exec(line)
        if (fail) current.push({ file: `${suite.root}/${entry}`, name: fail[1].trim(), status: 'failed' })
      }
      if (current.length === before) throw new Error(`${suite.label}: no IDs parsed from ${entry} — a reporter/format change would silently under-count; fix this tool`)
    }
  }
  process.stdout.write(`. ${suite.label}\n`)
}
await rm(tmp, { recursive: true, force: true })

// --- diff vs the freeze ----------------------------------------------------
const universe = new Map() // name -> [{file, status}]
for (const entry of current) {
  if (!universe.has(entry.name)) universe.set(entry.name, [])
  universe.get(entry.name).push(entry)
}

const kept = [], moved = [], missing = [], failing = []
for (const frozenFile of FROZEN_FILES) {
  const lines = (await readFile(path.join(freezeDir, frozenFile), 'utf8')).split('\n').filter(Boolean)
  for (const line of lines) {
    const [, file, name] = line.split('|')
    const sites = universe.get(name) ?? []
    const same = sites.find(s => s.file === file)
    const other = sites.find(s => s.file !== file)
    if (same) { kept.push(`${frozenFile}: ${name}`); if (same.status !== 'passed') failing.push(`${file} :: ${name} (${same.status})`) }
    else if (other) { moved.push(`${frozenFile}: ${file}  ->  ${other.file}  ::  ${name}`); if (other.status !== 'passed') failing.push(`${other.file} :: ${name} (${other.status})`) }
    else missing.push(`${frozenFile}: ${file} :: ${name}`)
  }
}

const frozenNames = new Set()
let frozenCount = 0
for (const frozenFile of FROZEN_FILES) {
  const lines = (await readFile(path.join(freezeDir, frozenFile), 'utf8')).split('\n').filter(Boolean)
  frozenCount += lines.length
  for (const line of lines) frozenNames.add(line.split('|')[2])
}
const addedByFile = new Map()
for (const entry of current) {
  if (!frozenNames.has(entry.name)) addedByFile.set(entry.file, (addedByFile.get(entry.file) ?? 0) + 1)
}
const addedCount = [...addedByFile.values()].reduce((a, b) => a + b, 0)

await mkdir(outDir, { recursive: true })
const ledger = current.map(e => `${e.status === 'passed' ? 'P' : e.status === 'failed' ? 'F' : 'S'}|${e.file}|${e.name}`).sort()
await writeFile(path.join(outDir, 'post-lane.ids.txt'), ledger.join('\n') + '\n')

console.log(`\nfrozen IDs: ${frozenCount}   current IDs: ${current.length}`)
console.log(`kept in place: ${kept.length}   moved (same name, new file): ${moved.length}   MISSING: ${missing.length}`)
console.log(`added since the freeze: ${addedCount}`)
if (moved.length) { console.log('\n--- moves (frozen group: old file -> new file :: ID) ---'); for (const m of moved) console.log('  ' + m) }
if (missing.length) { console.log('\n--- UNEXPLAINED LOSSES (frozen ID no longer runs anywhere) ---'); for (const m of missing) console.log('  ' + m) }
if (failing.length) { console.log('\n--- frozen IDs NOT passing ---'); for (const f of failing) console.log('  ' + f) }
console.log('\n--- added IDs per file ---')
for (const [file, count] of [...addedByFile.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))) console.log(`  ${String(count).padStart(3)}  ${file}`)
console.log(`\ncurrent ledger written: ${path.relative(repoRoot, outDir)}/post-lane.ids.txt`)
process.exitCode = missing.length || failing.length ? 1 : 0
