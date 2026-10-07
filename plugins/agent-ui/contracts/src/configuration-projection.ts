/**
 * Read-only frontend projection over the Agent domain's backend owner.
 *
 * `target` must already be resolved by trusted Agent/session evidence. This
 * module never derives a target, creates a local Agent owner, or treats UI
 * selection as confirmed configuration. Writes are serialized through the
 * supplied AgentOwnerPort; snapshots only come from that port or an optional
 * authorized observation adapter.
 */
import type { ResourceScope } from '@ordessa/extension-api'

import type {
  AgentOwnerPort,
  ConfigSnapshotView,
  OperationReceipt,
  OwnerAnswer,
} from './owner-port'

export type ProjectionGeneration = string | number

export interface ConfigurationProjectionSnapshot {
  status: 'loading' | 'ready' | 'unknown' | 'unavailable'
  target: string
  generation?: ProjectionGeneration
  config?: ConfigSnapshotView
  queryHint?: string
  reason?: string
}

/**
 * Adapter for the frozen Agent observeConfig capability. The adapter owns
 * binding/cursor/credit/authorization mechanics and delivers full snapshots;
 * release must detach that observation idempotently.
 */
export type ConfigurationObserveSource = (
  target: string,
  onSnapshot: (snapshot: ConfigSnapshotView) => void,
  onUnavailable: (reason: string) => void,
) => { release(): void } | (() => void)

export interface ConfigurationProjectionOptions {
  /** A canonical target already resolved by the trusted Agent/session owner. */
  target: string
  /** Production callers provide the backend-backed owner port. */
  owner: AgentOwnerPort
  /** The scope that owns this projection; disposal fences all late responses. */
  scope?: ResourceScope
  /** Trusted connection/session generation captured when this projection opens. */
  generation?: ProjectionGeneration
  /** Rechecks the caller's trusted generation evidence after each await. */
  isGenerationCurrent?: (generation: ProjectionGeneration | undefined) => boolean
  /** Optional authorized Agent observeConfig adapter; no timer polling is used. */
  observeSource?: ConfigurationObserveSource
}

export interface ConfigurationProjection {
  getSnapshot(): ConfigurationProjectionSnapshot
  subscribe(listener: () => void): () => void
  refresh(): Promise<ConfigurationProjectionSnapshot>
  dispatch(
    patch: Readonly<Record<string, unknown>>,
    options?: { unset?: ReadonlyArray<string>; sourceRef?: string },
  ): Promise<OwnerAnswer<OperationReceipt>>
  close(): void
  dispose(): void
}

function copyFrozenValue(value: unknown, copies: WeakMap<object, object>): unknown {
  if (value === null || (typeof value !== 'object' && typeof value !== 'function')) return value
  if (typeof value === 'function') throw new TypeError('Agent config contains a function')
  const prior = copies.get(value)
  if (prior) return prior
  if (Array.isArray(value)) {
    const copy: unknown[] = new Array(value.length)
    copies.set(value, copy)
    for (const key of Reflect.ownKeys(value)) {
      if (key === 'length') continue
      const descriptor = Object.getOwnPropertyDescriptor(value, key)
      if (!descriptor || !('value' in descriptor)) throw new TypeError('Agent config contains an accessor')
      Object.defineProperty(copy, key, {
        value: copyFrozenValue(descriptor.value, copies),
        enumerable: descriptor.enumerable,
        configurable: false,
        writable: false,
      })
    }
    return Object.freeze(copy)
  }
  const prototype = Object.getPrototypeOf(value)
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError('Agent config contains an unsupported value')
  }
  const copy: Record<string | symbol, unknown> = Object.create(prototype)
  copies.set(value, copy)
  for (const key of Reflect.ownKeys(value)) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key)
    if (!descriptor || !('value' in descriptor)) throw new TypeError('Agent config contains an accessor')
    Object.defineProperty(copy, key, {
      value: copyFrozenValue(descriptor.value, copies),
      enumerable: descriptor.enumerable,
      configurable: false,
      writable: false,
    })
  }
  return Object.freeze(copy)
}

function copySnapshot(source: ConfigSnapshotView): ConfigSnapshotView {
  if (!Number.isSafeInteger(source.revision) || source.revision < 0 || typeof source.ownerRef !== 'string') {
    throw new TypeError('Agent config snapshot has an invalid owner revision')
  }
  const copies = new WeakMap<object, object>()
  const fields = copyFrozenValue(source.fields, copies) as ConfigSnapshotView['fields']
  const resolved = copyFrozenValue(source.resolved, copies) as ConfigSnapshotView['resolved']
  return Object.freeze({
    ownerRef: source.ownerRef,
    revision: source.revision,
    observedEvidence: source.observedEvidence,
    fields,
    resolved,
    ...(source.operations === undefined ? {} : { operations: copyFrozenValue(source.operations, copies) as ConfigSnapshotView['operations'] }),
  })
}

