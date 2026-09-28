// T006 guard, generalized for T020 and T029 (CN-08): EVERY DI Token literal
// and EVERY ConnectionKind literal constructed in the current product sources
// (watchlists + source discovery, see token-scan.mjs) must be built exactly
// once, only inside its owning shared bundle of the real product build, and
// this harness must go red when a second bundled copy of ANY of them appears
// (rogue-extension counterexample, parameterized per literal). Typechecking
// alone cannot pass this gate. The kind half additionally checks the runtime
// identity semantics against the REAL built carrier bundle: kind identity is
// per-construction, so a duplicated copy is a functional bug (open() kind
// matching silently fails), not a cosmetic one.
import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'
import { register } from 'node:module'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { promisify } from 'node:util'
import { build } from 'esbuild'
import {
  countKindConstructions, countTokenConstructions, discoverKindSources, discoverTokenSources,
  KIND_SOURCE_DISCOVERY_ROOTS, KIND_WATCHLIST, scanDirsForKindConstructions,
  scanDirsForTokenConstructions, TOKEN_SOURCE_DISCOVERY_ROOTS, TOKEN_WATCHLIST,
  WATCHED_KIND_LITERALS, WATCHED_TOKEN_LITERALS,
} from './token-scan.mjs'
import { acquireRealBuildLock } from '../../../tooling/real-build-lock.mjs'

const run = promisify(execFile)
const repoRoot = path.resolve(import.meta.dirname, '..', '..', '..')
const extensionsRoot = path.join(repoRoot, 'products/desktop/dist/extensions')
const sharedRoot = path.join(repoRoot, 'apps/desktop/dist/renderer/shared')
const artifactRoots = [extensionsRoot, sharedRoot]

function isOwnerSite(file, ownerBundle) {
  if (ownerBundle.startsWith('shared/')) {
    return file === path.join(sharedRoot, ownerBundle.slice('shared/'.length))
  }
  const relative = path.relative(extensionsRoot, file)
  return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative) &&
    relative.split(path.sep)[0] === ownerBundle
}

// Mirror tooling/build-extension.mjs externals so a variant build exercises the
// same bundling semantics as the real pipeline.
const EXTENSION_BUILDER_EXTERNALS = ['react', 'react/*', 'react-dom', 'react-dom/*', '@ordessa/extension-api', '@ordessa/ui-components/api', '@extensions/*']

// Discover the token and kind construction sites in the current product
// sources before the real build; the counterexamples below import these files
// directly.
const { sites: sourceSites, all: allDiscovered } = await discoverTokenSources(repoRoot, TOKEN_SOURCE_DISCOVERY_ROOTS, WATCHED_TOKEN_LITERALS)
const { sites: kindSourceSites, all: allKindsDiscovered } = await discoverKindSources(repoRoot, KIND_SOURCE_DISCOVERY_ROOTS, WATCHED_KIND_LITERALS)

// Build the real product extensions and renderer shared entries once; the
// positive scan needs both fresh artifacts from the same app build.
// Held under the cross-process real-build lock for the whole file: the product
// guards rebuild the same shared tree, and a scan must never see a half-written
// dist (tooling/real-build-lock.mjs).
const releaseRealBuildLock = await acquireRealBuildLock(repoRoot)
try {
  await run(process.execPath, [path.join(repoRoot, 'apps/desktop/scripts/build.mjs')], { cwd: repoRoot, stdio: 'inherit' })
} catch (error) {
  await releaseRealBuildLock()
  throw error
}
test.after(() => releaseRealBuildLock())

// The identity-semantics test imports the REAL built bundles below in-process.
// Map host API specifiers to the app's actual shared renderer entries and
// '@extensions/<id>/<file>.js' to each built carrier, matching the browser
// import map while executing the built bundles unmodified.
{
  const apiUrl = pathToFileURL(path.join(sharedRoot, 'api.js')).href
  const extensionsUrl = pathToFileURL(extensionsRoot).href + '/'
  const uiApiUrl = pathToFileURL(path.join(sharedRoot, 'ui-components-api.js')).href
  register('data:text/javascript,' + encodeURIComponent(`
export async function resolve(specifier, context, next) {
  if (specifier === '@ordessa/extension-api') return { url: ${JSON.stringify(apiUrl)}, shortCircuit: true }
  if (specifier === '@ordessa/ui-components/api') return { url: ${JSON.stringify(uiApiUrl)}, shortCircuit: true }
  if (specifier.startsWith('@extensions/')) return { url: ${JSON.stringify(extensionsUrl)} + specifier.slice('@extensions/'.length), shortCircuit: true }
  return next(specifier, context)
}`))
}

