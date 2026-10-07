/**
 * Closeout regressions for the frontend-facing Agent configuration projection.
 * Each client gets a distinct WireCall and AgentOwnerPort; both talk to one
 * controlled backend authority that owns target records and revisions.
 */
import { describe, expect, it } from 'vitest'

import { createAgentOwnerPort, type ConfigSnapshotView, type WireCall } from '../src/owner-port'
import { createConfigurationProjection } from '../src/configuration-projection'

type WireAnswer = Awaited<ReturnType<WireCall>>
type Deferred<T> = { promise: Promise<T>; resolve(value: T): void }

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

function controlledBackend() {
  type RecordState = { revision: number; resolved: Record<string, unknown> }
  const records = new Map<string, RecordState>()
  let operation = 0
  let nextSubmitGate: Deferred<void> | undefined

  const stateFor = (target: string): RecordState => {
    let state = records.get(target)
    if (!state) {
      state = { revision: 0, resolved: {} }
      records.set(target, state)
    }
    return state
  }

  const handle: WireCall = async (method, params): Promise<WireAnswer> => {
    const target = String(params.target)
    const state = stateFor(target)
    if (method === 'agent.config.read') {
      return {
        kind: 'Accepted',
        result: {
          ownerRef: `server-agent-owner:${target}`,
          revision: state.revision,
          observedEvidence: 'native',
          fields: Object.fromEntries(Object.keys(state.resolved).map(key => [key, 'known'])),
          resolved: { ...state.resolved },
        },
      }
    }
    if (method === 'agent.config.submitOperation') {
      operation += 1
      const patch = params.patch as Record<string, unknown>
      Object.assign(state.resolved, patch)
      for (const key of (params.unset as string[] | undefined) ?? []) delete state.resolved[key]
      state.revision += 1
      const receipt = {
        operationId: `server-op-${operation}`,
        patchKinds: [
          ...Object.keys(patch).map(() => 'present'),
          ...((params.unset as string[] | undefined) ?? []).map(() => 'unset'),
        ],
        state: 'pending',
      }
      const gate = nextSubmitGate
      nextSubmitGate = undefined
      if (gate) await gate.promise
      return { kind: 'Accepted', result: receipt }
    }
    return { kind: 'Refused', reason: `unexpected method: ${method}` }
  }

  return {
    client: () => createAgentOwnerPort(handle),
    deferNextSubmitResponse: () => {
      const gate = deferred<void>()
      nextSubmitGate = gate
      return gate
    },
  }
}

