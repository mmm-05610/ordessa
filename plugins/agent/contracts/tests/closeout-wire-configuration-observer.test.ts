import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import type { AgentSessionLocation, AgentSessions } from '../src/agent'
import type { ConfigSnapshotView, WireCall } from '../src/owner-port'
import { createWireConfigurationClient } from '../src/wire-configuration'

type WireAnswer = Awaited<ReturnType<WireCall>>
type Deferred<T> = { promise: Promise<T>; resolve(value: T): void }

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

const location = (runtimeGeneration?: number) => ({
  kind: 'session' as const,
  sessionId: 'session-1',
  connectionId: 'connection-1',
  serverInstanceId: 'server-1',
  contextRevision: 3,
  ...(runtimeGeneration === undefined ? {} : { runtimeGeneration }),
})

function snapshot(revision: number, model = 'M1'): ConfigSnapshotView {
  return {
    ownerRef: 'backend-owner:canonical-session-1',
    revision,
    observedEvidence: 'native',
    fields: { model: 'known' },
    resolved: { model },
  }
}

function sessions(runtimeGeneration = 10): AgentSessions {
  const listeners = new Set<() => void>()
  return {
    getSnapshot: () => ({ runtimeGeneration }),
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    nativeOwnerForLocation(input: AgentSessionLocation) {
      return {
        sessionId: input.sessionId, serverInstanceId: input.serverInstanceId ?? 'server-1',
        // ACP backend channel identity has a distinct namespace from the frontend connection.
        connectionId: 'backend-channel-1', nativeSessionId: 'native-session-1',
        harnessId: input.harnessId ?? 'acp', workspaceId: '/workspace/one',
      }
    },
  } as unknown as AgentSessions
}

function until(predicate: () => boolean, label: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const started = Date.now()
    const check = () => {
      if (predicate()) { resolve(); return }
      if (Date.now() - started > 1000) { reject(new Error(`timed out waiting for ${label}`)); return }
      setTimeout(check, 0)
    }
    check()
  })
}

function observationBatch(value?: ConfigSnapshotView): WireAnswer {
  return {
    kind: 'Accepted',
    result: {
      subscription_id: 'observe-subscription-1',
      cursor: value ? 'cursor-1' : null,
      frames: value ? [{ kind: 'snapshot', cursor: 'cursor-1', source: { environment: 'environment-1' }, value }] : [],
    },
  }
}

/**
 * This fixture mocks only the transport boundary: backend-issued target/generation,
 * config read/operation methods, and declared observation batches. Each test still
 * invokes createWireConfigurationClient and its real AgentOwnerPort/projection.
 * It does not mock configuration-projection, the wire client, React, or an owner.
 */
function backendFixture(options: { read?: () => ConfigSnapshotView } = {}) {
  const calls: Array<{ method: string; params: Readonly<Record<string, unknown>> }> = []
  let nextObservation: () => Promise<WireAnswer> = async () => observationBatch()
  let observationCalls = 0
  const wire = {
    ready: true,
    scope: 'transport-scope-1' as string | null,
    async call(method: string, params: Readonly<Record<string, unknown>>): Promise<WireAnswer> {
      calls.push({ method, params })
      if (method === 'agent.session.resolve') {
        return { kind: 'Accepted', result: {
          target: 'backend-canonical:session-1',
          generation: 2,
          observation: {
            method: 'agent.config.observe',
            releaseMethod: 'agent.config.release',
            environment: 'environment-1',
          },
        } }
      }
      if (method === 'agent.config.read') {
        const current = (options.read ?? (() => snapshot(5)))()
        return { kind: 'Accepted', result: current as unknown as Record<string, unknown> }
      }
      if (method === 'agent.config.observe') {
        observationCalls += 1
        return nextObservation()
      }
      if (method === 'agent.config.release') {
        return { kind: 'Accepted', result: { released: true } }
      }
      if (method === 'agent.config.submitOperation') {
        return { kind: 'Accepted', result: { operationId: 'operation-1', patchKinds: ['present'], state: 'pending' } }
      }
      return { kind: 'Refused', reason: `unexpected method: ${method}` }
    },
  }
  return {
    wire,
    calls,
    get observationCalls() { return observationCalls },
    observeWith(next: () => Promise<WireAnswer>) { nextObservation = next },
    client(scope?: OwnedResources, currentSessions = sessions()) {
      return createWireConfigurationClient({ wire, sessions: currentSessions, ...(scope ? { scope } : {}) })
    },
  }
}

