import type { ResourceScope } from '@ordessa/extension-api'
import type { AgentSessions } from './agent'
import { createAgentOwnerPort, type WireCall } from './owner-port'
import { createConfigurationProjection, type ConfigurationProjection } from './configuration-projection'

type Location = { readonly kind: 'draft' | 'session'; readonly draftId?: string; readonly sessionId?: string;
  readonly connectionId?: string; readonly serverInstanceId?: string; readonly runtimeGeneration?: number;
  readonly contextRevision: number; readonly projectId?: string; readonly harnessId?: string }
type Wire = { readonly ready: boolean; readonly scope: string | null; call: WireCall }
const transportProjections = new WeakMap<Wire, Map<string, { projection: ConfigurationProjection; refs: number }>>()

/** Backend-issued identity only. This client contains projections, never owners. */
export function createWireConfigurationClient(options: { wire: Wire; sessions: AgentSessions; scope?: ResourceScope }) {
  const projections = new Map<string, ConfigurationProjection>()
  let closed = false
  const owner = createAgentOwnerPort((method, params) => options.wire.call(method, params))
  async function forLocation(location: Location): Promise<ConfigurationProjection> {
    if (closed || options.scope?.isDisposed || !options.wire.ready || !options.wire.scope) {
      throw new Error('Agent configuration transport unavailable')
    }
    const wireScope = options.wire.scope
    const result = await options.wire.call('agent.session.resolve', { location })
    if (result.kind !== 'Accepted') throw new Error(`Agent target resolution ${result.kind}: ${result.reason}`)
    const target = result.result.target
    const generation = result.result.generation
    if (typeof target !== 'string' || !target || (typeof generation !== 'number' && typeof generation !== 'string')) {
      throw new Error('Agent target resolution lacks canonical identity/generation')
    }
    if (closed || options.wire.scope !== wireScope) throw new Error('Agent target binding changed')
    const key = JSON.stringify([wireScope, target, generation])
    let shared = transportProjections.get(options.wire)
    if (!shared) { shared = new Map(); transportProjections.set(options.wire, shared) }
    let projection = projections.get(key)
    if (!projection) {
      const existing = shared.get(key)
      if (existing) { projection = existing.projection; existing.refs += 1 }
      else {
      projection = createConfigurationProjection({ target, owner, generation,
        isGenerationCurrent: () => options.wire.scope === wireScope
          && (location.runtimeGeneration === undefined || options.sessions.getSnapshot().runtimeGeneration === location.runtimeGeneration),
      })
      shared.set(key, { projection, refs: 1 })
      }
      projections.set(key, projection)
    }
    await projection.refresh()
    return projection
  }
  async function prepare(snapshot: { target: Location; submissionId: string; draftRevision: number }) {
    try {
      const projection = await forLocation(snapshot.target)
      const state = projection.getSnapshot()
      if (state.status !== 'ready' || !state.config) return { status: 'unknown' as const }
      const answer = await options.wire.call('agent.config.prepare', {
        target: state.target, generation: state.generation, revision: state.config.revision,
        submissionId: snapshot.submissionId, draftRevision: snapshot.draftRevision,
      })
      if (answer.kind === 'Unknown') return { status: 'unknown' as const }
      if (answer.kind === 'Refused') return { status: 'refused' as const, reason: answer.reason }
      if (answer.result.status === 'ready') return { status: 'ready' as const }
      if (answer.result.status === 'refused') return { status: 'refused' as const, reason: String(answer.result.reason) }
      return { status: 'unknown' as const }
    } catch (error) { return { status: 'refused' as const, reason: String(error) } }
  }
  function dispose() {
    if (closed) return
    closed = true
    const shared = transportProjections.get(options.wire)
    for (const [key, projection] of projections) {
      const entry = shared?.get(key)
      if (entry && --entry.refs === 0) { projection.close(); shared?.delete(key) }
    }
    projections.clear()
  }
  options.scope?.add({ get isDisposed() { return closed }, dispose })
  return { forLocation, prepare, dispose }
}
