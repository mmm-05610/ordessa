import { describe, expect, it } from 'vitest'
import type { AgentNativeSessionOwner, AgentSessions } from '../src/agent'
import type { ConfigSnapshotView, WireCall } from '../src/owner-port'
import { createWireConfigurationClient } from '../src/wire-configuration'

type Location = {
  kind: 'session' | 'draft'
  sessionId?: string
  draftId?: string
  connectionId: string
  serverInstanceId?: string
  harnessId?: string
  runtimeGeneration?: number
  contextRevision: number
}
type SubmissionBinding = {
  readonly target: string
  readonly generation: string | number
  readonly namespace: string
  readonly principalScope: string
  readonly schema: string
  readonly mode: 'existing' | 'createWithConfig'
  readonly configOperationIds: readonly string[]
}
type BindingClient = ReturnType<typeof createWireConfigurationClient> & {
  captureSubmissionBinding(location: Location): SubmissionBinding
}

const sessionLocation: Location = {
  kind: 'session', sessionId: 'route:session-1', connectionId: 'frontend-1',
  serverInstanceId: 'server-1', harnessId: 'acp', runtimeGeneration: 4, contextRevision: 9,
}
const owner: AgentNativeSessionOwner = {
  sessionId: sessionLocation.sessionId!, serverInstanceId: 'server-1', connectionId: 'backend-channel-1',
  nativeSessionId: 'native-1', harnessId: 'acp', workspaceId: '/workspace/one',
}

function config(revision: number, operationId = 'operation-model-1'): ConfigSnapshotView {
  return {
    ownerRef: 'backend-owner:session-1', revision, observedEvidence: 'native',
    fields: { model: 'known' }, resolved: { model: `M${revision}` },
    operations: [{ operationId, patchKinds: ['present'], state: 'pending' }],
  }
}

function fixture(options: {
  submission?: Record<string, unknown>
  omitSubmission?: boolean
  available?: boolean
} = {}) {
  const calls: Array<{ method: string; params: Readonly<Record<string, unknown>> }> = []
  let current = config(3)
  let runtimeGeneration = 4
  let scope: string | null = 'transport-1'
  const listeners = new Set<() => void>()
  const wire = {
    ready: true,
    get scope() { return scope },
    async call(method: string, params: Readonly<Record<string, unknown>>) {
      calls.push({ method, params })
      if (method === 'agent.session.resolve') {
        const metadata = options.omitSubmission ? undefined : {
          available: options.available ?? true,
          namespace: 'environment-1', principalScope: 'principal-1',
          schema: 'agent-input/v1', mode: 'existing',
          ...options.submission,
        }
        return { kind: 'Accepted' as const, result: {
          target: 'backend-canonical:session-1', generation: 12,
          ...(metadata ? { submission: metadata } : {}),
        } }
      }
      if (method === 'agent.config.read') return { kind: 'Accepted' as const, result: current as unknown as Record<string, unknown> }
      if (method === 'agent.config.prepare') return { kind: 'Accepted' as const, result: { status: 'ready' } }
      return { kind: 'Refused' as const, reason: `unexpected method: ${method}` }
    },
  }
  const sessions = {
    getSnapshot: () => ({ runtimeGeneration }),
    subscribe(listener: () => void) { listeners.add(listener); return () => listeners.delete(listener) },
    nativeOwnerForLocation: () => owner,
  } as unknown as AgentSessions
  const client = createWireConfigurationClient({ wire, sessions }) as BindingClient
  return {
    client, calls,
    setConfig(value: ConfigSnapshotView) { current = value },
    setScope(value: string | null) { scope = value },
    setRuntimeGeneration(value: number) {
      runtimeGeneration = value
      for (const listener of [...listeners]) listener()
    },
  }
}

function capture(client: ReturnType<typeof createWireConfigurationClient>, location: Location) {
  return (client as BindingClient).captureSubmissionBinding(location)
}

