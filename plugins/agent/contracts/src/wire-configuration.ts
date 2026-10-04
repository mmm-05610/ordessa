import type { ResourceScope } from '@ordessa/extension-api'
import type { AgentNativeSessionOwner, AgentSessionLocation, AgentSessions } from './agent'
import { createAgentOwnerPort, type WireCall } from './owner-port'
import { createConfigurationProjection, type ConfigurationProjection, type ConfigurationObserveSource,
  type ConfigurationProjectionSnapshot } from './configuration-projection'
import type { ConfigSnapshotView } from './owner-port'
import { createSubmissionConditionsCache } from './capture-conditions'

type Location = { readonly kind: 'draft' | 'session'; readonly draftId?: string; readonly sessionId?: string;
  readonly connectionId?: string; readonly serverInstanceId?: string; readonly runtimeGeneration?: number;
  readonly contextRevision: number; readonly projectId?: string; readonly harnessId?: string }
type Wire = { readonly ready: boolean; readonly scope: string | null; call: WireCall }
type SharedProjection = { projection: ConfigurationProjection; refs: number }
type ClientProjection = ConfigurationProjection & { retire(reason: string, notify: boolean): void }
type SubmissionDeclaration = Readonly<{
  available?: unknown
  namespace?: unknown
  principalScope?: unknown
  schema?: unknown
  mode?: unknown
  nativeBound?: unknown
}>
type BoundSubmission = {
  readonly target: string
  readonly generation: string | number
  readonly submission?: SubmissionDeclaration
  readonly wireScope: string
  readonly runtimeGeneration?: number
  readonly projection: ClientProjection
}
export interface AgentSubmissionBinding {
  readonly target: string
  readonly generation: string | number
  readonly namespace: string
  readonly principalScope: string
  readonly schema: string
  readonly mode: 'existing' | 'createWithConfig'
  readonly configOperationIds: readonly string[]
}
const transportProjections = new WeakMap<Wire, Map<string, SharedProjection>>()

function locationBindingKey(location: Location): string {
  return JSON.stringify([
    location.kind, location.sessionId ?? null, location.draftId ?? null, location.connectionId ?? null,
    location.serverInstanceId ?? null, location.harnessId ?? null, location.runtimeGeneration ?? null,
    location.projectId ?? null,
  ])
}

function copySubmissionDeclaration(value: unknown): SubmissionDeclaration | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined
  const copy: Record<string, unknown> = {}
  for (const key of ['available', 'namespace', 'principalScope', 'schema', 'mode', 'nativeBound'] as const) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key)
    if (descriptor && !('value' in descriptor)) return undefined
    if (descriptor) copy[key] = descriptor.value
  }
  return Object.freeze(copy) as SubmissionDeclaration
}

function clientProjection(base: ConfigurationProjection, onRelease: (reason: string) => void): ClientProjection {
  let retiredReason: string | undefined
  let retiredSnapshot: ConfigurationProjectionSnapshot | undefined
  const listeners = new Set<() => void>()
  const detachBase = base.subscribe(() => {
    if (retiredReason !== undefined) return
    for (const listener of [...listeners]) {
      try { listener() } catch { /* consumer callbacks cannot break sibling readers */ }
    }
  })
  const facade: ClientProjection = {
    getSnapshot() {
      const current = base.getSnapshot()
      if (retiredReason === undefined) return current
      return retiredSnapshot!
    },
    subscribe(listener) {
      if (retiredReason !== undefined) return () => undefined
      listeners.add(listener)
      let released = false
      return () => {
        if (released) return
        released = true
        listeners.delete(listener)
      }
    },
    async refresh() {
      if (retiredReason !== undefined) return facade.getSnapshot()
      await base.refresh()
      return facade.getSnapshot()
    },
    dispatch(patch, submitOptions) {
      if (retiredReason !== undefined) {
        return Promise.resolve({ kind: 'unavailable', reason: retiredReason })
      }
      return base.dispatch(patch, submitOptions)
    },
    close() { onRelease('Agent configuration projection closed') },
    dispose() { onRelease('Agent configuration projection disposed') },
    retire(reason, notify) {
      if (retiredReason !== undefined) return
      retiredReason = reason
      retiredSnapshot = Object.freeze({
        ...base.getSnapshot(), status: 'unavailable', reason,
      })
      detachBase()
      if (notify) {
        for (const listener of [...listeners]) {
          try { listener() } catch { /* teardown continues */ }
        }
      }
      listeners.clear()
    },
  }
  return facade
}

