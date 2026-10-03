// N4-R1 (spec 021 core inventory) — the plugin → host-internal direction wall.
//
// docs/architecture.md §Dependency direction states the load-bearing rule
// verbatim: "plugins/* ──▶ (plugins never import host internals)". This file
// mechanises the half of that rule the existing guards do not cover:
// `products/desktop/tests/contract-ownership.test.mjs` guards the OPPOSITE wall
// (the platform must not reverse-import a domain carrier), and
// `connections/tests/platform-isolation.test.ts` guards the platform's own
// sources. Nobody guarded the extension plugins against reaching back into the
// host's private modules.
//
// Scope and honesty rules this guard follows:
//   · Value imports (binding, side-effect or `require`) of a host-internal
//     module are a violation. Type-only imports (`import type …`) are NOT:
//     they are erased at bundle time and never become a runtime coupling. The
//     inventory found exactly four of them; they are enumerated below so the
//     registry is explicit and a fifth one turns this suite red instead of
//     quietly widening the coupling.
//   · A plugin importing its OWN subdirectories is never a violation — only a
//     target outside the importing plugin package counts.
//   · `plugins/harness/**` is out of scope: per AGENTS.md the bridge internals
//     are harness-internal, and that tree is a self-contained JS/Python/Go
//     package, not a desktop extension.
//   · Every assertion has a counterexample half, so the guard cannot be green
//     merely because the scanner failed to match anything.
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const repoRoot = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..', '..', '..', '..', '..')
const pluginsRoot = path.join(repoRoot, 'plugins')

// Repository subtrees a desktop extension plugin may never reach into: the two
// apps, the host-side platform packages, the platform contract carriers and the
// harness plugin.
const HOST_DIRS = [
  'apps/desktop',
  'apps/server',
  'packages/frontend/extension-host',
  'packages/frontend/extension-loader',
  'packages/frontend/native-bridge',
  'packages/frontend/server-bridge',
  'packages/frontend/contracts',
  'plugins/harness',
]
// Bare specifiers naming the same host modules (a plugin reaching for them by
// package name instead of by relative path).
const HOST_BARE = ['@ordessa/extension-host', '@ordessa/native-bridge', '@ordessa/server-bridge', '@ordessa/extension-loader']

const SOURCE_FILE_RE = /\.[cm]?[jt]sx?$/

// A static import/export clause: statement-shaped (anchored on `^`, `;`, `{`,
// `}` or a newline) so `import.meta.url` — which has no specifier and no
// `from` — cannot read as one. Group 1 is the clause (used only to tell
// `import type` from a value import), group 2 the specifier.
const STATIC_RE = /(?:^|[;{}\n])\s*((?:import|export)\s+(?:type\s+)?[^;]*?from\s*|import\s*)['"]([^'"]+)['"]/g
// `require('…')` and dynamic `import('…')` carry no type-only form, so they are
// matched on their own (unanchored `require` cannot appear in a comment that
// would change the verdict).
const CALL_RE = /\b(?:require|import)\s*\(\s*['"]([^'"]+)['"]/g

export interface Violation { file: string; line: number; specifier: string; target: string; typeOnly: boolean }

/** The host subtree a specifier reaches, or null when it stays inside the
 * plugin's own package. Exported so the counterexamples below can drive it. */
export function hostTargetOf(file: string, specifier: string): string | null {
  const pluginRoot = owningPackageRoot(file)
  const isOwn = (target: string) => pluginRoot !== null && (target === pluginRoot || target.startsWith(pluginRoot + path.sep))
  if (specifier.startsWith('.')) {
    const resolved = path.resolve(path.dirname(file), specifier)
    for (const dir of HOST_DIRS) {
      const hostDir = path.join(repoRoot, dir)
      if ((resolved === hostDir || resolved.startsWith(hostDir + path.sep)) && !isOwn(resolved)) return dir
    }
    return null
  }
  if (specifier.startsWith('@')) {
    return HOST_BARE.find(bare => specifier === bare || specifier.startsWith(`${bare}/`)) ?? null
  }
  return null
}

function owningPackageRoot(file: string): string | null {
  let dir = path.dirname(file)
  while (dir.startsWith(pluginsRoot + path.sep)) {
    if (existsSync(path.join(dir, 'package.json')) || existsSync(path.join(dir, 'pyproject.toml'))) return dir
    dir = path.dirname(dir)
  }
  return null
}

/** Every static and call-form specifier in a source text, tagged type-only or not. */
export function specifiersOf(source: string): { specifier: string; typeOnly: boolean }[] {
  const entries = [...source.matchAll(new RegExp(STATIC_RE.source, 'g'))].map(match => ({
    specifier: match[2],
    typeOnly: /^(?:import|export)\s+type\s/.test(match[1].trim()),
  }))
  for (const match of source.matchAll(new RegExp(CALL_RE.source, 'g'))) {
    entries.push({ specifier: match[1], typeOnly: false })
  }
  return entries
}

/** Plugin production sources: no tests, no builds, no installed output. */
function pluginSources(): string[] {
  const found: string[] = []
  function walk(dir: string) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (['node_modules', 'dist', '__pycache__', '.pytest_cache', 'harness'].includes(entry.name)) continue
      const file = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(file)
      else if (SOURCE_FILE_RE.test(entry.name) && !/\.test\.[cm]?[jt]sx?$/.test(entry.name)
        && !/(^|[\\/])(tests?|__tests__)[\\/]/.test(file)) found.push(file)
    }
  }
  walk(pluginsRoot)
  return found.sort()
}

