import { expect, test } from 'vitest'
import { createConfigurationProjection, type ConfigurationObserveSource } from '../src/configuration-projection'
import { createAbsentAgentOwnerPort, type AgentOwnerPort, type ConfigSnapshotView } from '../src/owner-port'

test('repeating a pre-gap snapshot cannot unlock a configuration capture', async () => {
  let revision = 7
  const snapshot = (): ConfigSnapshotView => ({ ownerRef: 'agent-config:T', revision,
    observedEvidence: 'native', fields: { model: 'known' }, resolved: { model: 'M1' } })
  let fail: ((reason: string) => void) | undefined
  const source: ConfigurationObserveSource = (_target, deliver, unavailable) => {
    deliver(snapshot())
    fail = unavailable
    return { release() {} }
  }
  const owner: AgentOwnerPort = { ...createAbsentAgentOwnerPort(), readConfig: async () => ({ kind: 'ok', value: snapshot() }) }
  const projection = createConfigurationProjection({ target: 'T', owner, observeSource: source })
  expect(projection.getSnapshot().status).toBe('ready')
  fail?.('gap')
  expect(projection.getSnapshot().status).toBe('unknown')
  await projection.refresh()
  expect(projection.getSnapshot().status).toBe('unknown')
  revision += 1
  await projection.refresh()
  expect(projection.getSnapshot().status).toBe('ready')
  projection.close()
  fail?.('late loss')
  expect(projection.getSnapshot().status).toBe('ready')
})

test('an uncertain write cannot leave the send projection ready', async () => {
  const owner: AgentOwnerPort = { ...createAbsentAgentOwnerPort(),
    readConfig: async () => ({ kind: 'ok', value: { ownerRef: 'agent-config:T', revision: 7,
      observedEvidence: 'native', fields: {model:'known'}, resolved: {model:'M1'} } }),
    submitConfigOperation: async () => ({ kind: 'unknown', queryHint: 'original-operation' }) }
  const projection = createConfigurationProjection({ target:'T', owner })
  await projection.refresh()
  expect(projection.getSnapshot().status).toBe('ready')
  const result = await projection.dispatch({model:'M2'})
  expect(result.kind).toBe('unknown')
  expect(projection.getSnapshot().status).toBe('unknown')
  await projection.refresh()
  expect(projection.getSnapshot().status).toBe('unknown')
  projection.close()
})
