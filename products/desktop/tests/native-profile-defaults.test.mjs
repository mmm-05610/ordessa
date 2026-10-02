import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { nativeProductPlan } from '../native-product-plan.mjs'

const defaults = {
  codex: '/opt/ordessa/harnesses/profile-codex-catalog-fast-off-v6/artifacts',
  pi: '/opt/ordessa/harnesses/profile-pi-registration-owner-bound/artifacts',
  'claude-code': '/opt/ordessa/harnesses/profile-claude-provider-restoration/artifacts',
}

test('desktop launch and installed probes select the verified Profile assets by default', async () => {
  let selected
  nativeProductPlan({ env: {}, planImpl: options => { selected = options; return { args: ['native'] } } })
  assert.deepEqual(selected.artifactRoots, defaults)
  const launcher = await readFile(new URL('../run-native.mjs', import.meta.url), 'utf8')
  assert.ok(launcher.includes("from './native-product-plan.mjs'"))
  for (const file of ['probe-native-installed.mjs', 'probe-profile-ui.mjs']) {
    const source = await readFile(new URL('../' + file, import.meta.url), 'utf8')
    for (const root of Object.values(defaults)) assert.ok(source.includes(root), `${file}: missing ${root}`)
    for (const override of ['ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT', 'ORDESSA_PI_PROFILE_ARTIFACT_ROOT',
      'ORDESSA_CLAUDE_PROFILE_ARTIFACT_ROOT']) assert.ok(source.includes(override), `${file}: missing ${override}`)
    assert.ok(!source.includes('/profile-chat-fixes/artifacts'), `${file}: obsolete default`)
  }
})

test('Codex probe seed and native acceptance use the same delivered default as the desktop', async () => {
  for (const file of ['seed-profile-ui-probe.py', 'probe-installed-codex-managed-profile.py']) {
    const source = await readFile(new URL('../../server/scripts/' + file, import.meta.url), 'utf8')
    assert.ok(source.includes(defaults.codex), `${file}: mismatched default`)
  }
})
