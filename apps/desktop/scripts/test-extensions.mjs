import assert from 'node:assert/strict'
import { mkdtemp, mkdir, cp, writeFile, readFile, readdir, rm } from 'node:fs/promises'
import path from 'node:path'
import { tmpdir } from 'node:os'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { launchSmoke } from './launch-smoke.mjs'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
async function digest(dir) {
  const hash = createHash('sha256')
  async function walk(folder) {
    for (const file of (await readdir(folder, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      const target = path.join(folder, file.name)
      if (file.isDirectory()) await walk(target)
      else { hash.update(path.relative(dir, target)); hash.update(await readFile(target)) }
    }
  }
  await walk(dir)
  return hash.digest('hex')
}
const build = path.join(root, 'apps/desktop/dist')
const before = await digest(build)
const home = await mkdtemp(path.join(tmpdir(), 'ordessa-extension-smoke-'))
const reports = []
const extensions = path.join(home, 'extensions')
const foundations = ['ordessa.contracts', 'ordessa.commands', 'ordessa.workbench']
async function enable(ids) { await writeFile(path.join(home, 'extensions.json'), JSON.stringify({ enabled: ids.length ? [...foundations, ...ids] : [] })) }
async function install(id, folder = id) { await cp(path.join(root, 'examples/dist', id), path.join(extensions, folder), { recursive: true }) }
async function check(name, expected, verify = () => {}) {
  const result = await launchSmoke(home)
  const exitMarker = JSON.parse(await readFile(path.join(home, '.ordessa/state/session.json'), 'utf8'))
  assert.equal(exitMarker.clean, true, 'Smoke must run host cleanup before a same-root restart')
  assert.equal(result.ready, true); assert.equal(result.nodeAbsent, true)
  assert.deepEqual(result.bridgeKeys, ['read'])
  assert.deepEqual(result.pages.sort(), expected.sort())
  verify(result)
  assert.equal(await digest(build), before, 'Host build changed during extension installation')
  reports.push({ name, ...result })
}
try {
  await mkdir(extensions)
  for (const id of foundations) await cp(path.join(root, 'products/desktop/dist/extensions', id), path.join(extensions, id), { recursive: true })
  await check('empty', [], r => assert.deepEqual(r.errors, []))
  await install('example.hello')
  await check('discovered but not approved', [], r => assert.deepEqual(r.errors, []))
  await enable(['example.hello'])
  await check('enabled standalone React Hook page', ['Hello'], r => {
    assert.ok(r.views.some(v => v.includes('Count: 1')), 'Shared React hook did not update')
    assert.deepEqual(r.errors, [])
  })
  await install('example.contracts'); await install('example.provider'); await install('example.consumer')
  await enable(['example.contracts', 'example.consumer', 'example.hello', 'example.provider'])
  await check('shared contract token across separate bundles', ['Hello', 'Service'], r => {
    assert.ok(r.views.some(v => v.includes('Shared token connected')))
    assert.deepEqual(r.errors, [])
  })
  const consumerDigest = await digest(path.join(extensions, 'example.consumer'))
  await rm(path.join(extensions, 'example.provider'), { recursive: true })
  await install('example.provider-alt')
  await enable(['example.contracts', 'example.consumer', 'example.hello', 'example.provider-alt'])
  await check('replace provider without changing consumer', ['Hello', 'Service'], r => {
    assert.ok(r.views.some(v => v.includes('Replacement provider connected')))
    assert.deepEqual(r.errors, [])
  })
  assert.equal(await digest(path.join(extensions, 'example.consumer')), consumerDigest)
  await mkdir(path.join(extensions, 'slow'))
  await writeFile(path.join(extensions, 'slow/manifest.json'), JSON.stringify({ id: 'example.slow', version: '0.1.0', hostApi: '2', entry: 'entry.js' }))
  await writeFile(path.join(extensions, 'slow/entry.js'), 'export default () => ({id:"example.slow", autoStart:true, activate:() => new Promise(()=>{})})')
  await enable(['example.slow', 'example.hello'])
  await check('pending activation does not block shell or healthy extension', ['Hello'], r => {
    assert.ok(r.starting.some(s => s.includes('example.slow')))
    assert.ok(r.views.some(v => v.includes('Count: 1')))
    assert.deepEqual(r.errors, [])
  })
  await enable([])
  await check('disabled after restart', [], r => assert.deepEqual(r.errors, []))
  await mkdir(path.join(extensions, 'broken'))
  await writeFile(path.join(extensions, 'broken/manifest.json'), JSON.stringify({ id: 'example.broken', version: '0.1.0', hostApi: '2', entry: 'entry.js' }))
  await writeFile(path.join(extensions, 'broken/entry.js'), 'this is invalid javascript !!')
  await enable(['example.hello', 'example.broken'])
  await check('malformed module does not stop healthy plugin', ['Hello'], r => assert.ok(r.errors.some(e => e.includes('example.broken'))))
  await install('example.hello', 'duplicate')
  await enable(['example.hello', 'example.contracts', 'example.provider-alt', 'example.consumer'])
  await check('duplicate identity rejected, unrelated plugins work', ['Service'], r => assert.ok(r.errors.some(e => e.includes('Duplicate extension id'))))
  assert.equal(await digest(build), before)
  console.log(JSON.stringify({ hostDigest: before, hostUnchanged: true, cases: reports }, null, 2))
} finally { await rm(home, { recursive: true, force: true }) }
