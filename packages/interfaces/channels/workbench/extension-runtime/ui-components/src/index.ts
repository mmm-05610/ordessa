// T032 — C7 runtime core: instantiated registry, frozen selection, scope-owned
// register/bind, validate-then-publish batches, generations and identity-stable
// availability snapshots (contract §2/§3; UI-02..UI-06, UI-11; U01–U08).
// Diagnostics channel choice: swallowed subscriber throws are reported through
// the optional `onDiagnostics` hook on createUiComponentsService (see below).
// Domain-neutral: no business ids/providers here; controlled fixtures use
// generic names like `example.card` / `provider-a` only.
import type { ComponentType } from 'react'
import type { IDisposable, ResourceScope } from '@ordessa/extension-api'
import {
  type UiAvailability,
  type UiBinding,
  type UiComponentKey,
  type UiComponents,
  type UiImplementation,
  type UiRegistration,
  type UiRequirementDiagnostic,
  type UiScope,
  type UiSelection,
} from '../api/ui-components'
import { UiComponentsError } from '../api/errors'
import { uiBindingInternals, type UiBindingInternals } from './internal'

/** One reported subscriber failure; never carries props, components or bindings. */
export interface UiSubscriberFailure {
  readonly kind: 'ui-subscriber-failure'
  readonly componentId: string
  readonly major: number
  readonly message: string
  readonly cause: unknown
}

/** Service options; `onDiagnostics` receives every swallowed subscriber throw. */
export interface UiComponentsServiceOptions {
  readonly onDiagnostics?: (failure: UiSubscriberFailure) => void
}

/** Internal surface relied on by the later assembly task and by the U01–U08 tests. */
export interface UiComponentsService extends IDisposable {
  readonly uiComponents: UiComponents
  inspectRequirements(): readonly UiRequirementDiagnostic[]
}

/**
 * Read-back of the opaque {@link UiRegistration} handle: `registration()` in
 * api/ui-components.ts freezes `{ key, providerId, component }` and casts it,
 * so the fields are recovered here by cast. The public branded surface is not
 * weakened: callers still cannot assemble a UiRegistration by hand.
 */
interface RegistrationData {
  readonly key: UiComponentKey<any>
  readonly providerId: string
  readonly component: unknown
}

function readRegistration(item: UiRegistration): RegistrationData {
  return item as unknown as RegistrationData
}

/** One committed implementation contribution. Removal is guarded by record identity. */
interface RegistrationRecord {
  readonly key: UiComponentKey<any>
  readonly providerId: string
  readonly component: unknown
  readonly generation: number
}

/** Address of one (id, major) slot. Separated by NUL, which typed key ids do not carry. */
function slotKey(id: string, major: number): string {
  return `${id}\u0000${major}`
}

function sameStringArray(a: readonly number[] | undefined, b: readonly number[] | undefined): boolean {
  if (a === b) return true
  if (a === undefined || b === undefined) return false
  return a.length === b.length && a.every((v, i) => v === b[i])
}

/** Structural equality so unchanged recomputation keeps the old snapshot object (U08). */
function sameSnapshot(a: UiAvailability, b: UiAvailability): boolean {
  if (a.status !== b.status) return false
  switch (a.status) {
    case 'disposed':
      return true
    case 'ready': {
      const other = b as typeof a
      return a.providerId === other.providerId && a.generation === other.generation
    }
    case 'missing': {
      const other = b as typeof a
      return a.reason === other.reason
        && a.selectedProviderId === other.selectedProviderId
        && sameStringArray(a.seenMajors, other.seenMajors)
    }
  }
}

function sanitizeCause(cause: unknown): string {
  if (cause instanceof Error) return cause.message
  const text = String(cause)
  return text.length > 200 ? `${text.slice(0, 200)}...` : text
}

const DISPOSED_SNAPSHOT: UiAvailability = Object.freeze({ status: 'disposed' as const })

/** Consumer-owned, revocable binding (UI-05). Never exposes the component itself. */
class BindingImpl<P> implements UiBinding<P>, IDisposable {
  current: UiAvailability
  isDisposedFlag = false
  readonly listeners = new Set<() => void>()

  /** Symbol-keyed capability for the React layer only; not part of the public UiBinding type. */
  readonly [uiBindingInternals]: UiBindingInternals

