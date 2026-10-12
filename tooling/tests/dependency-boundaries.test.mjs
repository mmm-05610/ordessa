import assert from 'node:assert/strict'
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { scanDependencyBoundaries } from '../checks/dependency-boundaries.mjs'
import { readFile } from 'node:fs/promises'

test('shared package policy rejects empty rules, boolean schema and unknown fields', async t => {
  const rootDir = await baseFixture(t)
  const original = JSON.parse(await readFile(new URL('../checks/package-boundaries.json', import.meta.url), 'utf8'))
  for (const update of [{ schema_version: true }, { denied_edges: [] }, { retired_paths: [] }, { ignored: true }]) {
    await writeJson(rootDir, 'policy.json', { ...original, ...update })
    const report = await scanDependencyBoundaries(rootDir, { policyPath: path.join(rootDir, 'policy.json') })
    assert.equal(report.status, 'FAIL')
    assert.ok(report.errors.some(item => item.kind === 'invalid-package-boundary-policy'), JSON.stringify(update))
  }
})

test('a symlinked retired owner parent cannot hide an absent retired entry', async t => {
  const rootDir = await baseFixture(t)
  await symlink(path.join(rootDir, 'apps'), path.join(rootDir, 'packages/execution'), 'dir')
  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'FAIL')
  assert.ok(report.errors.some(item => item.kind === 'retired-package-path-invalid'))
})

async function convergenceFixture(t) {
  const rootDir = await baseFixture(t)
  await writeJson(rootDir, 'package.json', { workspaces: ['apps/**', 'packages/**', 'plugins/**'] })
  for (const [rel, name] of [
    ['packages/infrastructure', '@fixture/infrastructure'],
    ['packages/execution/units', '@fixture/units'],
    ['packages/execution/agents', '@fixture/agents'],
    ['packages/execution/environments', '@fixture/environments'],
    ['packages/execution/decision', '@fixture/decision'],
    ['packages/engineering', '@fixture/engineering'],
    ['packages/interfaces/channels/cli', '@fixture/channel'],
    ['packages/interfaces/transport/server', '@fixture/transport'],
    ['packages/interfaces/system-access', '@fixture/system-access'],
    ['packages/interfaces/contracts', '@fixture/contracts'],
  ]) {
    await addWorkspace(rootDir, rel, name, { '.': './src/index.ts' })
    await writeFileAt(rootDir, `${rel}/src/index.ts`, 'export type Value = string\n')
  }
  return rootDir
}

test('approved package directions keep native owner interfaces and injected assembly', async t => {
  const rootDir = await convergenceFixture(t)
  await writeFileAt(rootDir, 'packages/execution/units/src/index.ts',
    "import type { Value } from '@fixture/agents'; import type { Value as Env } from '@fixture/environments'; export type Unit = Value | Env\n")
  await writeFileAt(rootDir, 'packages/engineering/src/ordessa_engineering/adapters/agents/index.ts',
    "import type { Unit } from '@fixture/units'; export type Worker = Unit\n")
  await writeFileAt(rootDir, 'packages/engineering/src/ordessa_engineering/domain/index.ts',
    "import type { Value } from '@fixture/infrastructure'; export type Fact = Value\n")
  await writeFileAt(rootDir, 'packages/interfaces/transport/server/src/index.ts',
    "import type { Value } from '@fixture/contracts'; export type Transport = Value\n")
  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'PASS_BOUNDED', JSON.stringify(report))
})

