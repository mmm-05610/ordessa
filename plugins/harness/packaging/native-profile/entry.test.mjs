import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { spawnSync } from 'node:child_process'

for (const brand of ['codex', 'claude-code']) {
  test(`${brand}: isolated entry refuses unsafe directories before upstream evaluation`, t => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ordessa-native-entry-'))
    t.after(() => fs.rmSync(root, { recursive: true, force: true }))
    const upstream = path.join(root, 'index.js')
    const marker = path.join(root, 'evaluated')
    fs.writeFileSync(upstream, `require('node:fs').writeFileSync(${JSON.stringify(marker)}, 'yes')`)
    const entry = path.join(root, 'ordessa-profile.mjs')
    fs.writeFileSync(entry, fs.readFileSync(new URL('./entry.mjs', import.meta.url), 'utf8').replace('__ORDESSA_NATIVE_BRAND__', brand))
    const instance = path.join(root, 'instance'); fs.mkdirSync(instance, { mode: 0o700 })
    const link = path.join(root, 'link'); fs.symlinkSync(instance, link)
    const run = directory => spawnSync(process.execPath, [entry], { encoding: 'utf8',
      env: { PATH: process.env.PATH, HOME: os.homedir(), ORDESSA_NATIVE_PROFILE_BRAND: brand,
        ...(directory === undefined ? {} : { ORDESSA_NATIVE_INSTANCE_DIR: directory }) } })
    for (const directory of [undefined, '.', link, instance + '/..']) {
      const result = run(directory)
      assert.equal(result.status, 1)
      assert.equal(fs.existsSync(marker), false)
    }
    fs.chmodSync(instance, 0o755)
    assert.equal(run(instance).status, 1)
    assert.equal(fs.existsSync(marker), false)
  })
  test(`${brand}: isolated entry establishes native HOME before imports without copying global state`, t => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ordessa-native-entry-'))
    t.after(() => fs.rmSync(root, { recursive: true, force: true }))
    const instance = path.join(root, 'instance'); fs.mkdirSync(instance, { mode: 0o700 })
    fs.writeFileSync(path.join(root, 'ordessa-profile.mjs'), fs.readFileSync(new URL('./entry.mjs', import.meta.url), 'utf8').replace('__ORDESSA_NATIVE_BRAND__', brand))
    fs.writeFileSync(path.join(root, 'index.js'), `process.stdout.write(JSON.stringify({
      home:process.env.HOME,codex:process.env.CODEX_HOME,claude:process.env.CLAUDE_CONFIG_DIR,
      xdg:process.env.XDG_CONFIG_HOME}))`)
    const result = spawnSync(process.execPath, [path.join(root, 'ordessa-profile.mjs')], {
      encoding: 'utf8', env: { PATH: process.env.PATH, HOME: os.homedir(),
        CODEX_HOME: '/global/codex', CLAUDE_CONFIG_DIR: '/global/claude',
        ORDESSA_NATIVE_INSTANCE_DIR: instance, ORDESSA_NATIVE_PROFILE_BRAND: brand } })
    assert.equal(result.status, 0, result.stderr)
    assert.deepEqual(JSON.parse(result.stdout), { home: instance, codex: instance,
      claude: instance, xdg: instance })
    assert.deepEqual(fs.readdirSync(instance), [])
  })
}

test('Codex managed scope uses only its explicit private account; inherited authentication is removed', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ordessa-managed-entry-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  const instance = path.join(root, 'instance'), account = path.join(root, 'account')
  fs.mkdirSync(instance, { mode: 0o700 }); fs.mkdirSync(account, { mode: 0o700 })
  const entry = path.join(root, 'ordessa-profile.mjs')
  const source = fs.readFileSync(new URL('./entry.mjs', import.meta.url), 'utf8')
  fs.writeFileSync(entry, source.replace('__ORDESSA_NATIVE_BRAND__', 'codex'))
  fs.writeFileSync(path.join(root, 'index.js'), `process.stdout.write(JSON.stringify({
    home:process.env.HOME,codex:process.env.CODEX_HOME,xdg:process.env.XDG_CONFIG_HOME,
    leaked:['CODEX_API_KEY','OPENAI_API_KEY','CODEX_ACCESS_TOKEN','CODEX_AUTH_TOKEN','DEFAULT_AUTH_REQUEST','MODEL_PROVIDER'].filter(k=>k in process.env)}))`)
  const environment = { PATH: process.env.PATH, ORDESSA_NATIVE_INSTANCE_DIR: instance,
    ORDESSA_CODEX_MANAGED_ACCOUNT_DIR: account, CODEX_API_KEY: 'synthetic',
    OPENAI_API_KEY: 'synthetic', CODEX_ACCESS_TOKEN: 'synthetic', CODEX_AUTH_TOKEN: 'synthetic',
    DEFAULT_AUTH_REQUEST: '{}', MODEL_PROVIDER: 'unexpected' }
  const run = () => spawnSync(process.execPath, [entry], { encoding: 'utf8', env: environment })
  let result = run()
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(JSON.parse(result.stdout), { home: instance, codex: account, xdg: instance, leaked: [] })
  // Account selection is baked into the verified brand asset, never a caller's brand env.
  fs.writeFileSync(entry, source.replace('__ORDESSA_NATIVE_BRAND__', 'claude-code'))
  assert.equal(run().status, 1)
  fs.writeFileSync(entry, source.replace('__ORDESSA_NATIVE_BRAND__', 'codex'))
  for (const selected of [instance, root, path.join(account, '..'), account + '/']) {
    environment.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR = selected
    assert.equal(run().status, 1)
  }
  environment.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR = account
  fs.chmodSync(account, 0o755)
  assert.equal(run().status, 1)
})