  constructor(
    private readonly service: ServiceCore,
    readonly key: UiComponentKey<P>,
    readonly required: boolean,
  ) {
    this.current = service.computeSnapshot(key)
    this[uiBindingInternals] = {
      required,
      resolve: availability => service.resolveComponent(key, availability),
    }
  }

  get isDisposed(): boolean { return this.isDisposedFlag }

  getSnapshot = (): UiAvailability => this.current

  subscribe = (listener: () => void): (() => void) => {
    if (this.isDisposedFlag) return () => undefined
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  dispose(): void {
    if (this.isDisposedFlag) return
    this.isDisposedFlag = true
    this.service.releaseBinding(this)
    this.current = DISPOSED_SNAPSHOT
    this.service.notify([this])
  }

  /** Service teardown path: same effect as dispose() without re-entering release. */
  forceDispose(): void {
    if (this.isDisposedFlag) return
    this.isDisposedFlag = true
    this.current = DISPOSED_SNAPSHOT
    this.service.notify([this])
  }
}

/** Handle over one committed record; identity-guarded so an old handle cannot evict a newer record (U05). */
class RecordHandle implements IDisposable {
  private released = false
  constructor(private readonly service: ServiceCore, private readonly record: RegistrationRecord) {}
  get isDisposed(): boolean { return this.released }
  dispose(): void {
    if (this.released) return
    this.released = true
    this.service.removeRecord(this.record)
  }
}

/** One-shot handle covering a whole published batch; disposes each member handle. */
class BatchHandle implements IDisposable {
  private released = false
  constructor(private readonly handles: readonly IDisposable[]) {}
  get isDisposed(): boolean { return this.released }
  dispose(): void {
    if (this.released) return
    this.released = true
    for (const handle of this.handles) handle.dispose()
  }
}

/** Everything below is per-service state; there is no module-level registry (U07). */
class ServiceCore implements UiComponentsService {
  /** (id, major) -> selected providerId, copied and frozen at construction (UI-03). */
  private readonly selection = new Map<string, string>()
  /** (id, major) -> the one key object accepted by this host; per instance, never global (U04/U07). */
  private readonly keyIdentities = new Map<string, UiComponentKey<any>>()
  /** (id, major) -> providerId -> record. Different providers coexist (UI-03). */
  private readonly slots = new Map<string, Map<string, RegistrationRecord>>()
  private readonly bindings = new Set<BindingImpl<any>>()
  private generation = 0
  private closed = false
  isDisposed = false
  readonly uiComponents: UiComponents

  constructor(selection: UiSelection, private readonly options?: UiComponentsServiceOptions) {
    for (const entry of selection) {
      const slot = slotKey(entry.componentId, entry.major)
      if (this.selection.has(slot)) {
        throw new UiComponentsError('UI_SELECTION_DUPLICATE', `selection has two entries for ${entry.componentId} major ${entry.major}`)
      }
      this.selection.set(slot, entry.providerId)
    }
    this.uiComponents = {
      forScope: (scope: ResourceScope): UiScope => ({
        register: <P>(implementation: UiImplementation<P>): IDisposable =>
          this.install(scope, [{
            key: implementation.key,
            providerId: implementation.providerId,
            component: implementation.component,
          }]),
        registerBatch: (items: readonly UiRegistration[]): IDisposable =>
          this.install(scope, items.map(readRegistration)),
        bind: <P>(key: UiComponentKey<P>, bindOptions: { required: boolean }): UiBinding<P> =>
          this.bind(scope, key, bindOptions),
      }),
    }
  }