test('package rules catch type-only business reverse imports and internal engineering edges', async t => {
  const rootDir = await convergenceFixture(t)
  await writeFileAt(rootDir, 'packages/infrastructure/src/index.ts', "import type { Value } from '@fixture/units'\n")
  await writeFileAt(rootDir, 'packages/execution/decision/src/index.ts', "import type { Value } from '@fixture/agents'\n")
  await writeFileAt(rootDir, 'packages/execution/agents/src/index.ts', "import type { Value } from '@fixture/decision'\n")
  await writeFileAt(rootDir, 'packages/execution/environments/src/index.ts', "import type { Value } from '@fixture/contracts'\n")
  await writeFileAt(rootDir, 'packages/engineering/src/ordessa_engineering/methods/index.ts',
    "import type { Fact } from '../domain/index'\n")
  await writeFileAt(rootDir, 'packages/engineering/src/ordessa_engineering/domain/index.ts',
    "import type { Method } from '../methods/index'\nimport type { Service } from '../application/index'\nexport type Fact = string\n")
  await writeFileAt(rootDir, 'packages/engineering/src/ordessa_engineering/application/index.ts',
    "import type { Value } from '@fixture/units'\nimport type { Adapter } from '../adapters/index'\n")
  await writeFileAt(rootDir, 'packages/engineering/src/ordessa_engineering/adapters/index.ts', 'export type Adapter = string\n')
  await writeFileAt(rootDir, 'packages/interfaces/channels/cli/src/index.ts', "import type { Value } from '@fixture/units'\n")
  await writeFileAt(rootDir, 'packages/interfaces/transport/server/src/index.ts', "import type { Value } from '@fixture/system-access'\n")
  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'FAIL')
  assert.deepEqual(report.errors, [])
  const rules = new Set(report.violations.map(item => item.rule))
  for (const expected of [
    'infrastructure_must_not_import_business', 'execution_must_not_import_engineering_or_interfaces',
    'decision_is_independent_of_other_execution_owners', 'execution_owners_must_not_import_decision',
    'domain_must_not_import_methods', 'methods_must_not_import_domain',
    'engineering_foundations_must_not_import_upper_owners', 'application_uses_injected_ports',
    'channels_use_public_system_contracts', 'transport_uses_injected_system_access',
  ]) assert.ok(rules.has(expected), expected)
})

test('package matrix also checks declared npm dependencies', async t => {
  const rootDir = await convergenceFixture(t)
  await writeJson(rootDir, 'packages/infrastructure/package.json', {
    name: '@fixture/infrastructure', exports: './src/index.ts', dependencies: { '@fixture/units': '*' },
  })
  const report = await scanDependencyBoundaries(rootDir)
  assert.ok(report.violations.some(item => item.kind === 'package-boundary-dependency' &&
    item.rule === 'infrastructure_must_not_import_business'))
})

test('retired identities fail even when no retired workspace can be discovered', async t => {
  const rootDir = await baseFixture(t)
  await writeFileAt(rootDir, 'packages/core/src/retired.ts',
    "import type { Value } from 'pacthold'; void import('ordessa_execution_api.unit'); require('ordessa-execution-api')\n")
  await writeJson(rootDir, 'packages/core/package.json', {
    name: '@fixture/core', exports: './src/index.ts', dependencies: { 'disguised': 'npm:ordessa-execution-api@1.0.0' },
  })
  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'FAIL')
  assert.equal(report.violations.filter(item => item.kind === 'retired-package-import').length, 3)
  assert.ok(report.violations.some(item => item.kind === 'retired-package-dependency' && item.dependency === 'disguised'))
})

test('retired source and Python metadata fail outside npm workspace discovery', async t => {
  const rootDir = await baseFixture(t)
  await writeFileAt(rootDir, 'packages/interfaces/execution/c1-api/pyproject.toml', '[project]\nname="ordessa-execution-api"\n')
  await writeFileAt(rootDir, 'packages/execution/kernel/src/pacthold/__init__.py', '')
  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'FAIL')
  assert.equal(report.errors.filter(item => item.kind === 'retired-package-content').length, 2)
})

test('package policy missing or malformed refuses a clean result', async t => {
  const rootDir = await baseFixture(t)
  let report = await scanDependencyBoundaries(rootDir, { policyPath: path.join(rootDir, 'missing-policy.json') })
  assert.equal(report.status, 'FAIL')
  assert.ok(report.errors.some(item => item.kind === 'invalid-json'))
  await writeJson(rootDir, 'invalid-policy.json', { schema_version: 2, denied_edges: [] })
  report = await scanDependencyBoundaries(rootDir, { policyPath: path.join(rootDir, 'invalid-policy.json') })
  assert.equal(report.status, 'FAIL')
  assert.ok(report.errors.some(item => item.kind === 'invalid-package-boundary-policy'))
})