function sameGraph(left: unknown, right: unknown, pairs = new WeakMap<object, object>()): boolean {
  if (Object.is(left, right)) return true
  if (left === null || right === null || typeof left !== 'object' || typeof right !== 'object') return false
  if (Array.isArray(left) !== Array.isArray(right)) return false
  const prior = pairs.get(left)
  if (prior) return prior === right
  pairs.set(left, right)
  if (Object.getPrototypeOf(left) !== Object.getPrototypeOf(right)) return false
  const leftKeys = Reflect.ownKeys(left)
  const rightKeys = Reflect.ownKeys(right)
  if (leftKeys.length !== rightKeys.length) return false
  for (const key of leftKeys) {
    if (!rightKeys.includes(key)) return false
    const leftDescriptor = Object.getOwnPropertyDescriptor(left, key)
    const rightDescriptor = Object.getOwnPropertyDescriptor(right, key)
    if (!leftDescriptor || !rightDescriptor || !('value' in leftDescriptor) || !('value' in rightDescriptor)) return false
    if (!sameGraph(leftDescriptor.value, rightDescriptor.value, pairs)) return false
  }
  return true
}

function sameSnapshot(left: ConfigSnapshotView, right: ConfigSnapshotView): boolean {
  return left.ownerRef === right.ownerRef
    && left.revision === right.revision
    && left.observedEvidence === right.observedEvidence
    && sameGraph(left.fields, right.fields)
    && sameGraph(left.resolved, right.resolved)
    && sameGraph(left.operations, right.operations)
}

/**
 * Creates one scoped read-only view over the canonical backend owner target.
 * Multiple windows create independent clients and converge by backend read or
 * the supplied authorized observeConfig source.
 */