  /** Validate the whole new batch, then publish atomically; on failure nothing of it is published (U03). */
  private install(scope: ResourceScope, items: readonly RegistrationData[]): IDisposable {
    this.assertUsable(scope)
    const batchKeys = new Map<string, UiComponentKey<any>>()
    const batchProviders = new Set<string>()
    for (const item of items) {
      if (typeof item.providerId !== 'string' || item.providerId.length === 0) {
        throw new RangeError('UI registration requires a providerId')
      }
      if (!item.component) throw new RangeError('UI registration requires a component')
      const slot = slotKey(item.key.id, item.key.major)
      const known = this.keyIdentities.get(slot)
      if (known !== undefined && known !== item.key) {
        throw new UiComponentsError('UI_KEY_IDENTITY_CONFLICT', `${item.key.id} major ${item.key.major} is already represented by another key instance in this host`)
      }
      const batchKey = batchKeys.get(slot)
      if (batchKey !== undefined && batchKey !== item.key) {
        throw new UiComponentsError('UI_KEY_IDENTITY_CONFLICT', `batch carries two distinct keys for ${item.key.id} major ${item.key.major}`)
      }
      batchKeys.set(slot, item.key)
      const providerSlot = `${slot}\u0000${item.providerId}`
      if (batchProviders.has(providerSlot) || this.slotOf(item.key)?.has(item.providerId)) {
        throw new UiComponentsError('UI_PROVIDER_DUPLICATE', `${item.key.id} major ${item.key.major} already has a registration from ${item.providerId}`)
      }
      batchProviders.add(providerSlot)
    }
    // Pure validation above touched no state; claim keys and publish now.
    const handles: IDisposable[] = []
    for (const item of items) {
      const slot = slotKey(item.key.id, item.key.major)
      if (!this.keyIdentities.has(slot)) this.keyIdentities.set(slot, item.key)
      const record: RegistrationRecord = {
        key: item.key,
        providerId: item.providerId,
        component: item.component,
        generation: ++this.generation,
      }
      let providers = this.slots.get(slot)
      if (!providers) { providers = new Map(); this.slots.set(slot, providers) }
      providers.set(record.providerId, record)
      handles.push(new RecordHandle(this, record))
    }
    this.publish()
    const handle = handles.length === 1 ? handles[0] as IDisposable : new BatchHandle(handles)
    try {
      return scope.add(handle)
    } catch (error) {
      // Scope closed concurrently with the commit: roll the batch back and report closure.
      handle.dispose()
      if (scope.isDisposed) {
        throw new UiComponentsError('UI_SCOPE_CLOSED', `scope closed while publishing: ${sanitizeCause(error)}`)
      }
      throw error
    }
  }

  private bind<P>(scope: ResourceScope, key: UiComponentKey<P>, options: { required: boolean }): UiBinding<P> {
    this.assertUsable(scope)
    if (typeof options?.required !== 'boolean') throw new RangeError('UI binding requires a boolean `required`')
    const slot = slotKey(key.id, key.major)
    const known = this.keyIdentities.get(slot)
    if (known !== undefined && known !== key) {
      throw new UiComponentsError('UI_KEY_IDENTITY_CONFLICT', `${key.id} major ${key.major} is already represented by another key instance in this host`)
    }
    if (known === undefined) this.keyIdentities.set(slot, key)
    const binding = new BindingImpl<P>(this, key, options.required)
    try {
      scope.add(binding)
    } catch (error) {
      if (scope.isDisposed) {
        throw new UiComponentsError('UI_SCOPE_CLOSED', `scope closed while binding: ${sanitizeCause(error)}`)
      }
      throw error
    }
    this.bindings.add(binding)
    return binding
  }

  /** Closed scope (or disposed service) rejects register/registerBatch/bind synchronously (UI-04). */
  private assertUsable(scope: ResourceScope): void {
    if (this.closed) throw new UiComponentsError('UI_SCOPE_CLOSED', 'ui-components service is disposed')
    if (scope.isDisposed) throw new UiComponentsError('UI_SCOPE_CLOSED', 'resource scope is closed; registration/binding rejected')
  }

  private slotOf(key: UiComponentKey<any>): Map<string, RegistrationRecord> | undefined {
    return this.slots.get(slotKey(key.id, key.major))
  }

  /** Identity-guarded removal: only removes the map entry if it is still this exact record. */
  removeRecord(record: RegistrationRecord): void {
    const providers = this.slotOf(record.key)
    if (providers?.get(record.providerId) === record) {
      providers.delete(record.providerId)
      if (providers.size === 0) this.slots.delete(slotKey(record.key.id, record.key.major))
      this.publish()
    }
  }

  releaseBinding(binding: BindingImpl<any>): void {
    this.bindings.delete(binding)
  }