async function fixture(t) {
  const rootDir = await mkdtemp(path.join(os.tmpdir(), 'ordessa-boundaries-'))
  t.after(() => rm(rootDir, { recursive: true, force: true }))
  await writeJson(rootDir, 'package.json', { workspaces: ['apps/*', 'packages/*', 'plugins/*', 'apps/server/deployment/default-product'] })
  await mkdir(path.join(rootDir, 'apps'), { recursive: true })
  await writeFileAt(rootDir, 'apps/server/deployment/default-product/pyproject.toml',
    '[project]\nname = "fixture-default-product"\nversion = "0.1.0"\n')
  return rootDir
}

async function writeFileAt(rootDir, rel, contents) {
  const filePath = path.join(rootDir, rel)
  await mkdir(path.dirname(filePath), { recursive: true })
  await writeFile(filePath, contents)
}

async function writeJson(rootDir, rel, value) {
  await writeFileAt(rootDir, rel, JSON.stringify(value))
}

async function addWorkspace(rootDir, rel, name, exports) {
  await writeJson(rootDir, `${rel}/package.json`, { name, exports })
}

async function baseFixture(t) {
  const rootDir = await fixture(t)
  await addWorkspace(rootDir, 'packages/core', '@fixture/core', {
    '.': { types: './src/index.ts', import: './src/index.ts', require: './src/index.ts' },
  })
  await addWorkspace(rootDir, 'plugins/feature', '@fixture/plugin', {
    '.': { types: './src/index.ts', import: './src/index.ts', require: './src/index.ts' },
  })
  await addWorkspace(rootDir, 'apps/server', '@fixture/server', { '.': './src/server.ts' })
  await addWorkspace(rootDir, 'apps/server/deployment/default-product', '@fixture/assembly', './src/index.ts')
  await writeFileAt(rootDir, 'apps/server/deployment/default-product/src/index.ts', 'export const owner = 1\n')
  await writeFileAt(rootDir, 'packages/core/src/index.ts', 'export const core = true\n')
  await writeFileAt(rootDir, 'plugins/feature/src/index.ts', "import { core } from '@fixture/core'; export { core }\n")
  await writeFileAt(rootDir, 'apps/server/src/server.ts', 'export const server = true\n')
  await writeFileAt(rootDir, 'apps/server/src/data.json', '{"layout": "stable"}\n')
  return rootDir
}

test('allows imports from a plugin to a public workspace package', async t => {
  const rootDir = await baseFixture(t)
  const report = await scanDependencyBoundaries(rootDir)

  assert.equal(report.status, 'PASS_BOUNDED')
  assert.deepEqual(report.errors, [])
  assert.deepEqual(report.violations, [])
  assert.ok(report.importsScanned > 0)
})

test('detects relative, workspace-name, path-alias, and JSON imports into apps', async t => {
  const rootDir = await baseFixture(t)
  await writeJson(rootDir, 'packages/core/tsconfig.json', {
    compilerOptions: { baseUrl: '.', paths: { '@fixture/app/*': ['../../apps/server/*'] } },
  })
  await writeFileAt(rootDir, 'packages/core/src/forbidden.ts', [
    "import { server } from '../../../apps/server/src/server'",
    "export { server as reexported } from '../../../apps/server/src/server'",
    "void import('../../../apps/server/src/server')",
    "const required = require('../../../apps/server/src/server')",
    "import { server as named } from '@fixture/server'",
    "import { server as aliased } from '@fixture/app/src/server'",
    "import layout from '../../../apps/server/src/data.json'",
    'void [server, named, aliased, layout]',
  ].join('\n'))
  await writeFileAt(rootDir, 'packages/core/src/plugin-edge.ts', "import { core } from '@fixture/plugin'; void core\n")

  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'FAIL')
  assert.ok(report.violations.some(item => item.kind === 'lower-layer-imports-app' && item.target.endsWith('apps/server/src/server.ts')))
  assert.ok(report.violations.some(item => item.kind === 'lower-layer-imports-app' && item.target.endsWith('apps/server/src/data.json')))
  assert.ok(report.violations.some(item => item.kind === 'public-package-imports-plugin' && item.target.endsWith('plugins/feature/src/index.ts')))
  assert.ok(report.violations.some(item => item.specifier === '@fixture/app/src/server'))
  assert.ok(report.violations.some(item => item.specifier === "../../../apps/server/src/server"))
  assert.deepEqual(report.errors, [])
})