describe('wire configuration submission binding capture', () => {
  it('captures a frozen binding from backend metadata and the current ready projection', async () => {
    const backend = fixture()
    await backend.client.forLocation(sessionLocation)

    const binding = capture(backend.client, sessionLocation)

    expect(binding).toEqual({
      target: 'backend-canonical:session-1', generation: 12,
      namespace: 'environment-1', principalScope: 'principal-1',
      schema: 'agent-input/v1', mode: 'existing', configOperationIds: ['operation-model-1'],
    })
    expect(Object.isFrozen(binding)).toBe(true)
    expect(Object.isFrozen(binding.configOperationIds)).toBe(true)
    backend.client.dispose()
  })

  it('reads operation IDs from the live projection at each synchronous capture', async () => {
    const backend = fixture()
    const projection = await backend.client.forLocation(sessionLocation)
    expect(capture(backend.client, sessionLocation).configOperationIds).toEqual(['operation-model-1'])

    backend.setConfig(config(4, 'operation-model-2'))
    await projection.refresh()

    expect(capture(backend.client, sessionLocation).configOperationIds).toEqual(['operation-model-2'])
    backend.client.dispose()
  })

  it('captures the complete pending operation set and refuses unknown or conflicted operation facts', async () => {
    const backend = fixture()
    const projection = await backend.client.forLocation(sessionLocation)
    backend.setConfig({
      ...config(4),
      operations: [
        { operationId: 'operation-model-2', patchKinds: ['present'], state: 'pending' },
        { operationId: 'operation-profile-3', patchKinds: ['present'], state: 'pending' },
      ],
    })
    await projection.refresh()
    expect(capture(backend.client, sessionLocation).configOperationIds)
      .toEqual(['operation-model-2', 'operation-profile-3'])

    for (const state of ['unknown', 'conflict'] as const) {
      backend.setConfig({
        ...config(5),
        operations: [{ operationId: 'operation-unsettled', patchKinds: ['present'], state }],
      })
      await projection.refresh()
      expect(() => capture(backend.client, sessionLocation)).toThrow(/operation|configuration|unknown|conflict/i)
    }
    backend.client.dispose()
  })

  it('refuses missing or explicitly unavailable backend submission capability metadata', async () => {
    for (const options of [{ omitSubmission: true }, { available: false }]) {
      const backend = fixture(options)
      await backend.client.forLocation(sessionLocation)
      expect(() => capture(backend.client, sessionLocation)).toThrow(/submission.*unavailable|metadata/i)
      backend.client.dispose()
    }
  })

  it('captures the backend createWithConfig mode for a draft without native owner lookup', async () => {
    const backend = fixture({ submission: { mode: 'createWithConfig' } })
    const draft: Location = {
      kind: 'draft', draftId: 'draft-1', connectionId: 'frontend-1', contextRevision: 9,
    }
    await backend.client.forLocation(draft)

    expect(capture(backend.client, draft)).toMatchObject({
      target: 'backend-canonical:session-1', generation: 12,
      namespace: 'environment-1', principalScope: 'principal-1',
      schema: 'agent-input/v1', mode: 'createWithConfig',
    })
    expect(backend.calls.find(call => call.method === 'agent.session.resolve')?.params.nativeOwner).toBeUndefined()
    backend.client.dispose()
  })

  it('fences a captured binding after transport scope or runtime generation changes', async () => {
    const backend = fixture()
    await backend.client.forLocation(sessionLocation)
    backend.setScope('transport-2')
    expect(() => capture(backend.client, sessionLocation)).toThrow(/scope|binding|generation/i)
    backend.client.dispose()

    const generation = fixture()
    await generation.client.forLocation(sessionLocation)
    generation.setRuntimeGeneration(5)
    expect(() => capture(generation.client, sessionLocation)).toThrow(/scope|binding|generation/i)
    generation.client.dispose()
  })

  it('uses prepare only as a local binding guard and does not dispatch config preparation', async () => {
    const backend = fixture()
    await backend.client.forLocation(sessionLocation)

    await expect(backend.client.prepare({
      target: sessionLocation, submissionId: 'submission-1', draftRevision: 3,
    })).resolves.toMatchObject({ status: 'ready' })

    expect(backend.calls.some(call => call.method === 'agent.config.prepare')).toBe(false)
    backend.client.dispose()
  })
})
