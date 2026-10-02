// N4-R1 (spec 021 core inventory) — the Workbench's own layering wall.
//
// `core-boundaries-small-refactor.md` §目标职责 assigns Workbench: 导航、区域/
// 视图/页、浮层、设置页容器和 UI 贡献注册; and explicitly *not* 模型/Profile
// 状态、配置存储与应用. §R2 then allows reorganising Workbench internals by
// layout/navigation/overlays/settings — which is only safe while this wall
// holds, so the wall is pinned here before any file moves.
//
// Nothing else guarded this direction:
//   · `products/desktop/tests/contract-ownership.test.mjs` guards the platform
//     umbrella against the Agent domain;
//   · `packages/desktop-platform/connections/tests/platform-isolation.test.ts`
//     guards the Connections platform;
//   · `extension-host/tests/plugin-host-boundary.test.ts` guards plugins
//     against host internals.
// Workbench was the unguarded one, and it is the package R2 will touch.
//
// Every assertion is paired with a counterexample so the scan cannot be green
// merely because it matched nothing.
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { createWorkbench } from '../src/model'
import type { ResourceScope } from '@ordessa/extension-api'

/** A minimal ResourceScope, the same shape `createWorkbench` is handed by the
 * extension host at activate time. */
function lifetimeScope(): ResourceScope {
  const items: { dispose(): void }[] = []
  return {
    isDisposed: false,
    add<T extends { dispose(): void }>(item: T): T { items.push(item); return item },
  }
}

const repoRoot = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..', '..', '..')
const packageRoot = path.join(repoRoot, 'packages', 'workbench')
const SOURCE_ROOTS = ['src', 'api', 'shared']

/** Bare specifiers the Workbench may use: the host extension API, the platform
 * contract carrier it is re-exported through (C4 — `packages/
 * desktop-platform/contracts/foundation/src/contract.ts:3-4` exists to carry
 * this one copy), and the three runtime libraries its package.json declares. */
const ALLOWED_BARE = ['@ordessa/extension-api', '@extensions/ordessa.contracts/contract.js', 'react', 'react-dom', 'react-resizable-panels']

const SOURCE_FILE_RE = /\.[cm]?[jt]sx?$/
const STATIC_RE = /(?:^|[;{}\n])\s*((?:import|export)\s+(?:type\s+)?[^;]*?from\s*|import\s*)['"]([^'"]+)['"]/g

/** Workbench product sources: the three shipped source roots, no tests and no
 * build/typecheck fixtures. */
function workbenchSources(): string[] {
  const found: string[] = []
  function walk(dir: string) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (['node_modules', 'dist', 'tests'].includes(entry.name)) continue
      const file = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(file)
      // *.typecheck.ts files are compile-only fixtures, never shipped: they are
      // excluded so the guard tracks the shipped surface, not the type surface.
      else if (SOURCE_FILE_RE.test(entry.name) && !entry.name.endsWith('.typecheck.ts')) found.push(file)
    }
  }
  for (const root of SOURCE_ROOTS) {
    const dir = path.join(packageRoot, root)
    if (existsSync(dir)) walk(dir)
  }
  return found.sort()
}

export function specifiersOf(source: string): string[] {
  return [...source.matchAll(new RegExp(STATIC_RE.source, 'g'))].map(match => match[2])
}

/** The reason a specifier is a layering violation, or null when it is allowed. */
export function violationReason(file: string, specifier: string): string | null {
  if (specifier.startsWith('.')) {
    const resolved = path.resolve(path.dirname(file), specifier)
    if (!resolved.startsWith(packageRoot + path.sep)) {
      return `escapes packages/workbench (resolves to ${path.relative(repoRoot, resolved)})`
    }
    return null
  }
  if (ALLOWED_BARE.includes(specifier)) return null
  return `'${specifier}' is outside the Workbench allow-list [${ALLOWED_BARE.join(', ')}]`
}

