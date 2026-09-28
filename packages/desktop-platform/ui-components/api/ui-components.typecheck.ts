// Type-level counterexamples for the C7 public API (task T031, contract §1/§2/§3,
// UI-02/UI-05, plan "类型反例是交付项"). Checked with the desktop sources by
// apps/desktop/tsconfig.json; never bundled and never runtime-loaded. A relaxed
// type silently fails this file, because every expectation directive below must
// actually fire.
import type { UiAvailability, UiBinding, UiComponents, UiImplementation, UiRegistration, UiSelection, UiScope } from './ui-components'
import { defineUiComponent, registration, UiComponentsToken } from './ui-components'

interface CardProps { title: string }
interface WiderProps { title: string; extra: number }

declare const cardKey: ReturnType<typeof defineUiComponent<CardProps>>
declare const scope: UiScope
declare const binding: UiBinding<CardProps>
declare const implementation: UiImplementation<CardProps>

// --- positives: the shapes the contract promises are usable as written ---------
const key = defineUiComponent<CardProps>('example.card', 1)
void (key satisfies { id: string; major: number })
const good: UiImplementation<CardProps> = { key: cardKey, providerId: 'provider-a', component: () => null }
void good
const batched: UiRegistration = registration(cardKey, 'provider-a', props => props.title.toUpperCase())
void batched
const bound = scope.bind(cardKey, { required: true })
void (bound satisfies UiBinding<CardProps>)
const selection: UiSelection = [{ componentId: 'example.card', major: 1, providerId: 'provider-a' }]
void selection
declare const service: UiComponents
void (service.forScope satisfies (scope: import('@ordessa/extension-api').ResourceScope) => UiScope)
void (UiComponentsToken.name === 'ordessa.ui-components.v1')
const readySnapshot: UiAvailability = { status: 'ready', providerId: 'provider-a', generation: 3 }
void readySnapshot

// --- negatives ---------------------------------------------------------------
// @ts-expect-error Props are invariant in a key: a component that needs an extra field is not an implementation of this key.
const wrongProps: UiImplementation<CardProps> = { key: cardKey, providerId: 'provider-a', component: (props: WiderProps) => props.extra }
void wrongProps

// @ts-expect-error The same mismatch on the single-registration path.
scope.register({ key: cardKey, providerId: 'provider-a', component: (props: WiderProps) => props.extra })

// @ts-expect-error A key cannot be assembled by hand — the invariant brand is not implementable.
const forgedKey: ReturnType<typeof defineUiComponent<CardProps>> = { id: 'example.card', major: 1 }
void forgedKey

// @ts-expect-error A registration record cannot be written out by hand either.
const forgedRegistration: UiRegistration = { key: cardKey, providerId: 'provider-a', component: () => null }
void forgedRegistration

// @ts-expect-error A batch takes opaque registrations; accepting UiImplementation<any>[] would erase props checking.
scope.registerBatch([implementation])

// @ts-expect-error required/optional is fixed on the binding, so it must be stated at bind time.
scope.bind(cardKey)

// @ts-expect-error The consumer-facing binding exposes snapshot and subscription only — never the component, which would bypass revocation.
void binding.component

// @ts-expect-error The binding carries no provider handle of its own — who serves it is read from the availability snapshot (UI-05).
void binding.providerId

// @ts-expect-error The scope surface is register/bind; there is no global removal of foreign contributions.
void scope.unregisterAll()

// @ts-expect-error Published availability is a read-only snapshot.
readySnapshot.status = 'disposed'

// @ts-expect-error v1 offers no in-place selection change: mutating the frozen selection is not an API.
selection.push({ componentId: 'example.card', major: 2, providerId: 'provider-b' })