describe('wire configuration observer lifecycle', () => {
  it('shares one backend-resolved target projection and releases it after the final independent client', async () => {
    const poll = deferred<WireAnswer>()
    const backend = backendFixture()
    backend.observeWith(async () => backend.observationCalls === 1
      ? observationBatch(snapshot(6, 'M2'))
      : poll.promise)
    const firstScope = new OwnedResources()
    const secondScope = new OwnedResources()
    const firstClient = backend.client(firstScope)
    const secondClient = backend.client(secondScope)

    const first = await firstClient.forLocation(location())
    const second = await secondClient.forLocation(location())
    expect(second.getSnapshot()).toMatchObject({
      status: 'ready',
      target: first.getSnapshot().target,
      config: { revision: first.getSnapshot().config?.revision, resolved: { model: 'M2' } },
    })
    expect(first.getSnapshot().config?.resolved.model).toBe('M2')
    expect(backend.calls.filter(call => call.method === 'agent.config.observe')).toHaveLength(2)
    expect(backend.calls.find(call => call.method === 'agent.config.observe')?.params.nativeOwner)
      .toMatchObject({ sessionId: 'session-1', connectionId: 'backend-channel-1', nativeSessionId: 'native-session-1' })
    expect(backend.calls.some(call => call.method === 'agent.config.submitOperation')).toBe(false)

    firstClient.dispose()
    expect(backend.calls.filter(call => call.method === 'agent.config.release')).toHaveLength(0)
    secondClient.dispose()
    await until(() => backend.calls.some(call => call.method === 'agent.config.release'), 'last-client observation release')
    expect(backend.calls.filter(call => call.method === 'agent.config.release')).toHaveLength(1)
    expect(backend.calls.filter(call => call.method === 'agent.config.release')[0].params.subscriptionId)
      .toBe('observe-subscription-1')

    poll.resolve(observationBatch())
    await firstScope.dispose()
    await secondScope.dispose()
  })

  it('releases an observation that attaches after its client was disposed', async () => {
    const lateAttach = deferred<WireAnswer>()
    const backend = backendFixture()
    backend.observeWith(() => lateAttach.promise)
    const client = backend.client()
    const projection = await client.forLocation(location())
    let notifications = 0
    projection.subscribe(() => { notifications += 1 })

    client.dispose()
    expect(backend.calls.some(call => call.method === 'agent.config.release')).toBe(false)
    lateAttach.resolve(observationBatch(snapshot(9, 'late')))
    await until(() => backend.calls.some(call => call.method === 'agent.config.release'), 'late observation release')

    expect(backend.calls.filter(call => call.method === 'agent.config.release')).toHaveLength(1)
    expect(projection.getSnapshot().config?.resolved.model).toBe('M1')
    expect(notifications).toBe(0)
    expect(backend.calls.some(call => call.method === 'agent.config.submitOperation')).toBe(false)
  })

  it('keeps an old read snapshot unknown after an observation gap', async () => {
    const secondPoll = deferred<WireAnswer>()
    const backend = backendFixture()
    backend.observeWith(async () => backend.observationCalls === 1
      ? observationBatch(snapshot(5))
      : secondPoll.promise)
    const client = backend.client()
    const projection = await client.forLocation(location())
    await until(() => backend.observationCalls >= 2, 'second observation poll')

    secondPoll.resolve({
      kind: 'Accepted',
      result: { subscription_id: 'observe-subscription-1', resync_required: true, frames: [] },
    })
    await until(() => projection.getSnapshot().status === 'unknown', 'gap invalidation')
    await projection.refresh() // the fixture returns the same pre-gap revision

    expect(projection.getSnapshot().status).toBe('unknown')
    expect(projection.getSnapshot().config?.revision).toBe(5)
    expect(backend.calls.some(call => call.method === 'agent.config.submitOperation')).toBe(false)
    await until(() => backend.calls.some(call => call.method === 'agent.config.release'), 'gap observation release')
    client.dispose()
  })

  it('refuses writes after trusted generation changes and releases the scoped observation', async () => {
    const poll = deferred<WireAnswer>()
    const backend = backendFixture()
    backend.observeWith(async () => backend.observationCalls === 1
      ? observationBatch(snapshot(5))
      : poll.promise)
    let runtimeGeneration = 10
    const sessionListeners = new Set<() => void>()
    const currentSessions = {
      getSnapshot: () => ({ runtimeGeneration }),
      subscribe(listener: () => void) { sessionListeners.add(listener); return () => sessionListeners.delete(listener) },
      nativeOwnerForLocation(input: AgentSessionLocation) {
        return {
          sessionId: input.sessionId, serverInstanceId: input.serverInstanceId ?? 'server-1',
          connectionId: 'backend-channel-1', nativeSessionId: 'native-session-1',
          harnessId: input.harnessId ?? 'acp', workspaceId: '/workspace/one',
        }
      },
    } as unknown as AgentSessions
    const scope = new OwnedResources()
    const client = backend.client(scope, currentSessions)
    const projection = await client.forLocation(location(10))
    await until(() => backend.observationCalls >= 2, 'active observation poll')

    runtimeGeneration = 11
    for (const listener of [...sessionListeners]) listener()
    await until(() => backend.calls.some(call => call.method === 'agent.config.release'), 'generation observation release')
    const result = await projection.dispatch({ prompt: 'must not write' })
    expect(result.kind).toBe('unavailable')
    expect(backend.calls.some(call => call.method === 'agent.config.submitOperation')).toBe(false)

    await scope.dispose()
    expect(backend.calls.filter(call => call.method === 'agent.config.release')).toHaveLength(1)
    poll.resolve(observationBatch())
  })
})