test('watch list is synced with the DI Tokens constructed in current product sources', () => {
  const watched = new Set(TOKEN_WATCHLIST.map(entry => entry.literal))
  const discovered = new Set(allDiscovered.keys())
  // Discovery itself is presence-checked: an empty or partial discovery (a
  // scanner regex drifting off the real source shapes) must fail, not pass
  // the set equality vacuously.
  for (const literal of watched) {
    assert.ok(discovered.has(literal), `watched token '${literal}' has no construction site under ${TOKEN_SOURCE_DISCOVERY_ROOTS.join(', ')}; discovery regressed or the watch list keeps a dead entry`)
  }
  for (const literal of discovered) {
    assert.ok(watched.has(literal), `source constructs token '${literal}' but the watch list does not cover it — real-build scanning would pass silently for an unwatched token`)
  }
  // A copied token definition in the sources (the CN-08 copy-Token mutation at
  // source level) must be caught even before any bundling.
  for (const literal of watched) {
    const sites = sourceSites[literal]
    assert.equal(sites.length, 1, `token '${literal}' must be constructed by exactly one source site, found ${sites.length}: ${JSON.stringify(sites.map(s => s.file), null, 2)}`)
  }
})

test('real product build constructs each watched DI token exactly once', async () => {
  const hits = await scanDirsForTokenConstructions(artifactRoots, WATCHED_TOKEN_LITERALS)
  for (const { literal, ownerBundle } of TOKEN_WATCHLIST) {
    const sites = hits[literal]
    const total = sites.reduce((n, s) => n + s.count, 0)
    // Presence first: a scanner or pipeline regression must not pass vacuously.
    assert.ok(total >= 1, `token '${literal}' is not constructed anywhere in ${artifactRoots.join(', ')}; the scan would pass vacuously`)
    assert.equal(total, 1, `token '${literal}' must be constructed exactly once, found ${total}: ${JSON.stringify(sites, null, 2)}`)
    assert.ok(
      isOwnerSite(sites[0].file, ownerBundle),
      `shared token '${literal}' leaked outside its owning bundle '${ownerBundle}': ${sites[0].file}`,
    )
  }
})

test('counterexample: a rogue direct-source import bundles a second construction and the guard goes red', async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'workbench-token-guard-'))
  try {
    const srcDir = path.join(tmp, 'src')
    const outDir = path.join(tmp, 'dist')
    await mkdir(srcDir, { recursive: true })
    for (const { literal, ownerBundle } of TOKEN_WATCHLIST) {
      const [{ file: tokenSource, exportName }] = sourceSites[literal]
      // Imports the token's API source file directly instead of the shared
      // '@extensions/<owner>/contract.js' external, so esbuild inlines a
      // second copy of the module including its `new Token(...)` site.
      const entryName = `entry-${literal.replace(/[^a-z0-9]+/gi, '_')}.ts`
      await writeFile(path.join(srcDir, entryName), [
        `import { ${exportName} } from ${JSON.stringify(tokenSource)}`,
        `export const rogueToken = ${exportName}`,
        ``,
      ].join('\n'))
      await build({
        entryPoints: { [path.basename(entryName, '.ts')]: path.join(srcDir, entryName) },
        outdir: outDir, bundle: true, format: 'esm', platform: 'browser',
        external: EXTENSION_BUILDER_EXTERNALS,
      })

      // The rogue bundle alone already carries the duplicated construction.
      const rogueOnly = await countTokenConstructions([outDir], [literal])
      assert.equal(rogueOnly[literal], 1, `variant build did not bundle a second Token copy for '${literal}'; the counterexample is not testing what it claims`)

      // The same scan over {real dist + variant bundle} must report the duplicate.
      const hits = await scanDirsForTokenConstructions([...artifactRoots, outDir], [literal])
      const sites = hits[literal]
      const total = sites.reduce((n, s) => n + s.count, 0)
      assert.equal(total, 2, `expected exactly one duplicated construction of '${literal}' across real dist + rogue bundle, got ${total}`)
      assert.equal(sites.filter(s => s.count > 0).length, 2, `duplicate of '${literal}' must span two distinct bundles: ${JSON.stringify(sites, null, 2)}`)
      // The uniqueness assertion of the positive test is what fails here — prove it.
      assert.notEqual(total, 1)
      // And the ownership rule discriminates too: the extra copy is not in
      // the owner bundle, so the owner check sees exactly the original one.
      const ownerCount = sites
        .filter(s => isOwnerSite(s.file, ownerBundle))
        .reduce((n, s) => n + s.count, 0)
      assert.equal(ownerCount, 1, `duplicate of '${literal}' must land outside the owner bundle for the owner check to discriminate: ${JSON.stringify(sites, null, 2)}`)
    }
  } finally {
    await rm(tmp, { recursive: true, force: true })
  }
})

