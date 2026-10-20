import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readdir, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

import { discoveredWorkspaceSuites, main, missingRequiredRoots, packageDirs, selectSuites } from '../checks/test-all.mjs'

const repoRoot = path.resolve(process.env.ORDESSA_REPO_ROOT ?? path.resolve(import.meta.dirname, '../..'))

async function fixture(t) {
  const cache = path.join(repoRoot, '.nightly-cache/js-aggregate-caller/control-fixtures')
  await mkdir(cache, { recursive: true })
  const rootDir = await mkdtemp(path.join(cache, 'ordessa-test-all-'))
  t.after(() => rm(rootDir, { recursive: true, force: true }))
  return rootDir
}

async function addPackage(rootDir, rel, scripts = {}) {
  const dir = path.join(rootDir, rel)
  await mkdir(dir, { recursive: true })
  await writeFile(path.join(dir, 'package.json'), JSON.stringify({ name: rel, scripts }))
}

test('package discovery skips node_modules, design source, and worktree build inputs', async t => {
  const rootDir = await fixture(t)
  await addPackage(rootDir, 'apps/desktop', { test: 'node --test' })
  await addPackage(rootDir, 'packages/interfaces/channels/workbench/ui', { test: 'node --test' })
  await addPackage(rootDir, 'docs/implementation/nightly/design-source/examples', { test: 'node --test' })
  await addPackage(rootDir, 'worktree/checkout/packages/generated', { test: 'node --test' })
  await addPackage(rootDir, 'apps/desktop/node_modules/fixture-dependency', { test: 'node --test' })

  assert.deepEqual(new Set(await packageDirs(rootDir)), new Set([
    'apps/desktop',
    'packages/interfaces/channels/workbench/ui',
  ]))
})

test('workspace suite discovery uses the supplied fixture root and package scripts', async t => {
  const rootDir = await fixture(t)
  await writeFile(path.join(rootDir, 'package.json'), JSON.stringify({
    workspaces: ['apps/*', 'packages/**', 'docs/**', 'worktree/**', '!packages/private/**'],
  }))
  await addPackage(rootDir, 'apps/desktop', { test: 'node --test' })
  await addPackage(rootDir, 'packages/interfaces/channels/workbench/ui', { test: 'vitest run' })
  await addPackage(rootDir, 'packages/no-tests')
  await addPackage(rootDir, 'packages/private/hidden', { test: 'node --test' })
  await addPackage(rootDir, 'docs/design-source/fixture', { test: 'node --test' })
  await addPackage(rootDir, 'worktree/generated/fixture', { test: 'node --test' })

  assert.deepEqual(await discoveredWorkspaceSuites(rootDir), [
    { name: 'workspace:apps/desktop', command: ['npm', 'run', '--workspace', 'apps/desktop', 'test'] },
    { name: 'workspace:packages/interfaces/channels/workbench/ui', command: ['npm', 'run', '--workspace', 'packages/interfaces/channels/workbench/ui', 'test'] },
  ])
})

test('required suite roots fail closed when a moved suite is absent', async t => {
  const rootDir = await fixture(t)
  const required = [{ name: 'node-test:tests/integration/harness/access', probes: [
    'tests/integration/harness/access',
    'tests/integration/harness/access/acp_passthrough_target.test.mjs',
  ] }]

  assert.deepEqual(await missingRequiredRoots(rootDir, required), [
    'node-test:tests/integration/harness/access → tests/integration/harness/access',
    'node-test:tests/integration/harness/access → tests/integration/harness/access/acp_passthrough_target.test.mjs',
  ])

  await mkdir(path.join(rootDir, required[0].probes[0]), { recursive: true })
  await mkdir(path.dirname(path.join(rootDir, required[0].probes[1])), { recursive: true })
  await writeFile(path.join(rootDir, required[0].probes[1]), '')
  assert.deepEqual(await missingRequiredRoots(rootDir, required), [])
})

test('suite filter never removes inventory before the full inventory check', () => {
  const suites = [
    { name: 'workspace:agents', command: ['npm', 'run', '--workspace', 'agents', 'test'] },
    { name: 'node-test:tooling', command: ['node', '--test', 'tooling/tests/**/*.test.mjs'] },
  ]
  assert.deepEqual(selectSuites(suites, 'agents'), [suites[0]])
  assert.deepEqual(selectSuites(suites, 'no-such-suite'), [])
})

test('unknown aggregate options fail closed before discovery or launch', async t => {
  const rootDir = await fixture(t)
  await assert.rejects(main({ rootDir, argv: ['--unreviewed-option'] }), /unsupported aggregate option/)
})

test('--list prints inventory without creating a run directory', async t => {
  const rootDir = repoRoot
  const cacheRoot = path.join(rootDir, '.nightly-cache/js-aggregate-caller/runs')
  const before = await readdir(cacheRoot).catch(() => [])
  const originalLog = console.log
  const lines = []
  console.log = (...args) => lines.push(args.join(' '))
  try { await main({ rootDir, argv: ['--list'] }) }
  finally { console.log = originalLog }
  const after = await readdir(cacheRoot).catch(() => [])
  assert.deepEqual(after, before)
  assert.equal(lines.at(-1), '53 suites')
})