test('every current source owner root is required and malformed source fails', async t => {
  for (const missing of ['packages', 'plugins', 'apps']) {
    const rootDir = await fixture(t)
    await mkdir(path.join(rootDir, 'packages'), { recursive: true })
    await mkdir(path.join(rootDir, 'plugins'), { recursive: true })
    await mkdir(path.join(rootDir, 'apps'), { recursive: true })
    await rm(path.join(rootDir, missing), { recursive: true, force: true })
    const report = await scanDependencyBoundaries(rootDir)
    assert.equal(report.status, 'FAIL')
    assert.ok(report.errors.some(item => item.kind === 'missing-scan-root' && item.file.endsWith(`/${missing}`)))
    await rm(rootDir, { recursive: true, force: true })
  }

  const rootDir = await fixture(t)
  await mkdir(path.join(rootDir, 'packages'), { recursive: true })
  await mkdir(path.join(rootDir, 'plugins'), { recursive: true })
  await mkdir(path.join(rootDir, 'apps'), { recursive: true })
  await writeFileAt(rootDir, 'packages/core.ts', 'export const = ;\n')
  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'FAIL')
  assert.ok(report.errors.some(item => item.kind === 'syntax-error' && item.file.endsWith('/packages/core.ts')))
})

test('unresolved workspace imports fail and computed dynamic imports are reported partial', async t => {
  const rootDir = await baseFixture(t)
  await writeFileAt(rootDir, 'packages/core/src/unresolved.ts', [
    "import { missing } from '@fixture/missing'",
    "const selected = './index'; void import(selected)",
  ].join('\n'))

  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'FAIL')
  assert.ok(report.errors.some(item => item.kind === 'unresolved-local-resource' && item.specifier === '@fixture/missing'))
  assert.ok(report.unresolvedDynamic.some(item => item.kind === 'non-literal-dynamic-import'))
  assert.ok(report.limitations.some(item => item.includes('Non-literal dynamic import')))
})

test('computed dynamic imports prevent a complete status even without static violations', async t => {
  const rootDir = await fixture(t)
  await writeFileAt(rootDir, 'packages/source/runtime.ts', "const selected = './module'; void import(selected)\n")
  await mkdir(path.join(rootDir, 'plugins'), { recursive: true })

  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'PARTIAL')
  assert.deepEqual(report.errors, [])
  assert.deepEqual(report.violations, [])
  assert.equal(report.unresolvedDynamic.length, 1)
})

test('computed require calls stay visible as unresolved dynamic edges', async t => {
  const rootDir = await fixture(t)
  await writeFileAt(rootDir, 'packages/source/runtime.ts', "const selected = './module'; require(selected)\n")
  await mkdir(path.join(rootDir, 'plugins'), { recursive: true })

  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'PARTIAL')
  assert.deepEqual(report.errors, [])
  assert.deepEqual(report.violations, [])
  assert.equal(report.unresolvedDynamic.length, 1)
  assert.deepEqual(report.unresolvedDynamic[0], {
    file: path.join(rootDir, 'packages/source/runtime.ts'),
    line: 1,
    kind: 'non-literal-require',
    expression: 'selected',
  })
})


test('apps-owned product composition is a host boundary and deleting its entry fails', async t => {
  const rootDir = await baseFixture(t)
  await writeFileAt(rootDir, 'packages/core/src/host.ts', "import {owner} from '@fixture/assembly'\n")
  let report = await scanDependencyBoundaries(rootDir)
  assert.ok(report.violations.some(item => item.kind === 'lower-layer-imports-app'
    && item.target.endsWith('apps/server/deployment/default-product/src/index.ts')))
  await rm(path.join(rootDir, 'apps/server/deployment/default-product'), { recursive: true })
  report = await scanDependencyBoundaries(rootDir)
  assert.ok(report.errors.some(item => item.kind === 'missing-default-product-entry'))
})