test('watch list is synced with the connection kinds constructed in current product sources', () => {
  const watched = new Set(KIND_WATCHLIST.map(entry => entry.literal))
  const discovered = new Set(allKindsDiscovered.keys())
  // Presence-checked discovery, same discipline as the token sync test: an
  // empty or partial discovery (a regex drifting off the real source shapes)
  // must fail, not pass the set equality vacuously.
  for (const literal of watched) {
    assert.ok(discovered.has(literal), `watched kind '${literal}' has no createConnectionKind construction site under ${KIND_SOURCE_DISCOVERY_ROOTS.join(', ')}; discovery regressed or the watch list keeps a dead entry`)
  }
  for (const literal of discovered) {
    assert.ok(watched.has(literal), `source constructs kind '${literal}' but the watch list does not cover it — real-build scanning would pass silently for an unwatched kind`)
  }
  for (const literal of watched) {
    const sites = kindSourceSites[literal]
    assert.equal(sites.length, 1, `kind '${literal}' must be constructed by exactly one source site, found ${sites.length}: ${JSON.stringify(sites.map(s => s.file), null, 2)}`)
  }
})

test('real product build constructs each watched connection kind exactly once', async () => {
  const hits = await scanDirsForKindConstructions(artifactRoots, WATCHED_KIND_LITERALS)
  for (const { literal, ownerBundle } of KIND_WATCHLIST) {
    const sites = hits[literal]
    const total = sites.reduce((n, s) => n + s.count, 0)
    // Presence first: a scanner or pipeline regression must not pass vacuously.
    assert.ok(total >= 1, `kind '${literal}' is not constructed anywhere in ${extensionsRoot}; the scan would pass vacuously`)
    assert.equal(total, 1, `kind '${literal}' must be constructed exactly once, found ${total}: ${JSON.stringify(sites, null, 2)}`)
    assert.ok(
      isOwnerSite(sites[0].file, ownerBundle),
      `shared kind '${literal}' leaked outside its owning bundle '${ownerBundle}': ${sites[0].file}`,
    )
  }
})

