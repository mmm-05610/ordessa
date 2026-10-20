import { afterEach, beforeEach, expect, it } from 'vitest'
import * as ts from 'typescript'
import { copyFile, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { resolveSmokeDriver, SMOKE_DRIVER_ADMISSIONS } from '../electron/smoke-driver-admission'
import { buildSmokeEnvironment } from './support/launch-smoke.mjs'

// This test is collected from apps/desktop/tests; its parent is the Electron app root.
const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const fixtureSource = path.join(desktopRoot, 'tests/fixtures')
let appRoot = ''
let outsideRoot = ''
const admittedFiles = ['smoke-driver.mjs', 'smoke-agent.mjs', 'smoke-ui.mjs', 'probe-startup-ui-driver.mjs']

beforeEach(async () => {
  appRoot = await mkdtemp(path.join(tmpdir(), 'ordessa-smoke-admission-'))
  outsideRoot = await mkdtemp(path.join(tmpdir(), 'ordessa-smoke-outside-'))
  const target = path.join(appRoot, 'tests/fixtures')
  await mkdir(target, { recursive: true })
  for (const name of admittedFiles) await copyFile(path.join(fixtureSource, name), path.join(target, name))
})
afterEach(async () => {
  if (appRoot) await rm(appRoot, { recursive: true, force: true })
  if (outsideRoot) await rm(outsideRoot, { recursive: true, force: true })
})

function fixtureImports(source: string): string[] {
  const imports: string[] = []
  const parsed = ts.createSourceFile('fixture.mjs', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  function visit(node: ts.Node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier) {
      if (!ts.isStringLiteral(node.moduleSpecifier)) throw Error('nonliteral fixture module specifier')
      imports.push(node.moduleSpecifier.text)
    }
    if (ts.isCallExpression(node)) {
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword) {
        const argument = node.arguments[0]
        if (!argument || !(ts.isStringLiteral(argument) || ts.isNoSubstitutionTemplateLiteral(argument))) {
          throw Error(`nonliteral fixture import: ${argument ? argument.getText(parsed) : '<missing>'}`)
        }
        imports.push(argument.text)
      } else if (ts.isIdentifier(node.expression) && node.expression.text === 'require') {
        const argument = node.arguments[0]
        if (!argument || !(ts.isStringLiteral(argument) || ts.isNoSubstitutionTemplateLiteral(argument))) {
          throw Error(`nonliteral fixture require: ${argument ? argument.getText(parsed) : '<missing>'}`)
        }
        imports.push(argument.text)
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(parsed)
  return imports
}
function assertLocalImportsAdmitted(file: string, source: string, closure: Set<string>) {
  for (const specifier of fixtureImports(source)) {
    if (!specifier.startsWith('.')) continue
    const target = path.posix.normalize(path.posix.join(path.posix.dirname(file), specifier))
    expect(closure.has(target), `${file} imports unadmitted ${target}`).toBe(true)
  }
}

it('admits only the named Root-reviewed fixture and its exact source closure', async () => {
  expect(await resolveSmokeDriver('smoke', appRoot)).toBe(path.join(appRoot, 'tests/fixtures/smoke-driver.mjs'))
  expect(await resolveSmokeDriver('probe-startup-ui', appRoot)).toBe(path.join(appRoot, 'tests/fixtures/probe-startup-ui-driver.mjs'))
})

it('uses TypeScript AST to cover static, literal dynamic and require edges; rejects computed imports', async () => {
  for (const admission of Object.values(SMOKE_DRIVER_ADMISSIONS)) {
    const closure = new Set(admission.files.map(file => file.relative))
    expect(closure.has(admission.entry)).toBe(true)
    for (const file of admission.files) {
      const source = await readFile(path.join(desktopRoot, file.relative), 'utf8')
      assertLocalImportsAdmitted(file.relative, source, closure)
    }
  }
  const syntheticClosure = new Set(['tests/fixtures/entry.mjs'])
  expect(() => assertLocalImportsAdmitted('tests/fixtures/entry.mjs',
    "void import('./unlisted.mjs')", syntheticClosure)).toThrow()
  expect(() => fixtureImports('void import(driverPath)')).toThrow('nonliteral fixture import')
  expect(() => fixtureImports('void import(`./${name}.mjs`)')).toThrow('nonliteral fixture import')
  expect(() => fixtureImports('require(target)')).toThrow('nonliteral fixture require')
  expect(fixtureImports("export { value } from './declared.mjs'; void import('./declared-too.mjs')")).toEqual(['./declared.mjs', './declared-too.mjs'])
})

it('rejects missing or unknown driver IDs before import', async () => {
  await expect(resolveSmokeDriver(undefined, appRoot)).rejects.toMatchObject({ code: 'SMOKE_DRIVER_NOT_ADMITTED' })
  await expect(resolveSmokeDriver('../host-source.mjs', appRoot)).rejects.toMatchObject({ code: 'SMOKE_DRIVER_NOT_ADMITTED' })
})

it('rejects a missing transitive fixture source', async () => {
  await rm(path.join(appRoot, 'tests/fixtures/smoke-ui.mjs'))
  await expect(resolveSmokeDriver('smoke', appRoot)).rejects.toMatchObject({ code: 'SMOKE_DRIVER_SOURCE_MISSING' })
})

it('rejects changed entry or transitive bytes', async () => {
  await writeFile(path.join(appRoot, 'tests/fixtures/smoke-agent.mjs'), 'export async function verifyAgentUI() {}\n')
  await expect(resolveSmokeDriver('smoke', appRoot)).rejects.toMatchObject({ code: 'SMOKE_DRIVER_SOURCE_MISMATCH' })
})

it('rejects a fixture symlink whose target is actually outside the app root', async () => {
  const entry = path.join(appRoot, 'tests/fixtures/probe-startup-ui-driver.mjs')
  await rm(entry)
  const outside = path.join(outsideRoot, 'outside-driver.mjs')
  await writeFile(outside, 'export async function runSmoke() {}\n')
  const relative = path.relative(appRoot, outside)
  expect(relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)).toBe(true)
  await symlink(outside, entry)
  await expect(resolveSmokeDriver('probe-startup-ui', appRoot)).rejects.toMatchObject({ code: 'SMOKE_DRIVER_PATH_ESCAPE' })
})

it('rejects path and ID overrides through extraEnv; caller selects only the finite driver ID option', () => {
  expect(buildSmokeEnvironment('/tmp/private-home').ORDESSA_SMOKE_DRIVER_ID).toBe('smoke')
  expect(buildSmokeEnvironment('/tmp/private-home', {}, 'probe-startup-ui').ORDESSA_SMOKE_DRIVER_ID).toBe('probe-startup-ui')
  for (const extra of [
    { ORDESSA_SMOKE_DRIVER: '/etc/passwd' },
    { ORDESSA_SMOKE_DRIVER_ID: '../host-source.mjs' },
    { MODULAR_SMOKE: '0' },
  ]) expect(() => buildSmokeEnvironment('/tmp/private-home', extra)).toThrow('SMOKE_DRIVER_ENV_OVERRIDE_REFUSED')
  expect(() => Reflect.apply(buildSmokeEnvironment, undefined, ['/tmp/private-home', {}, '../host-source.mjs'])).toThrow('SMOKE_DRIVER_NOT_ADMITTED')
})