describe('Agent configuration projection closeout', () => {
  it('keeps Profile and model operations on one backend target and preserves omitted fields', async () => {
    const backend = controlledBackend()
    const profileClient = createConfigurationProjection({
      target: 'trusted-agent-target:session-1',
      owner: backend.client(),
    })
    const modelClient = createConfigurationProjection({
      target: 'trusted-agent-target:session-1',
      owner: backend.client(),
    })

    await profileClient.dispatch({ prompt: 'profile A prompt', model: 'M1' })
    await modelClient.dispatch({ model: 'M2' })
    await profileClient.refresh()
    expect(profileClient.getSnapshot().config?.resolved).toMatchObject({
      prompt: 'profile A prompt',
      model: 'M2',
    })

    await modelClient.dispatch({ prompt: 'profile B prompt' })
    await profileClient.refresh()
    expect(profileClient.getSnapshot().config?.resolved).toMatchObject({
      prompt: 'profile B prompt',
      model: 'M2',
    })

    await profileClient.dispatch({ prompt: 'profile A prompt', model: 'M1' })
    await modelClient.refresh()
    expect(modelClient.getSnapshot().config?.resolved).toMatchObject({
      prompt: 'profile A prompt',
      model: 'M1',
    })
    expect(modelClient.getSnapshot().config?.revision).toBeGreaterThan(0)
  })

  it('isolates different trusted targets while independent clients share each target revision', async () => {
    const backend = controlledBackend()
    const firstWindow = createConfigurationProjection({
      target: 'trusted-agent-target:session-1',
      owner: backend.client(),
    })
    const secondWindow = createConfigurationProjection({
      target: 'trusted-agent-target:session-1',
      owner: backend.client(),
    })
    const otherSession = createConfigurationProjection({
      target: 'trusted-agent-target:session-2',
      owner: backend.client(),
    })

    await firstWindow.dispatch({ model: 'M1' })
    await secondWindow.refresh()
    await otherSession.refresh()

    expect(secondWindow.getSnapshot().config?.revision).toBe(firstWindow.getSnapshot().config?.revision)
    expect(secondWindow.getSnapshot().config?.resolved).toEqual({ model: 'M1' })
    expect(otherSession.getSnapshot().config?.resolved).toEqual({})
    expect(otherSession.getSnapshot().config?.revision).toBe(0)
  })

  it('does not let a delayed earlier operation result replace the later owner revision', async () => {
    const backend = controlledBackend()
    const clientA = createConfigurationProjection({
      target: 'trusted-agent-target:session-1',
      owner: backend.client(),
    })
    const clientB = createConfigurationProjection({
      target: 'trusted-agent-target:session-1',
      owner: backend.client(),
    })
    const delayedA = backend.deferNextSubmitResponse()

    const operationA = clientA.dispatch({ model: 'M1' })
    await clientB.dispatch({ model: 'M2' })
    const revisionB = clientB.getSnapshot().config?.revision
    delayedA.resolve()
    await operationA

    expect(clientA.getSnapshot().config?.resolved.model).toBe('M2')
    expect(clientA.getSnapshot().config?.revision).toBe(revisionB)
    expect(clientA.getSnapshot().config?.revision).toBeGreaterThan(0)
  })

  it('captures each queued operation patch at dispatch time', async () => {
    const backend = controlledBackend()
    const projection = createConfigurationProjection({
      target: 'trusted-agent-target:session-1',
      owner: backend.client(),
    })
    const gate = backend.deferNextSubmitResponse()

    const first = projection.dispatch({ prompt: 'first' })
    const patch = { model: 'M2' }
    const second = projection.dispatch(patch)
    patch.model = 'M3'
    gate.resolve()

    await Promise.all([first, second])
    expect(projection.getSnapshot().config?.resolved).toMatchObject({
      prompt: 'first',
      model: 'M2',
    })
  })

  it('does not apply an in-flight response after its scope or generation is retired', async () => {
    const backend = controlledBackend()
    const gate = backend.deferNextSubmitResponse()
    let currentGeneration = 7
    const projection = createConfigurationProjection({
      target: 'trusted-agent-target:session-1',
      owner: backend.client(),
      generation: 7,
      isGenerationCurrent: generation => generation === currentGeneration,
    })
    const notifications: unknown[] = []
    projection.subscribe(() => notifications.push(projection.getSnapshot()))

    const pending = projection.dispatch({ model: 'M1' })
    currentGeneration = 8
    gate.resolve()
    await pending

    expect(projection.getSnapshot().status).toBe('loading')
    expect(notifications).toEqual([])
    projection.close()
    projection.close()
  })

  it('projects optional authorized observation snapshots and releases the source on close', async () => {
    const backend = controlledBackend()
    let observedTarget = ''
    let deliver: ((snapshot: ConfigSnapshotView) => void) | undefined
    let releases = 0
    const projection = createConfigurationProjection({
      target: 'trusted-agent-target:session-1',
      owner: backend.client(),
      observeSource: (target, onSnapshot) => {
        observedTarget = target
        deliver = onSnapshot
        return () => { releases += 1 }
      },
    })
    let notifications = 0
    projection.subscribe(() => { notifications += 1 })

    deliver!({
      ownerRef: 'server-agent-owner:session-1',
      revision: 3,
      observedEvidence: 'native',
      fields: { model: 'known' },
      resolved: { model: 'M3' },
    })
    await projection.refresh() // revision 0 from this read cannot roll revision 3 back
    deliver!({
      ownerRef: 'server-agent-owner:session-1',
      revision: 3,
      observedEvidence: 'native',
      fields: { model: 'known' },
      resolved: { model: 'M4' },
    })
    const beforeClose = projection.getSnapshot()
    expect(beforeClose.status).toBe('unavailable')
    expect(beforeClose.reason).toContain('conflicting data')
    expect(beforeClose.config?.resolved.model).toBe('M3')
    projection.close()
    deliver!({
      ownerRef: 'server-agent-owner:session-1',
      revision: 4,
      observedEvidence: 'native',
      fields: { model: 'known' },
      resolved: { model: 'M4' },
    })

    expect(observedTarget).toBe('trusted-agent-target:session-1')
    expect(projection.getSnapshot()).toBe(beforeClose)
    expect(projection.getSnapshot().config?.resolved.model).toBe('M3')
    expect(notifications).toBe(2)
    expect(releases).toBe(1)
  })
})