/** Backend-issued identity only. This client contains projections, never owners. */
export function createWireConfigurationClient(options: { wire: Wire; sessions: AgentSessions; scope?: ResourceScope }) {
  const projections = new Map<string, ClientProjection>()
  const projectionGenerations = new Map<string, number | undefined>()
  const submissionBindings = new Map<string, BoundSubmission>()
  const conditions = createSubmissionConditionsCache()
  let closed = false
  const owner = createAgentOwnerPort((method, params) => options.wire.call(method, params))

  function releaseProjection(key: string, facade: ClientProjection, reason: string, notify = false): void {
    if (projections.get(key) !== facade) {
      facade.retire(reason, notify)
      return
    }
    projections.delete(key)
    projectionGenerations.delete(key)
    for (const [locationKey, binding] of submissionBindings) {
      if (binding.projection === facade) submissionBindings.delete(locationKey)
      if (binding.projection === facade) conditions.invalidate(locationKey)
    }
    facade.retire(reason, notify)
    const shared = transportProjections.get(options.wire)
    const entry = shared?.get(key)
    if (!entry) return
    entry.refs -= 1
    if (entry.refs <= 0) {
      entry.projection.close()
      shared?.delete(key)
    }
  }

  const unsubscribeSessions = options.sessions.subscribe(() => {
    let currentGeneration: number | undefined
    try { currentGeneration = options.sessions.getSnapshot().runtimeGeneration } catch { /* missing evidence retires scoped views */ }
    for (const [key, facade] of [...projections]) {
      const expectedGeneration = projectionGenerations.get(key)
      if (expectedGeneration !== undefined && currentGeneration !== expectedGeneration) {
        releaseProjection(key, facade, 'Agent session runtime generation changed', true)
      }
    }
  })

  async function warmConditions(locationKey: string, binding: BoundSubmission) {
    conditions.invalidate(locationKey)
    if (binding.submission?.available !== true) return
    const token = conditions.begin(locationKey, {
      wireScope: binding.wireScope, generation: binding.generation, target: binding.target,
    })
    try {
      const answer = await options.wire.call('agent.submission.capture.read', {
        target: binding.target, mode: binding.submission.mode,
      })
      if (closed || options.scope?.isDisposed || submissionBindings.get(locationKey) !== binding
          || options.wire.scope !== binding.wireScope) return
      if (answer.kind === 'Accepted') conditions.complete(token, answer.result)
    } catch { /* Missing native conditions disables only reliable capture, never configuration UI. */ }
  }

  async function forLocation(location: Location): Promise<ConfigurationProjection> {
    if (closed || options.scope?.isDisposed || !options.wire.ready || !options.wire.scope) {
      throw new Error('Agent configuration transport unavailable')
    }
    const wireScope = options.wire.scope
    const runtimeGenerationAtStart = options.sessions.getSnapshot().runtimeGeneration
    let nativeOwner: AgentNativeSessionOwner | undefined
    if (location.kind === 'session') {
      if (!location.sessionId || !location.connectionId) {
        throw new Error('Agent configuration native owner lookup requires an exact session route')
      }
      const lookup = options.sessions.nativeOwnerForLocation
      if (!lookup) throw new Error('Agent configuration native owner lookup unavailable')
      const ownerLocation: AgentSessionLocation = {
        ...location, kind: 'session', sessionId: location.sessionId, connectionId: location.connectionId,
        ...(location.serverInstanceId ? { serverInstanceId: location.serverInstanceId } : {}),
        ...(location.harnessId ? { harnessId: location.harnessId } : {}),
      }
      nativeOwner = lookup.call(options.sessions, ownerLocation)
      const ownerValues = [nativeOwner.sessionId, nativeOwner.serverInstanceId, nativeOwner.connectionId,
        nativeOwner.nativeSessionId, nativeOwner.harnessId, nativeOwner.workspaceId]
      if (ownerValues.some(value => typeof value !== 'string' || value.length === 0)
          || nativeOwner.sessionId !== location.sessionId
          || (location.serverInstanceId && nativeOwner.serverInstanceId !== location.serverInstanceId)
          || (location.harnessId && nativeOwner.harnessId !== location.harnessId)) {
        throw new Error('Agent configuration native owner route identity changed')
      }
    }
    const result = await options.wire.call('agent.session.resolve', {
      location, ...(nativeOwner ? { nativeOwner } : {}),
    })
    if (result.kind !== 'Accepted') throw new Error(`Agent target resolution ${result.kind}: ${result.reason}`)
    const target = result.result.target
    const generation = result.result.generation
    if (typeof target !== 'string' || !target || (typeof generation !== 'number' && typeof generation !== 'string')) {
      throw new Error('Agent target resolution lacks canonical identity/generation')
    }
    if (closed || options.scope?.isDisposed || !options.wire.ready || options.wire.scope !== wireScope) {
      throw new Error('Agent target binding changed')
    }
    const runtimeGeneration = options.sessions.getSnapshot().runtimeGeneration
    if (runtimeGeneration !== runtimeGenerationAtStart
      || (location.runtimeGeneration !== undefined && runtimeGeneration !== location.runtimeGeneration)) {
      throw new Error('Agent session runtime generation changed during target resolution')
    }
    const submission = copySubmissionDeclaration(result.result.submission)
    const boundLocationKey = locationBindingKey(location)
    const key = JSON.stringify([wireScope, target, generation, runtimeGeneration ?? null])
    let projection = projections.get(key)
    if (projection) {
      await projection.refresh()
      submissionBindings.set(boundLocationKey, {
        target, generation, submission, wireScope, runtimeGeneration, projection,
      })
      await warmConditions(boundLocationKey, submissionBindings.get(boundLocationKey)!)
      return projection
    }
    let shared = transportProjections.get(options.wire)
    if (!shared) { shared = new Map(); transportProjections.set(options.wire, shared) }
    let sharedEntry = shared.get(key)
    if (sharedEntry) {
      sharedEntry.refs += 1
    } else {
      const declaration = result.result.observation as Record<string, unknown> | undefined
      const observeSource: ConfigurationObserveSource | undefined = declaration
        && typeof declaration.method === 'string' && typeof declaration.releaseMethod === 'string'
        && typeof declaration.environment === 'string'
        ? (_target, deliver, unavailable) => {
          let released = false
          let subscriptionId: string | undefined
          let remoteReleaseSent = false
          let cursor: string | null = null
          let sourceIdentity: string | undefined
          const releaseRemote = async () => {
            if (remoteReleaseSent || !subscriptionId || !options.wire.ready || options.wire.scope !== wireScope) return
            remoteReleaseSent = true
            await options.wire.call(String(declaration.releaseMethod), {
              target, generation, location, subscriptionId,
            }) // A lost release remains bounded by the Environment's lease.
          }
          const observe = async () => {
            try {
              while (!released && options.wire.ready && options.wire.scope === wireScope) {
                const answer = await options.wire.call(String(declaration.method), {
                  target, generation, location, credits: 1, cursor,
                  ...(nativeOwner ? { nativeOwner } : {}),
                  ...(subscriptionId === undefined ? {} : { subscriptionId }),
                })
                if (answer.kind !== 'Accepted') {
                  if (!released) unavailable(`configuration observation ${answer.kind}: ${answer.reason}`)
                  break // Never reconnect or substitute another binding implicitly.
                }
                const batch = answer.result
                if (typeof batch.subscription_id !== 'string') throw new Error('observation lacks subscription identity')
                if (subscriptionId !== undefined && subscriptionId !== batch.subscription_id) throw new Error('observation identity changed')
                subscriptionId = batch.subscription_id
                if (released || !options.wire.ready || options.wire.scope !== wireScope) break
                if (batch.resync_required === true) throw new Error('configuration observation requires resync')
                if (!Array.isArray(batch.frames) || batch.frames.length > 1) throw new Error('observation exceeded credit')
                for (const frame of batch.frames as Array<Record<string, unknown>>) {
                  const source = frame.source as Record<string, unknown> | undefined
                  if (source?.environment !== declaration.environment) throw new Error('observation environment changed')
                  const identity = JSON.stringify(source)
                  if (sourceIdentity !== undefined && sourceIdentity !== identity) throw new Error('observation source generation changed')
                  sourceIdentity = identity
                  if (frame.kind !== 'snapshot' || typeof frame.cursor !== 'string') throw new Error('configuration observation gap/revocation')
                  cursor = frame.cursor
                  deliver(frame.value as ConfigSnapshotView)
                }
                if (typeof batch.cursor === 'string') cursor = batch.cursor
              }
              if (!released && (!options.wire.ready || options.wire.scope !== wireScope)) unavailable('configuration observation transport changed')
            } catch (cause) {
              if (!released) unavailable(String(cause))
            } finally {
              await releaseRemote().catch(() => undefined)
            }
          }
          void observe()
          return { release() { released = true; void releaseRemote().catch(() => undefined) } }
        } : undefined
      const base = createConfigurationProjection({ target, owner, generation,
        observeSource,
        isGenerationCurrent: () => options.wire.scope === wireScope
          && (runtimeGeneration === undefined || options.sessions.getSnapshot().runtimeGeneration === runtimeGeneration),
      })
      sharedEntry = { projection: base, refs: 1 }
      shared.set(key, sharedEntry)
    }
    const facade = clientProjection(sharedEntry.projection, reason => releaseProjection(key, facade, reason))
    projection = facade
    projections.set(key, facade)
    projectionGenerations.set(key, runtimeGeneration)
    await facade.refresh()
    submissionBindings.set(boundLocationKey, {
      target, generation, submission, wireScope, runtimeGeneration, projection,
    })
    await warmConditions(boundLocationKey, submissionBindings.get(boundLocationKey)!)
    return projection
  }

  function captureSubmissionBinding(location: Location): AgentSubmissionBinding {
    if (closed || options.scope?.isDisposed || !options.wire.ready || !options.wire.scope) {
      throw new Error('Agent submission binding transport unavailable')
    }
    const binding = submissionBindings.get(locationBindingKey(location))
    if (!binding) throw new Error('Agent submission binding has not been resolved for this location')
    if (binding.wireScope !== options.wire.scope) throw new Error('Agent submission binding transport scope changed')
    const runtimeGeneration = options.sessions.getSnapshot().runtimeGeneration
    if (binding.runtimeGeneration === undefined || runtimeGeneration !== binding.runtimeGeneration
        || (location.runtimeGeneration !== undefined && location.runtimeGeneration !== runtimeGeneration)) {
      throw new Error('Agent submission binding runtime generation changed or is unavailable')
    }
    if (submissionBindings.get(locationBindingKey(location)) !== binding) {
      throw new Error('Agent submission binding was retired')
    }
    const state = binding.projection.getSnapshot()
    if (state.status !== 'ready' || !state.config || state.target !== binding.target
        || state.generation !== binding.generation) {
      throw new Error(`Agent submission configuration projection is ${state.status}`)
    }
    const metadata = binding.submission
    if (!metadata || metadata.available !== true) {
      throw new Error('Agent submission capability metadata is missing or unavailable')
    }
    const namespace = metadata.namespace
    const principalScope = metadata.principalScope
    const schema = metadata.schema
    const mode = metadata.mode
    if (typeof namespace !== 'string' || !namespace.trim() || namespace.trim() !== namespace
        || typeof principalScope !== 'string' || !principalScope.trim() || principalScope.trim() !== principalScope
        || typeof schema !== 'string' || !schema.trim() || schema.trim() !== schema
        || (mode !== 'existing' && mode !== 'createWithConfig')) {
      throw new Error('Agent submission capability metadata is incomplete')
    }
    if ((location.kind === 'draft' && mode !== 'createWithConfig' && metadata.nativeBound !== true)
        || (location.kind === 'session' && mode !== 'existing')) {
      throw new Error('Agent submission mode does not match the resolved location')
    }
    const operations = state.config.operations
    if (!Array.isArray(operations)) throw new Error('Agent submission configuration operations are unknown')
    const operationIds: string[] = []
    const seenOperationIds = new Set<string>()
    for (const operation of operations) {
      if (!operation || typeof operation.operationId !== 'string' || !operation.operationId.trim()
          || operation.operationId.trim() !== operation.operationId || seenOperationIds.has(operation.operationId)) {
        throw new Error('Agent submission configuration operation identity is invalid')
      }
      seenOperationIds.add(operation.operationId)
      if (operation.state === 'pending') operationIds.push(operation.operationId)
      else if (operation.state !== 'applied') {
        throw new Error(`Agent submission configuration operation is ${String(operation.state)}`)
      }
    }
    return Object.freeze({
      target: binding.target,
      generation: binding.generation,
      namespace,
      principalScope,
      schema,
      mode,
      configOperationIds: Object.freeze(operationIds),
    })
  }

  function captureSubmissionConditions(location: Location) {
    const binding = captureSubmissionBinding(location)
    const bound = submissionBindings.get(locationBindingKey(location))!
    const state = bound.projection.getSnapshot()
    return conditions.capture(locationBindingKey(location), {
      wireScope: bound.wireScope, target: binding.target, generation: binding.generation,
      ownerRef: state.config!.ownerRef, revision: state.config!.revision,
    })
  }

  async function prepare(snapshot: { target: Location; submissionId: string; draftRevision: number }) {
    try {
      if (!snapshot.submissionId || !snapshot.submissionId.trim()
          || !Number.isSafeInteger(snapshot.draftRevision) || snapshot.draftRevision < 0) {
        return { status: 'refused' as const, reason: 'Agent submission preparation identity is incomplete' }
      }
      captureSubmissionBinding(snapshot.target)
      return { status: 'ready' as const }
    } catch (error) { return { status: 'refused' as const, reason: String(error) } }
  }
  function dispose() {
    if (closed) return
    closed = true
    conditions.invalidate()
    unsubscribeSessions()
    for (const [key, projection] of [...projections]) {
      releaseProjection(key, projection, 'Agent configuration client disposed')
    }
  }
  options.scope?.add({ get isDisposed() { return closed }, dispose })
  return { forLocation, captureSubmissionBinding, captureSubmissionConditions, prepare, dispose }
}