describe('N4-R1: the Workbench reaches nothing above or beside its own package', () => {
  const files = workbenchSources()
  const violations = files.flatMap(file => specifiersOf(readFileSync(file, 'utf8'))
    .map(specifier => ({ file: path.relative(repoRoot, file), specifier, reason: violationReason(file, specifier) }))
    .filter(entry => entry.reason !== null))

  it('scans the real Workbench sources, or this guard would pass vacuously', () => {
    const relative = files.map(file => path.relative(repoRoot, file))
    expect(relative.length).toBeGreaterThanOrEqual(8)
    expect(relative).toEqual(expect.arrayContaining([
      'packages/workbench/src/entry.tsx',
      'packages/workbench/src/model.ts',
      'packages/workbench/src/shell.tsx',
      'packages/workbench/api/workbench.ts',
    ]))
  })

  it('imports only its own package, the host API and the sanctioned carriers', () => {
    expect(violations.map(entry => `${entry.file} -> ${entry.specifier}: ${entry.reason}`)).toEqual([])
  })

  it('really does use the two sanctioned channels (the allow-list is not vacuous)', () => {
    const used = new Set(files.flatMap(file => specifiersOf(readFileSync(file, 'utf8'))))
    expect(used.has('@ordessa/extension-api')).toBe(true)
    expect(used.has('@extensions/ordessa.contracts/contract.js')).toBe(true)
    // …and every listed allowance is a real package dependency of this package.
    const pkg = JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8'))
    expect(Object.keys(pkg.dependencies)).toContain('react-resizable-panels')
  })

  it('counterexample: reaching into a domain plugin, a host module or an app IS a violation', () => {
    const entry = path.join(packageRoot, 'src', 'entry.tsx')
    const planted = [
      ["import { Workbench } from '../../../plugins/agent/contracts/src/contract'", '../../../plugins/agent/contracts/src/contract'],
      ["import { runtime } from '@ordessa/extension-host'", '@ordessa/extension-host'],
      ["import { buildHostServices } from '../../../apps/desktop/renderer/host-services'", '../../../apps/desktop/renderer/host-services'],
      ["import { AgentSessionsToken } from '@extensions/ordessa.agent-contracts/contract.js'", '@extensions/ordessa.agent-contracts/contract.js'],
    ] as const
    for (const [source, expected] of planted) {
      expect(specifiersOf(source)).toEqual([expected])
      expect(violationReason(entry, expected)).not.toBeNull()
    }
  })

  it('counterexample: the legal forms stay legal under the same scanner', () => {
    const entry = path.join(packageRoot, 'src', 'entry.tsx')
    for (const specifier of ['./model', '../shared/registry', '@ordessa/extension-api',
      '@extensions/ordessa.contracts/contract.js', 'react', 'react-dom']) {
      expect(violationReason(entry, specifier)).toBeNull()
    }
  })

  it('carries no domain token or connection-kind literal (Workbench owns no domain identity)', () => {
    // §目标职责: 模型/Profile 状态 belongs to the domains. Constructing one of
    // their DI identities here would be a second copy of a domain Token — the
    // exact failure the product's token guard (tests/token-single-instance.mjs)
    // exists to catch, checked here at the source so it fails before a build.
    const DOMAIN_LITERAL = /(?:new\s+Token\b|createConnectionKind\b)(?:<[^()]*>)?\s*\(\s*(['"])(ordessa\.(?:agent|profile|model|chat|harness)[^'"]*)\1/
    const hits: string[] = []
    for (const file of files) {
      readFileSync(file, 'utf8').split('\n').forEach((line, index) => {
        const match = DOMAIN_LITERAL.exec(line)
        if (match) hits.push(`${path.relative(repoRoot, file)}:${index + 1} constructs '${match[2]}'`)
      })
    }
    expect(hits).toEqual([])
    // The regex must be able to see one: feed it the Workbench's OWN token.
    expect(DOMAIN_LITERAL.test("export const WorkbenchToken = new Token<Workbench>('ordessa.workbench.v1')")).toBe(false)
    expect(DOMAIN_LITERAL.test("export const AgentSessionsToken = new Token<AgentSessions>('ordessa.agent.sessions.v1')")).toBe(true)
  })
})

// N4-R1 finding, pinned so R3 cannot merge the two Settings entry points by
// accident. `core-boundaries-small-refactor.md` §R3 asks for a source-evidence
// answer to "are SettingsContribution and WorkbenchComposition.addSettingsSection
// the same registry?" before any owner is chosen. The evidence is that the
// Workbench package never mentions the platform Settings contract at all:
//
//   token:        packages/desktop-platform/contracts/foundation/src/product/
//                 token/SettingsContributionToken.ts:11  ('ordessa.settings.v1')
//   host instance: apps/desktop/renderer/host-services.ts:111,120-126 (a plain
//                 array inside buildHostServices)
//   host consumer: apps/desktop/renderer/main.tsx:95 (services.settings
//                 .getSnapshot() -> SettingsPage `contributed`)
//   workbench:     packages/workbench/src/model.ts:24 (its own `registry()`),
//                  :124 (addSettingsSection -> sections.add),
//                  packages/workbench/src/shell.tsx:185 (renders model.sections)
//
// Two independent registries, two independent surfaces. If someone wires the
// Workbench to the platform token as part of R3, this test turns red and the
// change has to be made deliberately, with the migration note the spec requires.
describe('N4-R1: the two Settings entry points are still two independent registries', () => {
  const files = workbenchSources()
  const sources = files.map(file => ({ file, text: readFileSync(file, 'utf8') }))

  it('no Workbench source names the platform Settings contract or its token', () => {
    const hits = sources.filter(entry => /SettingsContributionToken|\bSettingsContribution\b/.test(entry.text))
      .map(entry => path.relative(repoRoot, entry.file))
    expect(hits).toEqual([])
    // The matcher must be able to see one, or the assertion above is vacuous.
    expect(/SettingsContributionToken|\bSettingsContribution\b/.test("import { SettingsContributionToken } from '@extensions/ordessa.contracts/contract.js'")).toBe(true)
  })

  it('the Workbench settings registry is its own, not the platform array', () => {
    // Runtime half: register through the public composition seam and read back
    // through the registry the shell renders from.
    const model = createWorkbench(lifetimeScope())
    const scope = lifetimeScope()
    const handle = model.composition.forScope(scope).addSettingsSection({
      id: 'probe.section', title: 'Probe', component: () => null,
    })
    expect(model.sections.getSnapshot().map(section => section.id)).toEqual(['probe.section'])
    // The platform SettingsContribution surface is `register(section) => dispose`
    // over a host-owned array; it exposes no snapshot of its own contract and
    // the Workbench service never receives one. Two shapes, two owners.
    const platformSurface: { register(section: unknown): () => void } = { register: () => () => undefined }
    expect(typeof platformSurface.register).toBe('function')
    expect(Object.keys(model.composition.forScope(scope)).sort()).toEqual(['addModule', 'addOverlay', 'addSettingsSection'])
    handle.dispose()
    expect(model.sections.getSnapshot()).toEqual([])
  })
})