test('counterexample: a rogue direct-source import bundles a second kind construction and the guard goes red', async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'workbench-kind-guard-'))
  try {
    const srcDir = path.join(tmp, 'src')
    const outDir = path.join(tmp, 'dist')
    await mkdir(srcDir, { recursive: true })
    for (const { literal, ownerBundle } of KIND_WATCHLIST) {
      const [{ file: kindSource, exportName }] = kindSourceSites[literal]
      // Imports the kind's source file directly instead of going through the
      // '@extensions/ordessa.contracts/contract.js' carrier for a shared copy,
      // so esbuild bundles a second module instance whose module scope calls
      // createConnectionKind('<literal>') again — producing a second, distinct
      // kind object at runtime (identity is per-construction).
      const entryName = `rogue-kind-${literal.replace(/[^a-z0-9]+/gi, '_')}.ts`
      await writeFile(path.join(srcDir, entryName), [
        `import { ${exportName} } from ${JSON.stringify(kindSource)}`,
        `export const rogueKind = ${exportName}`,
        ``,
      ].join('\n'))
      await build({
        entryPoints: { [path.basename(entryName, '.ts')]: path.join(srcDir, entryName) },
        outdir: outDir, bundle: true, format: 'esm', platform: 'browser',
        external: EXTENSION_BUILDER_EXTERNALS,
      })

      // The rogue bundle alone already carries the duplicated construction.
      const rogueOnly = await countKindConstructions([outDir], [literal])
      assert.equal(rogueOnly[literal], 1, `variant build did not bundle a second kind copy for '${literal}'; the counterexample is not testing what it claims`)

      // The same scan over {real dist + variant bundle} must report the duplicate.
      const hits = await scanDirsForKindConstructions([...artifactRoots, outDir], [literal])
      const sites = hits[literal]
      const total = sites.reduce((n, s) => n + s.count, 0)
      assert.equal(total, 2, `expected exactly one duplicated construction of '${literal}' across real dist + rogue bundle, got ${total}`)
      assert.equal(sites.filter(s => s.count > 0).length, 2, `duplicate of '${literal}' must span two distinct bundles: ${JSON.stringify(sites, null, 2)}`)
      // The uniqueness assertion of the positive test is what fails here — prove it.
      assert.notEqual(total, 1)
      // And the ownership rule discriminates: the extra copy is not in the
      // owner bundle, so the owner check sees exactly the original one.
      const ownerCount = sites
        .filter(s => isOwnerSite(s.file, ownerBundle))
        .reduce((n, s) => n + s.count, 0)
      assert.equal(ownerCount, 1, `duplicate of '${literal}' must land outside the owner bundle for the owner check to discriminate: ${JSON.stringify(sites, null, 2)}`)
    }
  } finally {
    await rm(tmp, { recursive: true, force: true })
  }
})

test('kind identity is per-construction: a duplicated kind literal is a functional break, not cosmetics', async () => {
  // Run the REAL built bundles (shimmed externals only), not sources or
  // fixtures: the ordessa.contracts carrier exposes the platform factory, and
  // the ordessa.agent-contracts carrier holds the one Agent kind construction.
  const carrier = await import(pathToFileURL(path.join(extensionsRoot, 'ordessa.contracts', 'contract.js')).href)
  const sharedApi = await import(pathToFileURL(path.join(sharedRoot, 'api.js')).href)
  assert.ok(carrier.CommandsToken instanceof sharedApi.Token,
    'the carrier must use the same Token class as the app import-map shared API')
  const uiApi = await import(pathToFileURL(path.join(sharedRoot, 'ui-components-api.js')).href)
  assert.equal(carrier.UiComponentsToken, uiApi.UiComponentsToken,
    'the foundation carrier must re-export the one renderer shared UI Token')
  assert.equal(typeof carrier.createConnectionKind, 'function', 'the real carrier bundle must export the sole ConnectionKind factory')
  const agentContracts = await import(pathToFileURL(path.join(extensionsRoot, 'ordessa.agent-contracts', 'contract.js')).href)
  const realKind = agentContracts.AgentClientConnectionKind
  assert.ok(realKind, 'the real agent-contracts carrier must export AgentClientConnectionKind')
  assert.equal(realKind.displayName, 'ordessa.agent-client')
  // Two kinds built from the same literal are NOT ===, i.e. a second bundled
  // copy of the construction is a second runtime identity — Connections.open
  // compares kinds with ===, so a copy silently rejects every connector
  // registered under the original. That is why the exactly-once scan matters.
  assert.notEqual(carrier.createConnectionKind('ordessa.agent-client'), carrier.createConnectionKind('ordessa.agent-client'), 'createConnectionKind must give each construction its own identity')
  assert.notEqual(realKind, carrier.createConnectionKind('ordessa.agent-client'), 'a fresh construction of the same literal must not match the product kind by identity')
  // The carrier mechanism itself: resolving the same shared bundle twice in
  // one process yields the identical module instance, so every extension that
  // imports the kind THROUGH the carrier gets the one true object (this is
  // what prevents the CN-08 duplicate in the first place).
  const agentContractsAgain = await import(pathToFileURL(path.join(extensionsRoot, 'ordessa.agent-contracts', 'contract.js')).href)
  assert.equal(agentContractsAgain.AgentClientConnectionKind, realKind, 'the same built carrier module must hand out one shared kind instance')
})
