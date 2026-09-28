// Reusable real-build DI Token / ConnectionKind construction scanner (T006;
// reused by T020/T021; kind coverage added by T029 for CN-08).
// Scans built JS bundles for `new Token(...)`-style constructions and
// `createConnectionKind('...')` calls whose string literal matches a watched
// id, so single-instance guarantees are verified against esbuild output, not
// just types.
import { readdir, readFile } from 'node:fs/promises'
import path from 'node:path'

/** Recursively list every *.js file under dir. */
export async function findJsFiles(dir) {
  const found = []
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name)
    if (entry.isDirectory()) found.push(...await findJsFiles(file))
    else if (entry.name.endsWith('.js')) found.push(file)
  }
  return found.sort()
}

// Matches any `new <Ctor>(<literal>` construction surviving esbuild output,
// e.g. `new Token("ordessa.workbench.v1")` or `new Token2("ordessa.workbench.v1")`
// (esbuild renames duplicated import bindings, so the constructor name is not
// stable; the watched token-id literal as the first argument is). Only
// literals from the watch list are counted, so this cannot drift into
// matching unrelated `new` calls.
const TOKEN_CONSTRUCTION_RE = /new\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*(?:<[^<>()]*>)?\s*\(\s*(['"])((?:[^\\'"\n])*)\2/g

// Matches any surviving `createConnectionKind<...>('<literal>')` CALL in built
// JS, tolerating esbuild's duplicated-binding suffix (createConnectionKind2…).
// The regex stays honest three ways: (1) the first argument must be a string
// LITERAL, so the factory's own definition `function createConnectionKind(displayName)`
// can never match; (2) a bare `import { createConnectionKind } from "…"` has
// no `(` after the binding, so re-exports and import statements are not calls;
// (3) only literals from the kind watch list are counted, so unrelated calls
// cannot drift in. The leading (?:^|[^\w$.]) guard keeps member expressions
// (`x.createConnectionKind('lit')`) out of the count — construction is always
// the bare (possibly suffixed) module binding in these bundles.
const KIND_CONSTRUCTION_RE = /(?:^|[^\w$.])(createConnectionKind\d*)\s*\(\s*(['"])((?:[^\\'"\n])*)\2/g

/** Scan one built file for constructions of the watched literals. */
async function scanFileWith(filePath, literals, constructionRe) {
  const source = await readFile(filePath, 'utf8')
  const perLiteral = new Map(literals.map(l => [l, 0]))
  for (const match of source.matchAll(constructionRe)) {
    if (perLiteral.has(match[3])) perLiteral.set(match[3], perLiteral.get(match[3]) + 1)
  }
  return perLiteral
}

/**
 * Scan one built file for token constructions of the watched literals.
 * Returns Map<literal, occurrences-in-this-file>.
 */
export async function scanFile(filePath, literals) {
  return scanFileWith(filePath, literals, new RegExp(TOKEN_CONSTRUCTION_RE.source, 'g'))
}

/** Same as scanFile, for `createConnectionKind('<literal>')` constructions. */
export async function scanFileForKindConstructions(filePath, literals) {
  return scanFileWith(filePath, literals, new RegExp(KIND_CONSTRUCTION_RE.source, 'g'))
}

/**
 * Scan all built JS under the given directories for constructions of each
 * watched literal. Returns { literal: [{ file, count }] } including literals
 * with zero hits (callers assert both presence and uniqueness).
 */
async function scanDirsForConstructions(dirs, literals, scanOne) {
  const hits = Object.fromEntries(literals.map(l => [l, []]))
  for (const dir of dirs) {
    for (const file of await findJsFiles(dir)) {
      const perLiteral = await scanOne(file, literals)
      for (const [literal, count] of perLiteral) {
        if (count > 0) hits[literal].push({ file, count })
      }
    }
  }
  return hits
}

export async function scanDirsForTokenConstructions(dirs, literals) {
  return scanDirsForConstructions(dirs, literals, scanFile)
}

/** Same as scanDirsForTokenConstructions, for connection kinds. */
export async function scanDirsForKindConstructions(dirs, literals) {
  return scanDirsForConstructions(dirs, literals, scanFileForKindConstructions)
}

/** Total construction count per literal across dirs. */
async function countConstructions(dirs, literals, scanDirs) {
  const hits = await scanDirs(dirs, literals)
  return Object.fromEntries(Object.entries(hits).map(([l, sites]) => [l, sites.reduce((n, s) => n + s.count, 0)]))
}

export async function countTokenConstructions(dirs, literals) {
  return countConstructions(dirs, literals, scanDirsForTokenConstructions)
}

/** Same as countTokenConstructions, for connection kinds. */
export async function countKindConstructions(dirs, literals) {
  return countConstructions(dirs, literals, scanDirsForKindConstructions)
}

// Every DI Token literal currently constructed in the product sources, with
// the shared bundle that owns its single copy. T029 admitted
// 'ordessa.connections.v1' by appending one entry here plus one roots entry
// (its construction site lives in packages/desktop-platform/connections/api,
// outside TOKEN_SOURCE_DISCOVERY_ROOTS). Nothing else in this guard is
// token-specific: the positive scan, the presence/uniqueness/ownership
// assertions and the rogue-bundle counterexample are all driven by this list
// plus source discovery, and the sync test fails if this list and the sources
// ever drift apart.
export const TOKEN_WATCHLIST = [
  { literal: 'ordessa.workbench.v1', ownerBundle: 'ordessa.contracts' },
  { literal: 'ordessa.commands.v1', ownerBundle: 'ordessa.contracts' },
  { literal: 'ordessa.agent.connections.v1', ownerBundle: 'ordessa.agent-contracts' },
  { literal: 'ordessa.agent.sessions.v1', ownerBundle: 'ordessa.agent-contracts' },
  { literal: 'ordessa.connections.v1', ownerBundle: 'ordessa.contracts' },
  { literal: 'ordessa.ui-components.v1', ownerBundle: 'shared/ui-components-api.js' },
]

// Kept for reuse (T021): the plain literal list derived from the watchlist.
export const WATCHED_TOKEN_LITERALS = TOKEN_WATCHLIST.map(entry => entry.literal)

// Source roots where shared DI Tokens may legitimately be constructed. The
// sync test discovers `new Token('<literal>')` sites under these roots and
// requires the discovered set to equal the watchlist.
export const TOKEN_SOURCE_DISCOVERY_ROOTS = [
  'packages/desktop-platform/contracts',
  'packages/workbench/api',
  'packages/desktop-platform/connections/api',
  'packages/desktop-platform/ui-components/api',
  'plugins/agent/contracts/src',
]

// Every ConnectionKind literal currently constructed in the product sources
// via the platform factory `createConnectionKind<T>('<literal>')`, with the
// shared bundle that owns its single copy (T029, CN-08 — kinds ride the same
// guard as tokens: presence, exactly-once, ownership, rogue duplicate). A
// second copy is a real bug, not cosmetics: kind identity is per-construction
// (`createConnectionKind('x') !== createConnectionKind('x')`), so two bundled
// copies of the same literal make `Connections.open(scope, id, kind)` reject
// every connector registered under the other copy. New kinds are admitted by
// appending one entry here, plus one roots entry only if the owning source
// directory lies outside KIND_SOURCE_DISCOVERY_ROOTS.
export const KIND_WATCHLIST = [
  { literal: 'ordessa.agent-client', ownerBundle: 'ordessa.agent-contracts' },
]

export const WATCHED_KIND_LITERALS = KIND_WATCHLIST.map(entry => entry.literal)

// Source roots where shared connection kinds may legitimately be constructed
// (the Agent domain kind lives in the src directory of the domain carrier
// package plugins/agent/contracts, the ordessa.agent-contracts package).
export const KIND_SOURCE_DISCOVERY_ROOTS = [
  'plugins/agent/contracts/src',
]

// A source-level construction site, e.g.
//   export const WorkbenchToken = new Token<Workbench>('ordessa.workbench.v1')
// Capture groups: 1 = exported binding name, 2 = quote, 3 = token literal.
const SOURCE_TOKEN_RE = /export\s+const\s+(\w+)\s*=\s*new\s+Token\b(?:<[^()]*?>)?\s*\(\s*(['"])([^'"]*)\2/g

// The kind analogue:
//   export const AgentClientConnectionKind = createConnectionKind<AgentClient>('ordessa.agent-client')
// Capture groups match SOURCE_TOKEN_RE (1 = binding, 3 = literal).
const SOURCE_KIND_RE = /export\s+const\s+(\w+)\s*=\s*createConnectionKind\b(?:<[^()]*?>)?\s*\(\s*(['"])([^'"]*)\2/g

/**
 * Discover every source-level construction site in the TypeScript sources
 * under the given roots (relative to repoRoot). Returns
 * { sites: { literal: [{ file, exportName }] }, all: Map<literal, sites[]> }.
 */
async function discoverSources(repoRoot, roots, literals, sourceRe) {
  const sites = Object.fromEntries(literals.map(l => [l, []]))
  const all = new Map() // every literal found in sources, watched or not
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules' && entry.name !== 'dist') await walk(path.join(dir, entry.name))
        continue
      }
      if (!/\.[cm]?ts$/.test(entry.name)) continue
      const file = path.join(dir, entry.name)
      const source = await readFile(file, 'utf8')
      for (const match of source.matchAll(sourceRe)) {
        const literal = match[3]
        if (!all.has(literal)) all.set(literal, [])
        all.get(literal).push({ file, exportName: match[1] })
      }
    }
  }
  for (const root of roots) await walk(path.join(repoRoot, root))
  for (const [literal, found] of all) {
    if (!sites[literal]) sites[literal] = []
    sites[literal].push(...found)
  }
  return { sites, all }
}

export async function discoverTokenSources(repoRoot, roots, literals) {
  return discoverSources(repoRoot, roots, literals, new RegExp(SOURCE_TOKEN_RE.source, 'g'))
}

/** Same as discoverTokenSources, for `createConnectionKind('<literal>')` sites. */
export async function discoverKindSources(repoRoot, roots, literals) {
  return discoverSources(repoRoot, roots, literals, new RegExp(SOURCE_KIND_RE.source, 'g'))
}