export function createConfigurationProjection(options: ConfigurationProjectionOptions): ConfigurationProjection {
  if (!options.target.trim()) throw new TypeError('A trusted canonical Agent target is required')

  const target = options.target
  const generation = options.generation
  const listeners = new Set<() => void>()
  let snapshot: ConfigurationProjectionSnapshot = Object.freeze({
    status: 'loading', target, ...(generation === undefined ? {} : { generation }),
  })
  let closed = false
  let releaseObservation: (() => void) | undefined
  let dispatchTail: Promise<void> = Promise.resolve()
  let latestRevision = -1
  let latestConfig: ConfigSnapshotView | undefined
  let conflictedRevision = -1

  const isCurrent = (): boolean => {
    if (closed || options.scope?.isDisposed) return false
    try { return options.isGenerationCurrent?.(generation) ?? true } catch { return false }
  }

  const currentConfig = (): ConfigSnapshotView | undefined =>
    snapshot.status === 'loading' ? undefined : snapshot.config

  const publish = (next: ConfigurationProjectionSnapshot): void => {
    if (!isCurrent()) return
    snapshot = Object.freeze(next)
    for (const listener of [...listeners]) {
      try { listener() } catch { /* projections do not let consumers break one another */ }
    }
  }

  const acceptSnapshot = (candidate: ConfigSnapshotView): void => {
    if (!isCurrent()) return
    if (Number.isSafeInteger(candidate?.revision) && candidate.revision < latestRevision) return
    try {
      const config = copySnapshot(candidate)
      if (config.revision < latestRevision) return
      if (latestConfig && config.ownerRef !== latestConfig.ownerRef) {
        conflictedRevision = Math.max(conflictedRevision, config.revision)
        publish({
          status: 'unavailable', target,
          ...(generation === undefined ? {} : { generation }),
          reason: 'Agent config owner changed for a canonical target',
          config: latestConfig,
        })
        return
      }
      if (config.revision <= conflictedRevision) return
      if (config.revision === latestRevision) {
        if (latestConfig && !sameSnapshot(latestConfig, config)) {
          conflictedRevision = config.revision
          publish({
            status: 'unavailable', target,
            ...(generation === undefined ? {} : { generation }),
            reason: 'Agent config owner returned conflicting data at one revision',
            config: latestConfig,
          })
        }
        return
      }
      latestRevision = config.revision
      latestConfig = config
      publish({ status: 'ready', target, ...(generation === undefined ? {} : { generation }), config })
    } catch (cause) {
      publish({
        status: 'unavailable', target,
        ...(generation === undefined ? {} : { generation }),
        reason: `invalid Agent config projection: ${String(cause)}`,
        ...(currentConfig() === undefined ? {} : { config: currentConfig() }),
      })
    }
  }

  const refresh = async (): Promise<ConfigurationProjectionSnapshot> => {
    if (!isCurrent()) return snapshot
    const revisionAtRequest = latestRevision
    let answer: OwnerAnswer<ConfigSnapshotView>
    try {
      answer = await options.owner.readConfig(target)
    } catch {
      answer = { kind: 'unknown', queryHint: 'wire:agent.config.read' }
    }
    if (!isCurrent()) return snapshot
    if (latestRevision > revisionAtRequest && answer.kind !== 'ok') return snapshot
    if (answer.kind === 'ok') {
      acceptSnapshot(answer.value)
    } else if (answer.kind === 'unknown') {
      publish({
        status: 'unknown', target,
        ...(generation === undefined ? {} : { generation }),
        queryHint: answer.queryHint,
        ...(currentConfig() === undefined ? {} : { config: currentConfig() }),
      })
    } else {
      publish({
        status: 'unavailable', target,
        ...(generation === undefined ? {} : { generation }),
        reason: answer.reason,
        ...(currentConfig() === undefined ? {} : { config: currentConfig() }),
      })
    }
    return snapshot
  }

  const dispatch = (
    patch: Readonly<Record<string, unknown>>,
    submitOptions?: { unset?: ReadonlyArray<string>; sourceRef?: string },
  ): Promise<OwnerAnswer<OperationReceipt>> => {
    let capturedPatch: Readonly<Record<string, unknown>>
    let capturedOptions: { unset?: ReadonlyArray<string>; sourceRef?: string } | undefined
    try {
      capturedPatch = copyFrozenValue(patch, new WeakMap<object, object>()) as Readonly<Record<string, unknown>>
      if (capturedPatch === null || Array.isArray(capturedPatch)
        || (Object.getPrototypeOf(capturedPatch) !== Object.prototype && Object.getPrototypeOf(capturedPatch) !== null)) {
        throw new TypeError('Agent config patch must be a plain record')
      }
      capturedOptions = submitOptions === undefined ? undefined : Object.freeze({
        ...(submitOptions.unset === undefined
          ? {}
          : { unset: copyFrozenValue(submitOptions.unset, new WeakMap<object, object>()) as ReadonlyArray<string> }),
        ...(submitOptions.sourceRef === undefined ? {} : { sourceRef: submitOptions.sourceRef }),
      })
      if (capturedOptions?.unset?.some(field => typeof field !== 'string')) {
        throw new TypeError('Agent config unset fields must be strings')
      }
    } catch (cause) {
      return Promise.resolve({ kind: 'unavailable', reason: `invalid Agent config patch: ${String(cause)}` })
    }
    const operation = dispatchTail.then(async (): Promise<OwnerAnswer<OperationReceipt>> => {
      if (!isCurrent()) {
        return { kind: 'unavailable', reason: 'Agent configuration projection scope is retired' }
      }
      let answer: OwnerAnswer<OperationReceipt>
      try {
        answer = await options.owner.submitConfigOperation(target, capturedPatch, capturedOptions)
      } catch {
        answer = { kind: 'unknown', queryHint: 'wire:agent.config.submitOperation' }
      }
      if (!isCurrent()) return answer
      if (answer.kind === 'unknown' || (answer.kind === 'ok' && answer.value.state === 'unknown')) {
        publish({ status: 'unknown', target,
          ...(generation === undefined ? {} : { generation }),
          queryHint: answer.kind === 'unknown' ? answer.queryHint : `operation:${answer.value.operationId}`,
          ...(currentConfig() === undefined ? {} : { config: currentConfig() }) })
      }
      // Unknown remains unknown: refresh may read current state, but it cannot
      // establish whether this operation applied and never resends it.
      if (answer.kind === 'ok' && answer.value.state !== 'unknown' && answer.value.state !== 'conflict') {
        await refresh()
      }
      return answer
    })
    dispatchTail = operation.then(() => undefined, () => undefined)
    return operation
  }

  const close = (): void => {
    if (closed) return
    closed = true
    try { releaseObservation?.() } catch { /* close is idempotent and best-effort */ }
    releaseObservation = undefined
    listeners.clear()
  }

  if (options.scope?.isDisposed) {
    close()
  } else {
    if (options.observeSource) {
      try {
        const observation = options.observeSource(target, acceptSnapshot, reason => {
          publish({ status: 'unknown', target,
            ...(generation === undefined ? {} : { generation }),
            reason, ...(currentConfig() === undefined ? {} : { config: currentConfig() }) })
        })
        releaseObservation = typeof observation === 'function'
          ? observation
          : () => observation.release()
        if (closed) releaseObservation()
      } catch (cause) {
        publish({
          status: 'unavailable', target,
          ...(generation === undefined ? {} : { generation }),
          reason: `Agent config observation unavailable: ${String(cause)}`,
        })
      }
    }
    if (options.scope) options.scope.add({ get isDisposed() { return closed }, dispose: close })
  }

  return {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      if (!isCurrent()) return () => undefined
      listeners.add(listener)
      let released = false
      return () => {
        if (released) return
        released = true
        listeners.delete(listener)
      }
    },
    refresh,
    dispatch,
    close,
    dispose: close,
  }
}