test('retired products root is optional but revived source and metadata fail closed', async t => {
  const rootDir = await baseFixture(t)
  assert.equal((await scanDependencyBoundaries(rootDir)).errors.length, 0)
  await mkdir(path.join(rootDir, 'products'), { recursive: true })
  assert.equal((await scanDependencyBoundaries(rootDir)).errors.length, 0)
  await writeFileAt(rootDir, 'products/desktop/electron/main.mjs', 'export const oldProduct = true\n')
  const report = await scanDependencyBoundaries(rootDir)
  assert.ok(report.errors.some(item => item.kind === 'retired-products-active-content'
    && item.file.endsWith('products/desktop/electron/main.mjs')))
})

test('retired products manifests and symlinks fail closed', async t => {
  const rootDir = await baseFixture(t)
  await writeJson(rootDir, 'products/desktop/package.json', { name: '@fixture/retired-desktop' })
  let report = await scanDependencyBoundaries(rootDir)
  assert.ok(report.errors.some(item => item.kind === 'retired-products-active-content'
    && item.file.endsWith('products/desktop/package.json')))
  await rm(path.join(rootDir, 'products'), { recursive: true, force: true })
  await mkdir(path.join(rootDir, 'products'), { recursive: true })
  await symlink(path.join(rootDir, 'apps'), path.join(rootDir, 'products/apps-link'))
  report = await scanDependencyBoundaries(rootDir)
  assert.ok(report.errors.some(item => item.kind === 'retired-products-active-content'
    && item.file.endsWith('products/apps-link')))
})

test('missing apps-owned default product entry or metadata fails closed', async t => {
  for (const removed of ['directory', 'metadata']) {
    const rootDir = await baseFixture(t)
    const defaultProduct = path.join(rootDir, 'apps/server/deployment/default-product')
    if (removed === 'directory') await rm(defaultProduct, { recursive: true })
    else await rm(path.join(defaultProduct, 'pyproject.toml'))
    const report = await scanDependencyBoundaries(rootDir)
    assert.ok(report.errors.some(item => item.kind === 'missing-default-product-entry'))
    await rm(rootDir, { recursive: true, force: true })
  }
})

test('declarations are scanned without emission and malformed declarations fail', async t => {
  const rootDir = await baseFixture(t)
  await writeFileAt(rootDir, 'packages/core/src/host.d.ts', "export {server} from '@fixture/server'\n")
  let report = await scanDependencyBoundaries(rootDir)
  assert.ok(report.violations.some(item => item.file.endsWith('host.d.ts') && item.target.startsWith('apps/')))
  assert.deepEqual(report.errors, [])
  await writeFileAt(rootDir, 'packages/core/src/broken.d.ts', 'export declare const : ;\n')
  report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'FAIL')
  assert.ok(report.errors.some(item => item.kind === 'syntax-error' && item.file.endsWith('broken.d.ts')))
})

test('workspace manifests reject lower-layer app edges and package-to-plugin edges', async t => {
  const rootDir = await baseFixture(t)

  await writeJson(rootDir, 'packages/core/package.json', {
    name: '@fixture/core',
    exports: { '.': { types: './src/index.ts', import: './src/index.ts', require: './src/index.ts' } },
    dependencies: { '@fixture/server': '*' },
    devDependencies: { '@fixture/assembly': '*' },
    optionalDependencies: { '@fixture/plugin': '*' },
  })
  await writeJson(rootDir, 'plugins/feature/package.json', {
    name: '@fixture/plugin',
    exports: { '.': './src/index.ts' },
    dependencies: { '@fixture/core': '*' },
    optionalDependencies: { '@fixture/server': '*' },
    peerDependencies: { '@fixture/assembly': '*' },
  })

  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'FAIL')
  const edges = report.violations.filter(item => item.file.endsWith('package.json'))
  assert.ok(edges.some(item => item.kind === 'workspace-depends-on-app' && item.file === 'packages/core/package.json'
    && item.section === 'dependencies' && item.target === 'apps/server'))
  assert.ok(edges.some(item => item.kind === 'workspace-depends-on-app' && item.file === 'packages/core/package.json'
    && item.section === 'devDependencies' && item.target === 'apps/server/deployment/default-product'))
  assert.ok(edges.some(item => item.kind === 'public-package-depends-on-plugin'
    && item.file === 'packages/core/package.json' && item.section === 'optionalDependencies'
    && item.target === 'plugins/feature'))
  assert.ok(edges.some(item => item.kind === 'workspace-depends-on-app' && item.file === 'plugins/feature/package.json'
    && item.section === 'optionalDependencies' && item.target === 'apps/server'))
  assert.ok(edges.some(item => item.kind === 'workspace-depends-on-app' && item.file === 'plugins/feature/package.json'
    && item.section === 'peerDependencies' && item.target === 'apps/server/deployment/default-product'))
  assert.equal(edges.some(item => item.file === 'plugins/feature/package.json' && item.target === 'packages/core'), false,
    'plugin-to-public-package dependency is allowed')
})

