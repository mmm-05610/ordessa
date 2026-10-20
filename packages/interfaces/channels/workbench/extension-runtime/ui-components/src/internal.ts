// Package-internal channel between the runtime core and the React layer.
//
// `UiBinding` deliberately exposes no component (contract §2: the implementation
// stays in private state so a consumer cannot render past a revocation). The
// Outlet therefore resolves through a symbol-keyed capability the core attaches
// to each binding it creates — not by reading the core's private field layout.
// This module is not a package export entry and `react/index.ts` does not
// re-export it, so consumers cannot reach it through `@ordessa/ui-components/*`.
// There is no registry here: the capability travels with the binding object
// itself, so per-host isolation (U07) and revocation (U05/U09) hold by construction.
import type { ComponentType } from 'react'
import type { UiAvailability } from '../api/ui-components'

/** A binding's component resolver, valid only for the generation it reports. */
export interface UiBindingInternals {
  readonly required: boolean
  resolve(availability: Extract<UiAvailability, { status: 'ready' }>): ComponentType<unknown> | undefined
}

// The symbol is registered by key on purpose: the provider extension, the
// consumer extension and the service extension are built as separate real
// bundles, each carrying its own copy of this module, and `Symbol(...)` would
// give every copy a different identity — the consumer's outlet could then never
// resolve a binding the service created. This is an identity marker, not a
// registry: no data is stored under it globally, the capability still travels
// with the binding object, so per-host isolation (U07) and revocation (U05/U09)
// hold exactly as before.
export const uiBindingInternals: unique symbol = Symbol.for('ordessa.ui-components.binding-internals')

/** `undefined` for anything that is not a binding created by this package's core. */
export function internalsOf(binding: unknown): UiBindingInternals | undefined {
  if (typeof binding !== 'object' || binding === null) return undefined
  const value = (binding as Record<symbol, unknown>)[uiBindingInternals as unknown as symbol]
  return typeof value === 'object' && value !== null ? value as UiBindingInternals : undefined
}
