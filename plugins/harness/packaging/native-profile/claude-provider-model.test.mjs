import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const source = (await readFile(new URL('./claude-provider-model.mjs', import.meta.url), 'utf8'))
  .replace("'./ordessa-native-routing.mjs'", JSON.stringify(new URL('./routing.mjs', import.meta.url).href))
const { providerModelCandidate, retainAcceptedProviderModel } = await import(
  'data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
const fixture = () => ({ models: { currentModelId: 'sonnet', availableModels: [{ modelId: 'sonnet', name: 'Sonnet' }] },
  modelInfos: [], ordessaProviderRoute: { apiType: 'anthropic', baseUrl: 'https://provider.test/v1' } })
const provider = { apiType: 'anthropic', baseUrl: 'https://provider.test/v1' }

test('custom model is a candidate only on an independently captured explicit provider route', () => {
  const session = fixture()
  assert.deepEqual(providerModelCandidate(provider, session, 'minimax-m2.7'),
    { value: 'minimax-m2.7', name: 'minimax-m2.7' })
  assert.equal(session.models.currentModelId, 'sonnet')
  assert.equal(session.models.availableModels.length, 1)
  for (const p of [undefined, {}, { ...provider, baseUrl: 'https://different.test' },
    { ...provider, apiType: 'openai' }])
    assert.equal(providerModelCandidate(p, session, 'minimax-m2.7'), null)
  session.queryClosed = true
  assert.equal(providerModelCandidate(provider, session, 'minimax-m2.7'), null)
})

test('malformed models, capacity and unsafe captured routes fail before SDK effects', () => {
  for (const value of ['', ' model', 'model\n', 'x'.repeat(257), {}, null, 'model?key=secret'])
    assert.equal(providerModelCandidate(provider, fixture(), value), null)
  const session = fixture()
  session.models.availableModels = Array.from({ length: 512 }, () => ({}))
  assert.equal(providerModelCandidate(provider, session, 'minimax-m2.7'), null)
  session.models.availableModels = []
  session.ordessaProviderRoute.baseUrl = 'https://user:secret@provider.test'
  assert.equal(providerModelCandidate(provider, session, 'minimax-m2.7'), null)
})

test('accepted exact identifier is retained without fabricating model capabilities', () => {
  const session = fixture()
  retainAcceptedProviderModel(session, 'minimax-m2.7')
  retainAcceptedProviderModel(session, 'minimax-m2.7')
  assert.deepEqual(session.models.availableModels[1], { modelId: 'minimax-m2.7', name: 'minimax-m2.7' })
  assert.equal(session.models.availableModels.length, 2)
  assert.deepEqual(session.modelInfos, [])
  assert.equal(session.models.currentModelId, 'sonnet')  // native applyConfigOptionValue owns current state
})
