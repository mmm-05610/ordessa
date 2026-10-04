import { describe, expect, it } from 'vitest'
import type { AgentNativeSessionOwner, AgentSessions } from '../src/agent'
import type { WireCall } from '../src/owner-port'
import { createWireConfigurationClient } from '../src/wire-configuration'

const location = {
  kind: 'session' as const,
  // This is a connector route key. It intentionally differs from the ACP id.
  sessionId: 'connection-7:native-route-4',
  // Frontend connector ID; it intentionally differs from the backend ACP channel ID.
  connectionId: 'frontend-connector-7',
  serverInstanceId: 'server-2',
  harnessId: 'acp',
  contextRevision: 12,
}

const nativeOwner: AgentNativeSessionOwner = Object.freeze({
  sessionId: location.sessionId,
  serverInstanceId: 'server-2',
  connectionId: 'backend-channel-22',
  nativeSessionId: 'native-route-4',
  harnessId: 'acp',
  workspaceId: '/workspace/one',
})

function sessions(ownerLookup?: (input: typeof location) => AgentNativeSessionOwner): AgentSessions {
  return {
    getSnapshot: () => ({ runtimeGeneration: 5 }),
    subscribe: () => () => undefined,
    ...(ownerLookup ? { nativeOwnerForLocation: ownerLookup } : {}),
  } as unknown as AgentSessions
}

function wire(calls: Array<{ method: string; params: Readonly<Record<string, unknown>> }>): { ready: true; scope: string; call: WireCall } {
  return {
    ready: true,
    scope: 'wire-scope',
    async call(method, params) {
      calls.push({ method, params })
      if (method === 'agent.session.resolve') {
        const input = params.location as { kind?: string }
        return { kind: 'Accepted', result: {
          target: 'canonical-session-4', generation: 8,
          ...(input.kind === 'session' ? { observation: {
            method: 'agent.config.observe', releaseMethod: 'agent.config.release', environment: 'environment-1',
          } } : {}),
        } }
      }
      if (method === 'agent.config.read') {
        return { kind: 'Accepted', result: {
          ownerRef: 'canonical-session-4', revision: 1, observedEvidence: 'native',
          fields: {}, resolved: {},
        } }
      }
      if (method === 'agent.config.observe') return { kind: 'Refused', reason: 'controlled observation end' }
      return { kind: 'Refused', reason: `unexpected method ${method}` }
    },
  }
}

describe('wire configuration native owner bridge', () => {
  it('resolves a route key only through its distinct connector-observed native owner', async () => {
    const calls: Array<{ method: string; params: Readonly<Record<string, unknown>> }> = []
    const lookupCalls: typeof location[] = []
    const client = createWireConfigurationClient({
      wire: wire(calls),
      sessions: sessions(input => { lookupCalls.push(input); return nativeOwner }),
    })

    const projection = await client.forLocation(location)

    expect(lookupCalls).toEqual([location])
    const resolve = calls.find(call => call.method === 'agent.session.resolve')
    expect(resolve?.params.nativeOwner).toEqual(nativeOwner)
    expect((resolve?.params.nativeOwner as AgentNativeSessionOwner).nativeSessionId)
      .toBe('native-route-4')
    expect((resolve?.params.location as typeof location).sessionId).toBe(location.sessionId)
    expect((resolve?.params.location as typeof location).sessionId)
      .not.toBe((resolve?.params.nativeOwner as AgentNativeSessionOwner).nativeSessionId)
    const observe = calls.find(call => call.method === 'agent.config.observe')
    expect(observe?.params.nativeOwner).toEqual(nativeOwner)

    client.dispose()
    projection.close()
  })

  it('fails closed before wire resolution when a session location has no trusted owner lookup', async () => {
    const calls: Array<{ method: string; params: Readonly<Record<string, unknown>> }> = []
    const client = createWireConfigurationClient({ wire: wire(calls), sessions: sessions() })

    await expect(client.forLocation(location)).rejects.toThrow(/native owner/i)

    expect(calls).toEqual([])
    client.dispose()
  })

  it('keeps backend-minted draft resolution available without creating or looking up a native session', async () => {
    const calls: Array<{ method: string; params: Readonly<Record<string, unknown>> }> = []
    const lookupCalls: unknown[] = []
    const client = createWireConfigurationClient({
      wire: wire(calls),
      sessions: sessions(input => { lookupCalls.push(input); return nativeOwner }),
    })
    const draft = {
      kind: 'draft' as const,
      draftId: 'draft-1',
      contextRevision: 12,
      connectionId: 'frontend-connector-7',
    }

    const projection = await client.forLocation(draft)

    expect(lookupCalls).toEqual([])
    expect(calls.find(call => call.method === 'agent.session.resolve')?.params)
      .toEqual({ location: draft })
    expect(projection.getSnapshot().status).not.toBe('unavailable')
    client.dispose()
    projection.close()
  })
})
