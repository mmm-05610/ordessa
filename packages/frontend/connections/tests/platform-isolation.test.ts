// T029 (contract C6 §3, CN-01's gate half) — the Connections platform must be a
// zero-business-coupling platform: it may not reach Agent or Workbench code, and
// it may not construct or reference a business Token/kind literal. CN-01's
// lifecycle test proves the platform WORKS against in-memory fakes only; this
// guard proves the structural half — the "导入 Agent 或必须启用 Workbench 时门禁红"
// counterexample — against the current product sources. The built-bundle half of
// the same check lives in products/desktop/tests/connections-platform-isolation.test.mjs,
// where the real product build is available.
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const packageRoot = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
// Product sources only: the guard's own tests deliberately name fake
// counterparties after the business domains, and vitest.config.ts is plumbing.
const SOURCE_ROOTS = ['api', 'src', 'extension']
const SOURCE_FILE_RE = /\.[cm]?[jt]sx?$/

// Bare specifiers the platform may import: the host extension API (lifetime and
// Token layer), the package's own public api subpath, and the SHARED CONTRACT
// CARRIER `@extensions/ordessa.contracts/…` — the sanctioned channel for the one
// Token/kind copy (C6 ruling). Any other `@extensions/…` is a business carrier.
const ALLOWED_BARE = ['@ordessa/extension-api', '@ordessa/connections/api', '@extensions/ordessa.contracts/']

// Business literals that must never appear in the platform: every Token and
// ConnectionKind id the Agent/Workbench domains own in the product. The
// companion real-build guard presence-checks each of these against the product
// dist, so an entry that stops existing anywhere cannot rot into dead weight.
const BUSINESS_LITERALS = [
  'ordessa.workbench.v1',
  'ordessa.commands.v1',
  'ordessa.agent.connections.v1',
  'ordessa.agent.sessions.v1',
  'ordessa.agent-client',
]

function sourceFiles() {
  const files = []
  function walk(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(file)
      else if (SOURCE_FILE_RE.test(entry.name)) files.push(file)
    }
  }
  for (const root of SOURCE_ROOTS) {
    const dir = path.join(packageRoot, root)
    if (existsSync(dir)) walk(dir)
  }
  return files
}

// Static `… from '…'` plus dynamic import() and require() specifiers. Deliberately
// not matching a bare `import` keyword, so `import.meta.url` cannot read as one.
const SPECIFIER_RE = /\bfrom\s*['"]([^'"]+)['"]|\bimport\s*\(\s*['"]([^'"]+)['"]|\brequire\s*\(\s*['"]([^'"]+)['"]/g

function specifiersOf(source) {
  return [...source.matchAll(SPECIFIER_RE)].map(match => match[1] ?? match[2] ?? match[3])
}

const relativeEscape = (file, specifier) => {
  const target = path.resolve(path.dirname(file), specifier)
  const relative = path.relative(packageRoot, target)
  return relative.startsWith('..') || path.isAbsolute(relative) ? relative : null
}

describe('CN-01 gate: the platform sources carry no business coupling', () => {
  const files = sourceFiles()

  it('scans a non-empty set of product sources, or this guard would pass vacuously', () => {
    expect(files.map(file => path.relative(packageRoot, file))).toEqual(
      expect.arrayContaining(['api/connections.ts', 'extension/entry.ts']),
    )
  })

  it('imports nothing that escapes the platform package or leaves the allow-list', () => {
    const violations = []
    for (const file of files) {
      for (const specifier of specifiersOf(readFileSync(file, 'utf8'))) {
        const label = `${path.relative(packageRoot, file)} → '${specifier}'`
        if (specifier.startsWith('.')) {
          const escaped = relativeEscape(file, specifier)
          if (escaped) violations.push(`${label} escapes the platform package (resolves to ${escaped}) and would be inlined into its bundle`)
        } else if (!ALLOWED_BARE.some(allowed => specifier === allowed || specifier.startsWith(allowed.replace(/\/$/, '') + '/'))) {
          violations.push(`${label} is a bare specifier outside the platform allow-list [${ALLOWED_BARE.join(', ')}]`)
        }
      }
    }
    expect(violations).toEqual([])
  })

  it('never references an Agent or Workbench token/kind literal', () => {
    const violations = []
    for (const file of files) {
      const source = readFileSync(file, 'utf8')
      for (const literal of BUSINESS_LITERALS) {
        if (source.includes(literal)) violations.push(`${path.relative(packageRoot, file)} references the business literal '${literal}'`)
      }
    }
    expect(violations).toEqual([])
  })
})
