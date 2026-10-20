/**
 * T009-04 gates: trusted builtin modules vs third-party execution domains.
 *
 * - bundled repository manifests that declare main-process (`native:`) entries
 *   must be in the reviewed first-party allowlist; the user-enabled local extension
 *   loader is a separate capability with its own confined-root checks;
 * - smoke driver loading is bound to a closed, digest-pinned fixture resolver;
 * - the separate native extension loader imports only an enabled discovered entry
 *   after path confinement to that extension root; both variable imports are AST-checked;
 * - the renderer window keeps its isolation posture (contextIsolation on,
 *   nodeIntegration off, sandbox on) — the embedded face gets only the
 *   capabilities it declares, never a global relaxation.
 */
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import path from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import * as ts from 'typescript'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..')

// The trusted builtins allowed a `native:` manifest entry (main-process code).
const TRUSTED_MAIN_ENTRIES = new Set([
  'ordessa.agent-acp', // its native.js is the reviewed ACP adapter entry
  'ordessa.agent-server', // first-party Ordessa wire connector (reviewed builtin)
])

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

test('bundled source manifests with main-process (native:) entries are reviewed first-party IDs', () => {
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
  assert.deepEqual(offenders, [], 'bundled repository native entries require first-party review; this does not classify user-data extensions')
})

function dynamicImports(source, fileName) {
  const parsed = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true,
    fileName.endsWith('.ts') ? ts.ScriptKind.TS : ts.ScriptKind.JS)
  const found = []
  function visit(node) {
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      const arg = node.arguments[0]
      const literal = !!arg && (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg))
      found.push({ argument: arg?.getText(parsed) ?? '<missing>', literal, node })
    }
    ts.forEachChild(node, visit)
  }
  visit(parsed)
  return found
}

function parseMainSource(source, fileName) {
  return ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true,
    fileName.endsWith('.ts') ? ts.ScriptKind.TS : ts.ScriptKind.JS)
}

function hasThrow(node) {
  let found = false
  function visit(child) {
    if (ts.isThrowStatement(child)) found = true
    ts.forEachChild(child, visit)
  }
  visit(node)
  return found
}

function declarations(sourceFile, name) {
  const found = []
  function visit(node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text === name) found.push(node)
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return found
}

