// @ordessa/ui-components/api — generic UI implementation provision/consumption, v1.
// Contract: specs/010-platform-core/amendments/ui-components/contracts/component-platform.md
// (C7 §1–§6), authorised by contracts/ui-components-platform.md.
//
// Side-effect free by design, like the C6 Connections api: types, the single
// UiComponentsToken construction site, and the only key/registration factories.
// Nothing here imports the implementation, React DOM, Workbench or any domain —
// a product that only installs this API can import it without an implementation
// present (UI-01/UI-12, U14). Component ids and provider ids are opaque strings
// owned by the domain/product configuration; the platform never branches on them.
import { Token, type IDisposable, type ResourceScope } from '@ordessa/extension-api'
import type { ComponentType } from 'react'

declare const keyBrand: unique symbol
/**
 * Type-safe identity of one component interface: `(id, major)` plus an
 * invariant-in-`P` brand, so a component with the wrong props cannot pass as an
 * implementation of this key (contract §2). The only construction site is
 * {@link defineUiComponent}; a hand-written object literal cannot satisfy the
 * branded member, and the platform detects two distinct objects carrying the same
 * `(id, major)` inside one host as `UI_KEY_IDENTITY_CONFLICT` instead of merging
 * them by string.
 */
export interface UiComponentKey<P> {
  readonly [keyBrand]: (props: P) => P
  readonly id: string
  readonly major: number
}

/** The single construction site of {@link UiComponentKey} (UI-02). */
export function defineUiComponent<P>(id: string, major: number): UiComponentKey<P> {
  if (typeof id !== 'string' || id.length === 0) throw new RangeError('UI component key requires a non-empty id')
  if (!Number.isInteger(major) || major < 1) throw new RangeError('UI component key major must be a positive integer')
  return Object.freeze({ id, major }) as unknown as UiComponentKey<P>
}

/** One implementation contribution: a key, the provider that owns it, and its component. */
export interface UiImplementation<P> {
  readonly key: UiComponentKey<P>
  /** The implementation contribution id, unique per key within one host. */
  readonly providerId: string
  readonly component: ComponentType<P>
}

declare const registrationBrand: unique symbol
/**
 * Opaque, erased registration record for {@link UiScope.registerBatch}. Built only
 * by {@link registration}; a caller cannot assemble one by hand, and the batch API
 * never exposes `UiImplementation<any>[]` (which would defeat props checking).
 */
export interface UiRegistration {
  readonly [registrationBrand]: never
}

/** The single factory of {@link UiRegistration}; keeps `P` inferred from the key. */
export function registration<P>(
  key: UiComponentKey<P>, providerId: string, component: ComponentType<P>,
): UiRegistration {
  if (typeof providerId !== 'string' || providerId.length === 0) throw new RangeError('UI registration requires a providerId')
  if (!component) throw new RangeError('UI registration requires a component')
  return Object.freeze({ key, providerId, component }) as unknown as UiRegistration
}

/** Availability snapshot of one consumed component (UI-06). `ready`/`missing` are states, not errors. */
export type UiAvailability =
  | { readonly status: 'ready'; readonly providerId: string; readonly generation: number }
  | { readonly status: 'missing'; readonly reason: 'unselected' | 'provider-unavailable';
      readonly selectedProviderId?: string; readonly seenMajors?: readonly number[] }
  | { readonly status: 'disposed' }

/**
 * Consumer-side, revocable reference to one component (UI-05/UI-06). It is owned
 * by the consumer's scope: disposing it releases only this binding, and it can
 * neither enumerate nor change other providers. The component implementation is
 * deliberately not exposed — a consumer must not be able to render past a
 * revocation by grabbing it directly.
 */
export interface UiBinding<P> extends IDisposable {
  readonly key: UiComponentKey<P>
  getSnapshot(): UiAvailability
  subscribe(listener: () => void): () => void
}

/** One host scope's registration/binding surface (UI-04/UI-05). */
export interface UiScope {
  /** Register a single implementation; released with `scope`. */
  register<P>(implementation: UiImplementation<P>): IDisposable
  /** Validate-then-publish batch: on any failure nothing of the new batch is published. */
  registerBatch(items: readonly UiRegistration[]): IDisposable
  /** Bind a consumed component; `required` is fixed on the binding (UI-09). */
  bind<P>(key: UiComponentKey<P>, options: { required: boolean }): UiBinding<P>
}

/** The service carried by {@link UiComponentsToken}. */
export interface UiComponents {
  /** Ownership is taken from the host-issued scope object, never from a caller-supplied owner string. */
  forScope(scope: ResourceScope): UiScope
}

export const UiComponentsToken = new Token<UiComponents>('ordessa.ui-components.v1')

/**
 * Product selection table, frozen and copied at assembly time; v1 exposes no way
 * to change it while running (UI-03, contract §3). Duplicate
 * `(componentId, major)` entries are rejected by the assembly factory.
 */
export type UiSelection = readonly {
  readonly componentId: string
  readonly major: number
  readonly providerId: string
}[]

/** Product-side diagnosis of one missing required binding; never carries props. */
export interface UiRequirementDiagnostic {
  readonly componentId: string
  readonly major: number
  readonly selectedProviderId?: string
  readonly reason: 'unselected' | 'provider-unavailable'
  readonly seenMajors?: readonly number[]
}

/** Generic error codes of this platform, and the rejection type that carries them (§5). */
export type { UiErrorCode } from './errors'
export { UiComponentsError } from './errors'

/** Result of a guarded UI action. `accepted` means the business took the operation, not that it finished. */
export type UiActionResult =
  | { readonly status: 'accepted' }
  | { readonly status: 'refused'; readonly message: string }
  | { readonly status: 'unavailable' }

export type UiAction<I> = (input: I) => Promise<UiActionResult>
