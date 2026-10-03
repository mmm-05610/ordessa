/**
 * T009-04 gates: trusted builtin modules vs third-party execution domains.
 *
 * - a plugin manifest may name a main-process (`native:`) entry ONLY inside
 *   the trusted builtin allowlist — third-party manifests carry renderer
 *   entries (or nothing) and never reach the main process;
 * - no main-process source performs a top-level DYNAMIC import of a
 *   non-literal specifier (third-party modules load through the injected
 *   importModule seam, never by main-side dynamic resolution);
 * - the renderer window keeps its isolation posture (contextIsolation on,
 *   nodeIntegration off, sandbox on) — the embedded face gets only the
 *   capabilities it declares, never a global relaxation.
 */
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import path from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

// The trusted builtins allowed a `native:` manifest entry (main-process code).
const TRUSTED_MAIN_ENTRIES = new Set([
  'ordessa.agent-acp', // its native.js is the reviewed ACP adapter entry
  'ordessa.agent-server', // first-party Ordessa wire connector (reviewed builtin)
])

// Review-shaped allowances: main-process variable imports that are trusted
// builtins, each with its justification on record. Third-party code reaches
// the main process only through the injected import seam.
const REVIEWED_VARIABLE_IMPORTS = [
  {
    pattern: 'apps/desktop/electron/main.ts: pathToFileURL(driver',
    reason: 'ORDESSA_SMOKE_DRIVER is the test-only smoke driver seam: env-controlled, '
      + 'never set by the product launcher, loaded only by the controlled smoke scripts',
  },
]

function walk(dir, out = []) {
  if (!existsSync(dir)) return out
  for (const name of readdirSync(dir)) {
    if (['node_modules', 'dist', '.git', 'build', '__pycache__'].includes(name)) continue
    const entry = path.join(dir, name)
    if (statSync(entry).isDirectory()) walk(entry, out)
    else out.push(entry)
  }
  return out
}

test('only trusted builtins carry main-process (native:) entries', () => {
  const offenders = []
  for (const root of ['plugins', 'examples', 'packages']) {
    for (const file of walk(path.join(repoRoot, root))) {
      if (path.basename(file) !== 'manifest.json') continue
      let manifest
      try { manifest = JSON.parse(readFileSync(file, 'utf8')) } catch { continue }
      const id = manifest.id
      const hasNative = Object.values(manifest.entries ?? {}).some(
        value => typeof value === 'string' && value.startsWith('native:'))
        || typeof manifest.native === 'string'
      if (hasNative && !TRUSTED_MAIN_ENTRIES.has(id)) {
        offenders.push(`${path.relative(repoRoot, file)} (${id})`)
      }
    }
  }
  assert.deepEqual(offenders, [], 'third-party manifests must not reach the main process')
})

test('no main-process source performs a top-level variable dynamic import', () => {
  const offenders = []
  const roots = [
    'apps/desktop/electron',
    'packages/frontend/extension-runtime/host/src/main',
  ]
  for (const root of roots) {
    for (const file of walk(path.join(repoRoot, root))) {
      if (!/\.[cm]?js$|\.ts$/.test(file)) continue
      const source = readFileSync(file, 'utf8')
      for (const match of source.matchAll(/(^|[;{}\n])\s*(?:const|let|var)\s+\w+\s*=\s*await\s+import\(([^'")]+)\)/gm)) {
        offenders.push(`${path.relative(repoRoot, file)}: ${match[2].trim()}`)
      }
    }
  }
  const remaining = offenders.filter(offender =>
    !REVIEWED_VARIABLE_IMPORTS.some(allow => offender.startsWith(allow.pattern)))
  assert.deepEqual(remaining, [],
    'third-party modules load only through the injected import seam '
    + '(reviewed builtins carry their justification in REVIEWED_VARIABLE_IMPORTS)')
})

test('the renderer keeps its isolation posture (no global relaxation)', () => {
  const security = readFileSync(
    path.join(repoRoot, 'apps/desktop/electron/security.ts'), 'utf8')
  assert.match(security, /contextIsolation:\s*true/)
  assert.match(security, /nodeIntegration:\s*false/)
  assert.match(security, /sandbox:\s*true/)
})
