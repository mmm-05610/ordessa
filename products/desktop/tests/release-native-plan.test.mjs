import test from 'node:test'
import assert from 'node:assert/strict'

const loadPlan = () => import('../native-product-plan.mjs')

test('the shared plan selects all three Profile variants through Harness', async () => {
  const { nativeProductPlan } = await loadPlan()
  let observed
  const result = nativeProductPlan({ env: {}, pluginRoot: '/installed/harness',
    planImpl: options => { observed = options; return { args: ['--execution-mode', 'native'] } } })
  assert.deepEqual(observed.harnessIds, ['pi', 'codex', 'claude-code'])
  assert.deepEqual(observed.nativeProfileHarnesses, ['codex', 'claude-code'])
  assert.equal(observed.piProfileBridge, true)
  assert.deepEqual(observed.artifactRoots, {
    pi: '/opt/ordessa/harnesses/profile-pi-startup-admission-v2/artifacts',
    codex: '/opt/ordessa/harnesses/profile-codex-catalog-fast-off-v6/artifacts',
    'claude-code': '/opt/ordessa/harnesses/profile-claude-provider-restoration/artifacts',
  })
  assert.equal(observed.pluginRoot, '/installed/harness')
  assert.deepEqual(result.args, ['--execution-mode', 'native'])
})

test('installed layout rebases product asset roots without knowing adapter entries', async () => {
  const { nativeProductPlan } = await loadPlan()
  let observed
  nativeProductPlan({ env: {}, pluginRoot: '/release/harness', assetBase: '/release/assets',
    planImpl: options => { observed = options; return { args: ['native'] } } })
  assert.equal(observed.artifactRoot, '/release/assets/artifacts')
  assert.equal(observed.artifactRoots.codex, '/release/assets/profile-codex-catalog-fast-off-v6/artifacts')
  assert.equal(observed.artifactRoots.pi, '/release/assets/profile-pi-startup-admission-v2/artifacts')
  assert.equal(observed.artifactRoots['claude-code'], '/release/assets/profile-claude-provider-restoration/artifacts')
  assert.ok(!Object.keys(observed).some(key => key.includes('entry') || key.includes('command')))
})

test('existing environment overrides retain precedence and shared Claude fallback', async () => {
  const { nativeProductPlan } = await loadPlan()
  let observed
  const env = { ORDESSA_NATIVE_HARNESS: 'claude-code', ORDESSA_HARNESS_PLUGIN_ROOT: '/override/plugin',
    ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT: '/override/profiles', ORDESSA_INSTALLED_ARTIFACT_ROOT: '/override/artifacts' }
  nativeProductPlan({ env, pluginRoot: '/installed/plugin', assetBase: '/release/assets',
    planImpl: options => { observed = options; return { args: ['native'] } } })
  assert.equal(observed.harnessId, 'claude-code')
  assert.equal(observed.pluginRoot, '/override/plugin')
  assert.equal(observed.artifactRoot, '/override/artifacts')
  assert.deepEqual(observed.artifactRoots, { 'claude-code': '/override/profiles' })
  assert.equal(observed.piProfileBridge, false)
  assert.deepEqual(observed.nativeProfileHarnesses, ['claude-code'])
})

for (const env of [{ ORDESSA_PI_PROFILE_BRIDGE: 'invalid' },
  { ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT: '' }, { ORDESSA_CLAUDE_PROFILE_ARTIFACT_ROOT: '' }]) {
  test(`invalid override fails before Harness planning: ${Object.keys(env)[0]}`, async () => {
    const { nativeProductPlan } = await loadPlan()
    let planned = false
    assert.throws(() => nativeProductPlan({ env, planImpl: () => { planned = true } }))
    assert.equal(planned, false)
  })
}

for (const failure of ['MISSING_CODEX_ASSET', 'MISSING_PI_ASSET', 'MISSING_CLAUDE_ASSET']) {
  test(`development runner never starts Electron after ${failure}`, async () => {
    const { launchNativeProduct } = await import('../run-native.mjs')
    let spawned = false
    assert.throws(() => launchNativeProduct({ env: {},
      planImpl: () => { throw new Error(failure) },
      spawnImpl: () => { spawned = true } }), new RegExp(failure))
    assert.equal(spawned, false)
  })
}

test('development launch passes exactly the shared plan to its child', async () => {
  const { launchNativeProduct } = await import('../run-native.mjs')
  let actual
  const args = ['--execution-mode', 'native', '--opaque-product-value', 'value']
  const child = launchNativeProduct({ env: { PRODUCT_SENTINEL: 'kept' },
    planImpl: () => ({ args }), spawnImpl: (command, argv, options) => {
      actual = { command, argv, options }; return { fixture: true }
    } })
  assert.equal(child.fixture, true)
  assert.deepEqual(JSON.parse(actual.options.env.ORDESSA_SERVER_ARGS_JSON), args)
  assert.equal(actual.options.env.PRODUCT_SENTINEL, 'kept')
})

test('release generator writes only plan JSON on success and nothing on refusal', async () => {
  const { runReleaseServerArgs } = await import('../release-server-args.mjs')
  let stdout = '', stderr = '', observed
  const io = { writeStdout: value => { stdout += value }, writeStderr: value => { stderr += value } }
  const status = runReleaseServerArgs({ ...io, env: {},
    argv: ['--plugin-root', '/release/plugin', '--asset-base', '/release/assets'],
    planImpl: options => { observed = options; return { args: ['--execution-mode', 'native'] } } })
  assert.equal(status, 0)
  assert.deepEqual(JSON.parse(stdout), ['--execution-mode', 'native'])
  assert.equal(stderr, '')
  assert.equal(observed.pluginRoot, '/release/plugin')
  assert.equal(observed.artifactRoots.pi, '/release/assets/profile-pi-startup-admission-v2/artifacts')
  stdout = ''; stderr = ''
  assert.equal(runReleaseServerArgs({ ...io, env: {}, argv: ['--plugin-root', '/release/plugin'],
    planImpl: () => { throw new Error('ADAPTER_ARTIFACT_UNVERIFIED') } }), 1)
  assert.equal(stdout, '')
  assert.match(stderr, /ADAPTER_ARTIFACT_UNVERIFIED/)
})

test('empty plan and malformed release layout cannot masquerade as a successful empty host', async () => {
  const { runReleaseServerArgs } = await import('../release-server-args.mjs')
  for (const argv of [[], ['--plugin-root'], ['--unknown', 'value'], ['--plugin-root', '/release/plugin']]) {
    let stdout = ''
    assert.equal(runReleaseServerArgs({ env: {}, argv, planImpl: () => ({ args: [] }),
      writeStdout: value => { stdout += value }, writeStderr: () => {} }), 1)
    assert.equal(stdout, '')
  }
})
