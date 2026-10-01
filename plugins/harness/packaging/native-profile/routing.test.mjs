import test from 'node:test'
import assert from 'node:assert/strict'
import { captureCodexThreadRoute, safeNativeRoute } from './routing.mjs'

test('Codex accepted thread binds its submitted routing snapshot, never mutable provider catalogue', () => {
  const params = { modelProvider: 'custom-gateway', config: { model_providers: {
    'custom-gateway': { base_url: 'https://fixture.invalid/v1', wire_api: 'responses',
      http_headers: { authorization: 'synthetic-secret' } } } } }
  const route = captureCodexThreadRoute(params, { modelProvider: 'custom-gateway' })
  params.config.model_providers['custom-gateway'].base_url = 'https://changed.invalid'
  assert.deepEqual(route, { provider: 'custom-gateway', api: 'responses', baseUrl: 'https://fixture.invalid/v1' })
  assert.equal(JSON.stringify(route).includes('synthetic-secret'), false)
  assert.equal(captureCodexThreadRoute(params, { modelProvider: 'openai' }), null)
})

test('routing never invents default endpoint/protocol or exposes URL credentials', () => {
  for (const baseUrl of ['https://u:p@fixture.invalid', 'https://fixture.invalid?token=secret',
    'https://fixture.invalid#secret', 'file:///private', '', undefined]) {
    assert.equal(safeNativeRoute({ provider: 'main', api: 'anthropic', baseUrl }), null)
  }
  assert.equal(captureCodexThreadRoute({ modelProvider: 'custom-gateway', config: {} },
    { modelProvider: 'custom-gateway' }), null)
  assert.equal(safeNativeRoute({ provider: 'main', api: 'guessed', baseUrl: 'https://fixture.invalid' }), null)
})