test('manifest dependency sections and npm workspace aliases fail closed when malformed or unresolved', async t => {
  const rootDir = await baseFixture(t)
  await writeJson(rootDir, 'packages/core/package.json', {
    name: '@fixture/core',
    dependencies: ['@fixture/server'],
    devDependencies: { broken: 7 },
  })
  await writeJson(rootDir, 'plugins/feature/package.json', {
    name: '@fixture/plugin',
    dependencies: { missing: 'workspace:*' },
    optionalDependencies: { alias: 'npm:@fixture/missing@workspace:*' },
  })

  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'FAIL')
  assert.ok(report.errors.some(item => item.kind === 'invalid-workspace-dependencies'
    && item.file === 'packages/core/package.json' && item.section === 'dependencies'))
  assert.ok(report.errors.some(item => item.kind === 'invalid-workspace-dependency-specifier'
    && item.file === 'packages/core/package.json' && item.section === 'devDependencies' && item.dependency === 'broken'))
  assert.ok(report.errors.some(item => item.kind === 'unresolved-workspace-dependency'
    && item.file === 'plugins/feature/package.json' && item.dependency === 'missing'))
  assert.ok(report.errors.some(item => item.kind === 'unresolved-workspace-dependency'
    && item.file === 'plugins/feature/package.json' && item.dependency === 'alias'))
})

test('npm aliases to enumerated workspaces are classified by their target package name', async t => {
  const rootDir = await baseFixture(t)
  await writeJson(rootDir, 'plugins/feature/package.json', {
    name: '@fixture/plugin',
    dependencies: { 'core-alias': 'npm:@fixture/core@workspace:*' },
  })

  const report = await scanDependencyBoundaries(rootDir)
  assert.deepEqual(report.errors, [])
  assert.deepEqual(report.violations, [])
  assert.equal(report.status, 'PASS_BOUNDED')
})

test('local and rewritten dependency aliases cannot masquerade as external packages', async t => {
  const rootDir = await baseFixture(t)
  await writeJson(rootDir, 'packages/core/package.json', {
    name: '@fixture/core', dependencies: {
      alias: 'file:../../plugins/feature', link: 'link:../../apps/server',
      portal: 'portal:../../apps/server/deployment/default-product', rewritten: 'patch:plugin@1#patch.diff',
    },
  })
  const report = await scanDependencyBoundaries(rootDir)
  assert.equal(report.status, 'FAIL')
  assert.equal(report.errors.filter(item => item.kind === 'unresolved-workspace-dependency').length, 4)
})


test('CSS resources retain ownership edges and missing CSS fails closed', async t => {
  const rootDir = await baseFixture(t)
  await writeFileAt(rootDir, 'packages/core/src/theme.css', 'body { color: black; }\n')
  await writeFileAt(rootDir, 'packages/core/src/style.ts', "import './theme.css'\n")
  let report = await scanDependencyBoundaries(rootDir)
  assert.deepEqual(report.errors, [])
  assert.deepEqual(report.violations, [])
  await writeFileAt(rootDir, 'apps/server/src/host.css', 'body {}\n')
  await writeFileAt(rootDir, 'packages/core/src/style.ts', "import '../../../apps/server/src/host.css'\nimport './absent.css'\n")
  report = await scanDependencyBoundaries(rootDir)
  assert.ok(report.violations.some(row => row.kind === 'lower-layer-imports-app' && row.target.endsWith('/host.css')))
  assert.ok(report.errors.some(row => row.kind === 'unresolved-local-resource' && row.specifier === './absent.css'))
})
