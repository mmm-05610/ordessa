/**
 * T008-09 gate: every logical plugin manifest matches the schema frozen at
 * 002, stays a BUILD-TIME catalog (never a scheduler), and keeps its
 * identity aligned with the runtime manifests (products/extensions.json is
 * still the selection/scheduling authority).
 */
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs'
import path from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { validateLogicalManifest } from '../../../tooling/validate-logical-manifest.mjs'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

function discover(dir) {
  const found = []
  const stack = [dir]
  while (stack.length > 0) {
    const current = stack.pop()
    for (const name of readdirSync(current)) {
      if (['node_modules', 'dist', '.git', 'build'].includes(name)) continue
      const entry = path.join(current, name)
      if (existsSync(entry) && statSync(entry).isDirectory()) stack.push(entry)
      else if (name === 'plugin.manifest.json') found.push(entry)
    }
  }
  return found.sort()
}

const manifests = [
  ...discover(path.join(repoRoot, 'packages/frontend')),
  ...discover(path.join(repoRoot, 'packages/backend')),
  ...discover(path.join(repoRoot, 'plugins')),
]

test('logical manifests exist for the moved frontend packages and validate', () => {
  assert.ok(manifests.length >= 10, `only ${manifests.length} manifests found — the frontend set must carry them`)
  for (const file of manifests) {
    const label = path.relative(repoRoot, file)
    const manifest = JSON.parse(readFileSync(file, 'utf8'))
    const errors = validateLogicalManifest(manifest, label)
    assert.deepEqual(errors, [], `manifest ${label} failed validation`)
  }
})

test('counterexample: a manifest that behaves like a scheduler is refused', () => {
  const errors = validateLogicalManifest({
    schemaVersion: 1,
    logicalPluginId: 'demo.plugin',
    displayName: 'demo',
    categories: ['platform'],
    versionSource: 'package.json',
    artifacts: [],
    entries: [],
    enable: true,       // forbidden: a catalog never enables itself
    startup: 'boot()',  // forbidden: no startup functions
  }, 'synthetic')
  assert.ok(errors.some(e => e.includes("forbidden key 'enable'")))
  assert.ok(errors.some(e => e.includes("forbidden key 'startup'")))
})

test('counterexample: malformed identity or unknown schema version is refused', () => {
  const errors = validateLogicalManifest({
    schemaVersion: 2,
    logicalPluginId: 'BAD',
    displayName: '',
    categories: ['nonsense'],
    versionSource: '',
    artifacts: [{ kind: 'binary', path: '' }],
    entries: [{ entryId: '', entrypoint: '', executionDomain: 'kernel' }],
  }, 'synthetic')
  assert.ok(errors.some(e => e.includes('schemaVersion must be 1')))
  assert.ok(errors.some(e => e.includes('logicalPluginId is malformed')))
  assert.ok(errors.some(e => e.includes('categories')))
  assert.ok(errors.some(e => e.includes('executionDomain')))
})

test('logical identity agrees with the runtime extension identity', () => {
  const enabled = JSON.parse(
    readFileSync(path.join(repoRoot, 'products/desktop/extensions.json'), 'utf8'))
  const enabledIds = new Set(enabled.enabled)
  for (const file of manifests) {
    const manifest = JSON.parse(readFileSync(file, 'utf8'))
    const pkgPath = path.join(path.dirname(file), 'package.json')
    if (!existsSync(pkgPath)) continue
    const pkg = JSON.parse(readFileSync(pkgPath, 'utf8'))
    const runtimeId = pkg.ordessa?.id
    if (runtimeId !== undefined) {
      // one identity: the logical id and the extension id must agree
      assert.equal(manifest.logicalPluginId, runtimeId,
        `${path.relative(repoRoot, file)}: logical id drifted from the extension id`)
      // entries bound to a runtime manifest must reference an enabled extension
      for (const entry of manifest.entries) {
        if (entry.existingRuntimeManifest !== undefined) {
          assert.ok(enabledIds.has(runtimeId),
            `${manifest.logicalPluginId} references the runtime manifest but is not enabled`)
        }
      }
    }
  }
})