  computeSnapshot(key: UiComponentKey<any>): UiAvailability {
    const slot = slotKey(key.id, key.major)
    const selected = this.selection.get(slot)
    if (selected === undefined) {
      return Object.freeze({ status: 'missing' as const, reason: 'unselected' as const })
    }
    const record = this.slots.get(slot)?.get(selected)
    if (record !== undefined) {
      return Object.freeze({ status: 'ready' as const, providerId: selected, generation: record.generation })
    }
    // Selected provider absent. A different major of the same id may be installed — report it (UI-06).
    const prefix = `${key.id}\u0000`
    const majors = [...this.slots.keys()]
      .filter(address => address.startsWith(prefix))
      .map(address => Number(address.slice(prefix.length)))
      .filter(major => major !== key.major)
      .sort((a, b) => a - b)
    return Object.freeze(majors.length > 0
      ? { status: 'missing' as const, reason: 'provider-unavailable' as const, selectedProviderId: selected, seenMajors: Object.freeze(majors) }
      : { status: 'missing' as const, reason: 'provider-unavailable' as const, selectedProviderId: selected })
  }

  /** The component behind a ready availability, or `undefined` if the generation no longer matches. */
  resolveComponent(key: UiComponentKey<any>, availability: Extract<UiAvailability, { status: 'ready' }>): ComponentType<unknown> | undefined {
    const record = this.slots.get(slotKey(key.id, key.major))?.get(availability.providerId)
    if (record === undefined || record.generation !== availability.generation) return undefined
    return record.component as ComponentType<unknown>
  }

  /** Recompute once for every live binding, then notify exactly the changed ones (UI-06, U08). */
  private publish(): void {
    const changed: BindingImpl<any>[] = []
    for (const binding of [...this.bindings]) {
      const next = this.computeSnapshot(binding.key)
      if (!sameSnapshot(binding.current, next)) {
        binding.current = next
        changed.push(binding)
      }
    }
    this.notify(changed)
  }

  /** A throwing subscriber is reported via onDiagnostics and cannot break the commit nor other subscribers. */
  notify(bindings: readonly BindingImpl<any>[]): void {
    for (const binding of bindings) {
      for (const listener of [...binding.listeners]) {
        try {
          listener()
        } catch (cause) {
          const failure: UiSubscriberFailure = Object.freeze({
            kind: 'ui-subscriber-failure' as const,
            componentId: binding.key.id,
            major: binding.key.major,
            message: sanitizeCause(cause),
            cause,
          })
          try {
            this.options?.onDiagnostics?.(failure)
          } catch { /* a throwing diagnostics sink must not break notification either */ }
        }
      }
    }
  }

  /** Only currently-missing required bindings (UI-11); never props or components. */
  inspectRequirements(): readonly UiRequirementDiagnostic[] {
    const diagnostics: UiRequirementDiagnostic[] = []
    for (const binding of this.bindings) {
      const snapshot = binding.current
      if (!binding.required || binding.isDisposed || snapshot.status !== 'missing') continue
      diagnostics.push(Object.freeze({
        componentId: binding.key.id,
        major: binding.key.major,
        ...(snapshot.selectedProviderId !== undefined ? { selectedProviderId: snapshot.selectedProviderId } : {}),
        reason: snapshot.reason,
        ...(snapshot.seenMajors !== undefined ? { seenMajors: snapshot.seenMajors } : {}),
      }))
    }
    return Object.freeze(diagnostics)
  }

  dispose(): void {
    if (this.isDisposed) return
    this.isDisposed = true
    this.closed = true
    this.slots.clear()
    this.keyIdentities.clear()
    const live = [...this.bindings]
    this.bindings.clear()
    for (const binding of live) binding.forceDispose()
  }
}

/**
 * Assembly entry (contract §3): copies and deep-freezes the product selection,
 * validates duplicate (componentId, major), and builds one host-scoped service.
 * There is no API to change the selection while running (UI-03, U02).
 */
export function createUiComponentsService(
  selection: UiSelection,
  options?: UiComponentsServiceOptions,
): UiComponentsService {
  const frozen = Object.freeze(selection.map(entry => Object.freeze({
    componentId: entry.componentId,
    major: entry.major,
    providerId: entry.providerId,
  })))
  return new ServiceCore(frozen, options)
}