function calls(sourceFile, expressionText) {
  const found = []
  function visit(node) {
    if (ts.isCallExpression(node) && node.expression.getText(sourceFile) === expressionText) found.push(node)
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return found
}

function requireIfThrow(sourceFile, conditionText, description) {
  let matched = false
  function visit(node) {
    if (ts.isIfStatement(node) && node.expression.getText(sourceFile) === conditionText && hasThrow(node.thenStatement)) matched = true
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  assert.ok(matched, `${description}: required fail-closed branch missing`)
}

function requireSmokeRefusal(sourceFile) {
  let matched = false
  function visit(node) {
    if (ts.isIfStatement(node) && node.expression.getText(sourceFile) === '!driverId') {
      const text = node.thenStatement.getText(sourceFile)
      if (text.includes('app.exit(1)') && /\breturn\b/.test(text)) matched = true
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  assert.ok(matched, 'missing smoke-ID refusal and early return')
}

function assertSmokeBoundary(site) {
  const parsed = parseMainSource(site.source, site.relative)
  const driverId = declarations(parsed, 'driverId').find(node => node.initializer)
  const driverPath = declarations(parsed, 'driverPath').find(node => node.initializer)
  assert.equal(driverId?.initializer?.getText(parsed), 'process.env.ORDESSA_SMOKE_DRIVER_ID')
  assert.equal(driverPath?.initializer?.getText(parsed), 'await resolveSmokeDriver(driverId, app.getAppPath())')
  requireSmokeRefusal(parsed)
  assert.equal(site.argument, 'pathToFileURL(driverPath).href')
}

function assertNativeBoundary(site) {
  const parsed = parseMainSource(site.source, site.relative)
  assert.ok(calls(parsed, 'trusted').some(call => call.arguments[0]?.getText(parsed) === 'event'),
    'native open must validate the trusted renderer frame')
  const installed = declarations(parsed, 'installed').find(node => node.initializer)
  assert.equal(installed?.initializer?.getText(parsed), 'discovery.installed.get(adapterId)')
  requireIfThrow(parsed, '!installed?.manifest.native', 'native manifest entry')
  const filename = declarations(parsed, 'filename').find(node => node.initializer)
  assert.equal(filename?.initializer?.getText(parsed),
    'await confinedFile(installed.root, installed.manifest.native)')
  assert.equal(site.argument, 'pathToFileURL(filename).href')
}

function assertNativeConfinedFile(source) {
  const parsed = parseMainSource(source, 'packages/interfaces/channels/workbench/extension-runtime/host/src/main/extensions.ts')
  const functions = []
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && node.name?.text === 'confinedFile') functions.push(node)
    ts.forEachChild(node, visit)
  }
  visit(parsed)
  assert.equal(functions.length, 1, 'one real confinedFile implementation is required')
  const body = functions[0].body
  const text = body.getText(parsed)
  assert.ok(calls(parsed, 'realpath').some(call => call.arguments[0]?.getText(parsed) === 'root'),
    'native path must resolve the extension root')
  assert.ok(calls(parsed, 'path.join').some(call => call.arguments.map(arg => arg.getText(parsed)).join(', ') === 'base, relative'),
    'native path must resolve the relative entry under that root')
  requireIfThrow(parsed, '!safeRelative(relative)', 'relative native entry')
  const escapeCheck = text.includes("rel.startsWith('..' + path.sep)")
    && text.includes("rel === '..'") && text.includes('path.isAbsolute(rel)')
    && text.includes('!rel')
  assert.ok(escapeCheck && text.includes('Path escapes extension'),
    'native path must reject traversal and absolute realpath escapes')
  assert.ok(text.includes('stat(file)') && text.includes('isFile()'),
    'native entry must be a regular file')
}

function assertOnlyReviewedDynamicImports(sites, confinedFileSource) {
  const actual = sites.map(site => [site.relative, site.argument]).sort()
  assert.deepEqual(actual, [
    ['apps/desktop/electron/main.ts', 'pathToFileURL(driverPath).href'],
    ['apps/desktop/electron/native-bridge/src/index.ts', 'pathToFileURL(filename).href'],
  ])
  const smoke = sites.find(site => site.relative === 'apps/desktop/electron/main.ts')
  const native = sites.find(site => site.relative === 'apps/desktop/electron/native-bridge/src/index.ts')
  assertSmokeBoundary(smoke)
  assertNativeBoundary(native)
  assertNativeConfinedFile(confinedFileSource)
}

test('AST inventory uses one shared allowlist and source-boundary guard for both real sites and negatives', () => {
  const roots = [
    'apps/desktop/electron',
    'packages/interfaces/channels/workbench/extension-runtime/host/src/main',
  ]
  const sites = []
  for (const root of roots) {
    for (const file of walk(path.join(repoRoot, root))) {
      if (!/\.[cm]?js$|\.ts$/.test(file)) continue
      const relative = path.relative(repoRoot, file)
      const source = readFileSync(file, 'utf8')
      for (const item of dynamicImports(source, relative)) {
        if (!item.literal) sites.push({ relative, argument: item.argument, source })
      }
    }
  }
  const confinedFileSource = readFileSync(path.join(repoRoot,
    'packages/interfaces/channels/workbench/extension-runtime/host/src/main/extensions.ts'), 'utf8')
  assertOnlyReviewedDynamicImports(sites, confinedFileSource)

  // Each counterexample goes through the same inventory + source-boundary guard.
  const computed = dynamicImports('await import(pathToFileURL(userControlledPath).href)', 'untrusted.ts')
    .map(item => ({ relative: 'apps/desktop/electron/untrusted.ts', argument: item.argument, source: 'await import(pathToFileURL(userControlledPath).href)' }))
  assert.throws(() => assertOnlyReviewedDynamicImports([...sites, ...computed], confinedFileSource))

  const native = sites.find(site => site.relative === 'apps/desktop/electron/native-bridge/src/index.ts')
  const unconfinedNativeSource = native.source.replace(
    'await confinedFile(installed.root, installed.manifest.native)',
    'path.resolve(installed.root, installed.manifest.native)')
  const unconfinedNative = dynamicImports(unconfinedNativeSource, native.relative)
    .filter(item => !item.literal)
    .map(item => ({ relative: native.relative, argument: item.argument, source: unconfinedNativeSource }))
  assert.throws(() => assertOnlyReviewedDynamicImports([
    sites.find(site => site.relative === 'apps/desktop/electron/main.ts'), ...unconfinedNative,
  ], confinedFileSource))

  const weakenedConfinement = confinedFileSource.replace(
    "if (!rel || rel.startsWith('..' + path.sep) || rel === '..' || path.isAbsolute(rel)) throw Error('Path escapes extension')",
    '/* missing realpath escape rejection */')
  assert.throws(() => assertOnlyReviewedDynamicImports(sites, weakenedConfinement))
})
test('every direct Electron smoke launcher names the admitted fixture instead of supplying a path', () => {
  for (const relative of [
    'apps/desktop/tests/smoke/test-native-two-turn.mjs',
    'apps/desktop/tests/smoke/test-native-paired-no-send.mjs',
    'apps/desktop/tests/smoke/diagnose-empty-host-network.mjs',
  ]) {
    const source = readFileSync(path.join(repoRoot, relative), 'utf8')
    assert.match(source, /MODULAR_SMOKE:\s*'1',[\s\S]{0,100}ORDESSA_SMOKE_DRIVER_ID:\s*'smoke'/, relative)
  }
  const startupProbe = readFileSync(path.join(repoRoot,
    'apps/desktop/packaging/product/scripts/probe-startup-ui.mjs'), 'utf8')
  assert.match(startupProbe, /driverId:\s*'probe-startup-ui'/)
})

test('the renderer keeps its isolation posture (no global relaxation)', () => {
  const security = readFileSync(
    path.join(repoRoot, 'apps/desktop/electron/security.ts'), 'utf8')
  assert.match(security, /contextIsolation:\s*true/)
  assert.match(security, /nodeIntegration:\s*false/)
  assert.match(security, /sandbox:\s*true/)
})