function violationsIn(files: string[]): Violation[] {
  const violations: Violation[] = []
  for (const file of files) {
    const source = readFileSync(file, 'utf8')
    for (const { specifier, typeOnly } of specifiersOf(source)) {
      const target = hostTargetOf(file, specifier)
      if (target === null) continue
      violations.push({ file: path.relative(repoRoot, file), line: 0, specifier, target, typeOnly })
    }
  }
  return violations
}

// The four type-only references the N4-R1 inventory found. Frozen: each is a
// plugin naming a host module in a type position (erased at build time), and
// closing them means moving the shared types to a public carrier — a contract
// migration that R1 deliberately does not perform. A fifth entry turns the
// suite red instead of letting the coupling grow unnoticed.
const KNOWN_TYPE_ONLY_LEAKS = [
  // (T008-06: the connectors' transport-handle imports now NAME the public
  // @ordessa/native-bridge contract instead of reaching into apps/desktop —
  // still type-only and still tracked here per the N4-R1 wall; the 012
  // review decides when the wall retires these entries entirely.)
  'plugins/connectors/acp/src/native.ts -> ../../../../packages/frontend/native-bridge/src/index',
  'plugins/connectors/acp/src/host.ts -> @ordessa/native-bridge',
  'plugins/connectors/ordessa/src/native.ts -> ../../../../packages/frontend/native-bridge/src/index',
  'plugins/connectors/ordessa/src/client.ts -> @ordessa/native-bridge',
]

describe('N4-R1: extension plugins never reach into host internals', () => {
  const files = pluginSources()
  const violations = violationsIn(files)

  it('scans a non-empty plugin source set, or this guard would pass vacuously', () => {
    const relative = files.map(file => path.relative(repoRoot, file))
    expect(relative.length).toBeGreaterThan(100)
    expect(relative).toEqual(expect.arrayContaining([
      'plugins/chat/frontend/src/entry.tsx',
      'plugins/connectors/acp/src/host.ts',
      'plugins/model-provider/desktop/src/entry.tsx',
    ]))
  })

  it('has no VALUE import of a host-internal module', () => {
    // Type-only imports are erased at build time and are enumerated separately.
    const valueViolations = violations.filter(violation => !violation.typeOnly)
    expect(valueViolations.map(violation => `${violation.file} -> ${violation.specifier} [${violation.target}]`)).toEqual([])
  })

  it('records exactly the known type-only host references and no more', () => {
    const typeOnly = violations.filter(violation => violation.typeOnly)
      .map(violation => `${violation.file} -> ${violation.specifier}`)
    expect(typeOnly.sort()).toEqual([...KNOWN_TYPE_ONLY_LEAKS].sort())
  })

  it('still lets a plugin reach the public API packages and its own subdirectories', () => {
    // Positive half: the guard must not be green because every specifier was
    // rejected. These are the channels plugins legitimately use.
    const allowed = [
      ['plugins/chat/frontend/src/entry.tsx', '@ordessa/extension-api'],
      ['plugins/chat/frontend/src/entry.tsx', '@extensions/ordessa.contracts/contract.js'],
      ['plugins/model-provider/desktop/src/entry.tsx', '@ordessa/ui-components/api'],
      ['plugins/agent/contracts/src/agent.ts', '@extensions/ordessa.contracts/contract.js'],
      ['plugins/connectors/acp/src/host.ts', './channel'],
    ] as const
    for (const [file, specifier] of allowed) {
      expect(hostTargetOf(path.join(repoRoot, file), specifier)).toBeNull()
    }
  })

  it('counterexample: a value import of a host internal IS a violation', () => {
    const planted = [
      `import { runtime } from '@ordessa/extension-host'`,
      `import '@ordessa/native-bridge'`,
      `const host = require('../../../../apps/desktop/renderer/host-services')`,
      `export { Shell } from '../../../../apps/desktop/renderer/app'`,
    ]
    // A leading newline so the statement-shaped matcher sees each clause the way
    // it sees one in a real module body.
    for (const source of planted.map(text => `\n${text}`)) {
      const [entry, ...rest] = specifiersOf(source)
      expect(entry, `the scanner matched nothing in: ${source}`).toBeDefined()
      expect(rest).toEqual([])
      expect(entry.typeOnly).toBe(false)
      expect(hostTargetOf(path.join(repoRoot, 'plugins/connectors/acp/src/host.ts'), entry.specifier)).not.toBeNull()
    }
  })

  it('counterexample: a type-only import of the same host internal is NOT a violation', () => {
    // The distinction that keeps the current tree green is real, not a loophole
    // in the scanner: the same specifier in a type position is accepted.
    const source = `import type { AgentNativeBridge } from '../../../../apps/desktop/renderer/agent-native'`
    const [entry] = specifiersOf(source)
    expect(entry.typeOnly).toBe(true)
    expect(hostTargetOf(path.join(repoRoot, 'plugins/connectors/acp/src/host.ts'), entry.specifier)).not.toBeNull()
  })

  it('counterexample: a plugin importing its own subdirectory is NOT a violation', () => {
    const source = `import { x } from '../shared/registry'`
    const [entry] = specifiersOf(source)
    expect(hostTargetOf(path.join(repoRoot, 'packages/frontend/workbench/src/entry.tsx'), '../shared/registry')).toBeNull()
    expect(entry.specifier).toBe('../shared/registry')
  })
})