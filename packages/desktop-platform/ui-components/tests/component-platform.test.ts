// T032 — U01–U08 acceptance for the C7 runtime core (registry/selection/batch/
// generations/snapshots). All fixtures are generic: component ids `example.*`,
// provider ids `provider-a|b|x|y`. Each test builds a fresh service, which also
// proves there is no module-level registry (U07).
import { describe, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import {
  UiComponentsError,
  defineUiComponent,
  registration,
  type UiAvailability,
  type UiComponentKey,
  type UiErrorCode,
  type UiImplementation,
} from '../api/ui-components'
import {
  createUiComponentsService,
  type UiComponentsService,
  type UiSubscriberFailure,
} from '../src/index'

const CARD = 'example.card'
const PANEL = 'example.panel'
const NOTE = 'example.note'

/** Stand-in component; the runtime core never renders it. */
const Stub = () => null

function impl<P>(key: UiComponentKey<P>, providerId: string): UiImplementation<P> {
  return { key, providerId, component: Stub }
}

function selectionOf(...entries: readonly (readonly [string, number, string])[]) {
  return entries.map(([componentId, major, providerId]) => ({ componentId, major, providerId }))
}

function expectUiError(action: () => unknown, code: UiErrorCode): void {
  let caught: unknown
  let threw = false
  try { action() } catch (error) { threw = true; caught = error }
  if (!threw) throw new Error(`expected UiComponentsError ${code}, but nothing was thrown`)
  expect(caught).toBeInstanceOf(UiComponentsError)
  expect((caught as UiComponentsError).code).toBe(code)
}

function expectReady(snapshot: UiAvailability): Extract<UiAvailability, { status: 'ready' }> {
  expect(snapshot.status).toBe('ready')
  if (snapshot.status !== 'ready') throw new Error('expected a ready availability snapshot')
  return snapshot
}

function missingProviderUnavailable(selectedProviderId: string): UiAvailability {
  return { status: 'missing', reason: 'provider-unavailable', selectedProviderId }
}

describe('U01 load-order independence', () => {
  it('U01 provider-first and consumer-first load orders end in the same ready snapshot', () => {
    const selection = selectionOf([CARD, 1, 'provider-a'])

    // Provider-first: register, then bind.
    const keyFirst = defineUiComponent<unknown>(CARD, 1)
    const svc1 = createUiComponentsService(selection)
    const ui1 = svc1.uiComponents.forScope(new OwnedResources())
    ui1.register(impl(keyFirst, 'provider-a'))
    const bindFirst = ui1.bind(keyFirst, { required: true })
    const snapFirst = bindFirst.getSnapshot()
    expect(snapFirst).toEqual({ status: 'ready', providerId: 'provider-a', generation: 1 })

    // Consumer-first: bind (missing), subscribe, then register.
    const keySecond = defineUiComponent<unknown>(CARD, 1)
    const svc2 = createUiComponentsService(selection)
    const ui2 = svc2.uiComponents.forScope(new OwnedResources())
    const bindSecond = ui2.bind(keySecond, { required: true })
    const notify = vi.fn()
    bindSecond.subscribe(notify)
    expect(bindSecond.getSnapshot()).toEqual(missingProviderUnavailable('provider-a'))
    ui2.register(impl(keySecond, 'provider-a'))
    expect(notify).toHaveBeenCalledTimes(1)
    expect(bindSecond.getSnapshot()).toEqual(snapFirst)

    svc1.dispose()
    svc2.dispose()
  })

  it('U01 with no selection the component stays missing even though the only provider is registered', () => {
    const key = defineUiComponent<unknown>(CARD, 1)
    const svc = createUiComponentsService([])
    const ui = svc.uiComponents.forScope(new OwnedResources())
    ui.register(impl(key, 'provider-a'))
    const binding = ui.bind(key, { required: true })
    const snapshot = binding.getSnapshot()
    expect(snapshot).toEqual({ status: 'missing', reason: 'unselected' })
    expect(snapshot).not.toHaveProperty('selectedProviderId')
    expect(svc.inspectRequirements()).toEqual([{ componentId: CARD, major: 1, reason: 'unselected' }])
    svc.dispose()
  })
})

describe('U02 product selection', () => {
  it('U02 with two providers registered only the selected one reports ready, and tampering the input array cannot move the frozen selection', () => {
    const input = selectionOf([CARD, 1, 'provider-a'])
    const key = defineUiComponent<unknown>(CARD, 1)
    const svc = createUiComponentsService(input)
    const ui = svc.uiComponents.forScope(new OwnedResources())
    ui.register(impl(key, 'provider-b'))
    ui.register(impl(key, 'provider-a'))
    const binding = ui.bind(key, { required: true })
    expect(binding.getSnapshot()).toEqual({ status: 'ready', providerId: 'provider-a', generation: 2 })

    // v1 exposes no live re-selection API...
    expect(Object.keys(svc.uiComponents)).toEqual(['forScope'])
    // ...and mutating the caller's original array/entries changes nothing.
    input[0].providerId = 'provider-b'
    input.push({ componentId: CARD, major: 1, providerId: 'provider-b' })
    input.splice(0, 0, { componentId: CARD, major: 1, providerId: 'provider-b' })
    const after = ui.bind(key, { required: true })
    expect(after.getSnapshot()).toEqual({ status: 'ready', providerId: 'provider-a', generation: 2 })
    expect(svc.inspectRequirements()).toEqual([])
    svc.dispose()
  })

  it('U02 a fresh assembly selecting provider-b shows provider-b to unchanged consumer code', () => {
    // The same consumer routine runs in both assemblies; only the product selection differs.
    const run = (svc: UiComponentsService, key: UiComponentKey<unknown>): UiAvailability => {
      const ui = svc.uiComponents.forScope(new OwnedResources())
      ui.register(impl(key, 'provider-a'))
      ui.register(impl(key, 'provider-b'))
      return ui.bind(key, { required: true }).getSnapshot()
    }
    const keyA = defineUiComponent<unknown>(CARD, 1)
    const snapA = run(createUiComponentsService(selectionOf([CARD, 1, 'provider-a'])), keyA)
    const keyB = defineUiComponent<unknown>(CARD, 1)
    const snapB = run(createUiComponentsService(selectionOf([CARD, 1, 'provider-b'])), keyB)
    expect(expectReady(snapA).providerId).toBe('provider-a')
    expect(expectReady(snapB).providerId).toBe('provider-b')
  })

  it('U02 a duplicate (componentId, major) in the selection is rejected at construction with UI_SELECTION_DUPLICATE', () => {
    expectUiError(
      () => createUiComponentsService(selectionOf([CARD, 1, 'provider-a'], [CARD, 1, 'provider-b'])),
      'UI_SELECTION_DUPLICATE',
    )
    // Different majors are not duplicates.
    expect(() => createUiComponentsService(selectionOf([CARD, 1, 'provider-a'], [CARD, 2, 'provider-b']))).not.toThrow()
  })
})

describe('U03 atomic batch', () => {
  it('U03 a batch colliding on key+providerId publishes nothing — not even its first item — and the previous registration stays intact', () => {
    const svc = createUiComponentsService(selectionOf([CARD, 1, 'provider-a'], [PANEL, 1, 'provider-x']))
    const keyCard = defineUiComponent<unknown>(CARD, 1)
    const keyPanel = defineUiComponent<unknown>(PANEL, 1)
    const scope = new OwnedResources()
    const ui = svc.uiComponents.forScope(scope)
    const handleA = ui.register(impl(keyCard, 'provider-a'))
    const cardBinding = ui.bind(keyCard, { required: true })
    const panelBinding = ui.bind(keyPanel, { required: true })
    const cardBefore = cardBinding.getSnapshot()

    expectUiError(() => ui.registerBatch([
      registration(keyPanel, 'provider-x', Stub), // would be visible if the batch partially published
      registration(keyCard, 'provider-a', Stub), // collides with the existing registration
    ]), 'UI_PROVIDER_DUPLICATE')

    // Nothing of the new batch is published...
    expect(panelBinding.getSnapshot()).toEqual(missingProviderUnavailable('provider-x'))
    // ...and the existing registration is untouched (same committed snapshot object).
    expect(cardBinding.getSnapshot()).toBe(cardBefore)
    handleA.dispose()
    expect(cardBinding.getSnapshot()).toEqual(missingProviderUnavailable('provider-a'))
    svc.dispose()
  })

  it('U03 a duplicate key+providerId inside the new batch alone rejects the whole batch', () => {
    const keyPanel = defineUiComponent<unknown>(PANEL, 1)
    const svc = createUiComponentsService(selectionOf([PANEL, 1, 'provider-x']))
    const scope = new OwnedResources()
    const ui = svc.uiComponents.forScope(scope)
    expectUiError(() => ui.registerBatch([
      registration(keyPanel, 'provider-x', Stub),
      registration(keyPanel, 'provider-x', Stub),
    ]), 'UI_PROVIDER_DUPLICATE')
    const binding = ui.bind(keyPanel, { required: false })
    expect(binding.getSnapshot()).toEqual(missingProviderUnavailable('provider-x'))
    // Rejected batch left no trace: the same content retries cleanly.
    ui.registerBatch([registration(keyPanel, 'provider-x', Stub)])
    expect(expectReady(binding.getSnapshot()).providerId).toBe('provider-x')
    svc.dispose()
  })
})

describe('U04 key instance identity', () => {
  it('U04 a second key object for the same (id, major) is rejected with UI_KEY_IDENTITY_CONFLICT and other majors simply do not match', () => {
    const keyV1a = defineUiComponent<unknown>(CARD, 1)
    const keyV1b = defineUiComponent<unknown>(CARD, 1)
    const keyV2 = defineUiComponent<unknown>(CARD, 2)
    const svc = createUiComponentsService(selectionOf([CARD, 1, 'provider-a']))
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const handleV1 = ui.register(impl(keyV1a, 'provider-a'))

    expectUiError(() => ui.register(impl(keyV1b, 'provider-b')), 'UI_KEY_IDENTITY_CONFLICT')
    expectUiError(() => ui.bind(keyV1b, { required: false }), 'UI_KEY_IDENTITY_CONFLICT')
    expectUiError(() => ui.registerBatch([
      registration(keyV2, 'provider-b', Stub),
      registration(keyV1b, 'provider-c', Stub),
    ]), 'UI_KEY_IDENTITY_CONFLICT')

    // A different major is neither merged nor auto-converted: with only the v2
    // instance installed, the major-1 consumer sees provider-unavailable with
    // the installed majors, never the v2 component.
    handleV1.dispose()
    ui.register(impl(keyV2, 'provider-a'))
    const binding = ui.bind(keyV1a, { required: true })
    expect(binding.getSnapshot()).toEqual({
      ...missingProviderUnavailable('provider-a'), seenMajors: [2],
    })
    expect(svc.inspectRequirements()).toEqual([{
      componentId: CARD, major: 1, selectedProviderId: 'provider-a',
      reason: 'provider-unavailable', seenMajors: [2],
    }])
    svc.dispose()
  })
})

describe('U05 generations', () => {
  it('U05 dispose then re-register the same provider id yields a new generation; double-disposing the handle never hurts the live instance', () => {
    const key = defineUiComponent<unknown>(CARD, 1)
    const svc = createUiComponentsService(selectionOf([CARD, 1, 'provider-a']))
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const binding = ui.bind(key, { required: true })

    const first = ui.register(impl(key, 'provider-a'))
    const generation1 = expectReady(binding.getSnapshot()).generation
    first.dispose()
    first.dispose() // idempotent
    expect(binding.getSnapshot()).toEqual(missingProviderUnavailable('provider-a'))

    const second = ui.register(impl(key, 'provider-a'))
    const snapshot2 = binding.getSnapshot()
    const generation2 = expectReady(snapshot2).generation
    expect(generation2).toBeGreaterThan(generation1)

    first.dispose() // old handle can only ever revoke its own contribution
    expect(binding.getSnapshot()).toBe(snapshot2)
    second.dispose()
    expect(binding.getSnapshot().status).toBe('missing')
    svc.dispose()
  })

  it('U05 re-activation after a scope teardown gets a new generation the old handle cannot evict', () => {
    const key = defineUiComponent<unknown>(CARD, 1)
    const svc = createUiComponentsService(selectionOf([CARD, 1, 'provider-a']))
    const consumerUi = svc.uiComponents.forScope(new OwnedResources())
    const binding = consumerUi.bind(key, { required: true })

    const providerScope1 = new OwnedResources()
    const staleHandle = svc.uiComponents.forScope(providerScope1).register(impl(key, 'provider-a'))
    const generation1 = expectReady(binding.getSnapshot()).generation
    providerScope1.dispose() // provider unmount revokes the registration
    expect(binding.getSnapshot()).toEqual(missingProviderUnavailable('provider-a'))

    const providerScope2 = new OwnedResources()
    svc.uiComponents.forScope(providerScope2).register(impl(key, 'provider-a'))
    const snapshot2 = binding.getSnapshot()
    expect(expectReady(snapshot2).generation).toBeGreaterThan(generation1)
    staleHandle.dispose()
    expect(binding.getSnapshot()).toBe(snapshot2)
    svc.dispose()
  })
})

describe('U06 scope ownership', () => {
  it('U06 closing the scope of an activation that threw reclaims every UI registration and required diagnostics report them', () => {
    const keyCard = defineUiComponent<unknown>(CARD, 1)
    const keyPanel = defineUiComponent<unknown>(PANEL, 1)
    const keyNote = defineUiComponent<unknown>(NOTE, 1)
    const svc = createUiComponentsService(selectionOf(
      [CARD, 1, 'provider-a'], [PANEL, 1, 'provider-a'], [NOTE, 1, 'provider-a'],
    ))
    const providerScope = new OwnedResources()
    const ui = svc.uiComponents.forScope(providerScope)
    const consumerUi = svc.uiComponents.forScope(new OwnedResources())
    const card = consumerUi.bind(keyCard, { required: true })
    const panel = consumerUi.bind(keyPanel, { required: true })
    const note = consumerUi.bind(keyNote, { required: false })

    try {
      ui.register(impl(keyCard, 'provider-a'))
      ui.register(impl(keyPanel, 'provider-a'))
      ui.register(impl(keyNote, 'provider-a'))
      throw new Error('activation failed midway')
    } catch {
      // The runtime reports the activation error and reclaims the plugin scope.
    }
    expect(card.getSnapshot().status).toBe('ready') // live until the scope closes
    providerScope.dispose()

    expect(card.getSnapshot()).toEqual(missingProviderUnavailable('provider-a'))
    expect(panel.getSnapshot().status).toBe('missing')
    expect(note.getSnapshot().status).toBe('missing')
    // Only required bindings are reported; the optional one is not a missing requirement.
    expect(svc.inspectRequirements().map(d => d.componentId).sort()).toEqual([CARD, PANEL])
    expect(providerScope.isDisposed).toBe(true)
    expect(() => providerScope.dispose()).not.toThrow() // idempotent teardown
    svc.dispose()
  })

  it('U06 disposing a consumer binding never unmounts the provider registration', () => {
    const key = defineUiComponent<unknown>(CARD, 1)
    const svc = createUiComponentsService(selectionOf([CARD, 1, 'provider-a']))
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const handle = ui.register(impl(key, 'provider-a'))
    const first = ui.bind(key, { required: true })
    const second = ui.bind(key, { required: true })
    const shared = second.getSnapshot()

    first.dispose()
    expect(first.getSnapshot()).toEqual({ status: 'disposed' })
    expect(second.getSnapshot()).toBe(shared) // provider untouched by the consumer's release
    expect(expectReady(second.getSnapshot()).generation).toBe(1)
    // ...and the provider can still be revoked through its own handle.
    handle.dispose()
    expect(second.getSnapshot()).toEqual(missingProviderUnavailable('provider-a'))
    svc.dispose()
  })

  it('U06 a closed scope rejects register, registerBatch and bind synchronously with UI_SCOPE_CLOSED', () => {
    const key = defineUiComponent<unknown>(CARD, 1)
    const svc = createUiComponentsService(selectionOf([CARD, 1, 'provider-a']))
    const closed = new OwnedResources()
    const ui = svc.uiComponents.forScope(closed)
    closed.dispose()

    expectUiError(() => ui.register(impl(key, 'provider-a')), 'UI_SCOPE_CLOSED')
    expectUiError(() => ui.registerBatch([registration(key, 'provider-a', Stub)]), 'UI_SCOPE_CLOSED')
    expectUiError(() => ui.bind(key, { required: true }), 'UI_SCOPE_CLOSED')
    // A fresh UiScope over the same closed scope is rejected too (identity, not handle).
    expectUiError(() => svc.uiComponents.forScope(closed).bind(key, { required: false }), 'UI_SCOPE_CLOSED')
    // Nothing leaked in: an open consumer scope still honestly sees the absence.
    const openUi = svc.uiComponents.forScope(new OwnedResources())
    expect(openUi.bind(key, { required: true }).getSnapshot()).toEqual(missingProviderUnavailable('provider-a'))
    svc.dispose()
  })
})

describe('U07 host isolation', () => {
  it('U07 two services are independent hosts: per-instance key tables, no shared registrations, teardown does not leak', () => {
    const selection = selectionOf([CARD, 1, 'provider-a'])
    const keyA = defineUiComponent<unknown>(CARD, 1)
    const keyB = defineUiComponent<unknown>(CARD, 1) // same (id, major), different object
    const svc1 = createUiComponentsService(selection)
    const svc2 = createUiComponentsService(selection)
    const ui1 = svc1.uiComponents.forScope(new OwnedResources())
    const ui2 = svc2.uiComponents.forScope(new OwnedResources())

    ui1.register(impl(keyA, 'provider-a'))
    // A global key table would raise UI_KEY_IDENTITY_CONFLICT here; per-host tables do not.
    expect(() => ui2.register(impl(keyB, 'provider-a'))).not.toThrow()
    // The tables really are separate: keyA conflicts only inside host 2 (claimed by keyB)...
    expectUiError(() => ui2.bind(keyA, { required: false }), 'UI_KEY_IDENTITY_CONFLICT')
    // ...and registrations are not shared across hosts (second provider slot per service).
    const bind1 = ui1.bind(keyA, { required: true })
    const bind2 = ui2.bind(keyB, { required: true })
    expect(expectReady(bind1.getSnapshot()).generation).toBe(1)
    expect(expectReady(bind2.getSnapshot()).generation).toBe(1)

    // Unmounting host 1's provider scope leaves host 2 completely working.
    const extraScope1 = new OwnedResources()
    svc1.uiComponents.forScope(extraScope1).register(impl(keyA, 'provider-b'))
    extraScope1.dispose()
    svc1.dispose()
    expect(bind1.getSnapshot()).toEqual({ status: 'disposed' })
    expect(bind2.getSnapshot().status).toBe('ready')
    expect(() => ui2.register(impl(keyB, 'provider-y'))).not.toThrow()
    expect(svc2.inspectRequirements()).toEqual([])
    svc2.dispose()
  })

  it('U07 repeated bind calls in one host produce independent bindings that release separately', () => {
    const key = defineUiComponent<unknown>(CARD, 1)
    const svc = createUiComponentsService(selectionOf([CARD, 1, 'provider-a']))
    const ui = svc.uiComponents.forScope(new OwnedResources())
    ui.register(impl(key, 'provider-a'))
    const b1 = ui.bind(key, { required: true })
    const b2 = ui.bind(key, { required: true })
    const b3 = ui.bind(key, { required: true })
    expect(b3.getSnapshot()).toEqual(b2.getSnapshot())
    const spy1 = vi.fn()
    b1.subscribe(spy1)

    b1.dispose()
    b1.dispose() // idempotent
    expect(b1.getSnapshot()).toEqual({ status: 'disposed' })
    expect(spy1).toHaveBeenCalledTimes(1)
    expect(b2.getSnapshot().status).toBe('ready')
    expect(b3.getSnapshot().status).toBe('ready')
    b2.dispose()
    expect(spy1).toHaveBeenCalledTimes(1) // b2's release does not touch b1's subscribers
    expect(b3.getSnapshot().status).toBe('ready')
    // Disposed bindings leave the required-missing report empty even though nothing is missing.
    b3.dispose()
    expect(svc.inspectRequirements()).toEqual([])
    svc.dispose()
  })
})

describe('U08 snapshot stability and notification', () => {
  it('U08 an unchanged getSnapshot keeps object identity across unrelated commits', () => {
    const keyCard = defineUiComponent<unknown>(CARD, 1)
    const keyPanel = defineUiComponent<unknown>(PANEL, 1)
    const svc = createUiComponentsService(selectionOf([CARD, 1, 'provider-a'], [PANEL, 1, 'provider-b']))
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const binding = ui.bind(keyCard, { required: true })
    const initial = binding.getSnapshot()
    expect(binding.getSnapshot()).toBe(initial)

    // A commit for a different component changes nothing for this binding...
    const panelHandle = ui.register(impl(keyPanel, 'provider-b'))
    expect(binding.getSnapshot()).toBe(initial)
    panelHandle.dispose()
    expect(binding.getSnapshot()).toBe(initial)

    // ...while a real change publishes a new stable object.
    const cardHandle = ui.register(impl(keyCard, 'provider-a'))
    const ready = binding.getSnapshot()
    expect(ready).not.toBe(initial)
    expectReady(ready)
    expect(binding.getSnapshot()).toBe(ready)
    cardHandle.dispose()
    const missing = binding.getSnapshot()
    cardHandle.dispose() // old handle, double dispose: no further churn
    expect(binding.getSnapshot()).toBe(missing)
    svc.dispose()
  })

  it('U08 subscribe and unsubscribe actually control notifications', () => {
    const key = defineUiComponent<unknown>(CARD, 1)
    const svc = createUiComponentsService(selectionOf([CARD, 1, 'provider-a']))
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const binding = ui.bind(key, { required: true })
    const notify = vi.fn()
    const unsubscribe = binding.subscribe(notify)

    const first = ui.register(impl(key, 'provider-a'))
    expect(notify).toHaveBeenCalledTimes(1)
    unsubscribe()
    first.dispose()
    ui.register(impl(key, 'provider-a'))
    expect(notify).toHaveBeenCalledTimes(1) // no notification after unsubscribe
    expectReady(binding.getSnapshot())
    svc.dispose()
  })

  it('U08 a throwing subscriber is reported through onDiagnostics without blocking other subscribers or the commit', () => {
    const failures: UiSubscriberFailure[] = []
    const svc = createUiComponentsService(
      selectionOf([CARD, 1, 'provider-a']),
      { onDiagnostics: failure => failures.push(failure) },
    )
    const key = defineUiComponent<unknown>(CARD, 1)
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const binding = ui.bind(key, { required: true })
    const other = ui.bind(key, { required: false })
    const boom = vi.fn((): void => { throw new Error('subscriber exploded') })
    const good = vi.fn()
    const otherSpy = vi.fn()
    binding.subscribe(boom)
    binding.subscribe(good)
    other.subscribe(otherSpy)

    const handle = ui.register(impl(key, 'provider-a'))

    expect(boom).toHaveBeenCalledTimes(1)
    expect(good).toHaveBeenCalledTimes(1) // the throwing subscriber did not stop its peers
    expect(otherSpy).toHaveBeenCalledTimes(1)
    expectReady(binding.getSnapshot()) // the commit went through
    expect(failures).toHaveLength(1)
    expect(failures[0]).toMatchObject({
      kind: 'ui-subscriber-failure', componentId: CARD, major: 1, message: 'subscriber exploded',
    })
    expect(failures[0]).not.toHaveProperty('props')
    expect(failures[0]).not.toHaveProperty('component')

    // Subsequent commits keep flowing to the same listeners.
    handle.dispose()
    expect(good).toHaveBeenCalledTimes(2)
    expect(otherSpy).toHaveBeenCalledTimes(2)
    expect(binding.getSnapshot().status).toBe('missing')
    svc.dispose()
  })
})
