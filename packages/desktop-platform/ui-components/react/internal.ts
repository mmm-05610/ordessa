// Package-internal helpers for the React layer.
//
// The implementation lookup goes through the symbol-keyed capability the core
// attaches to each binding it creates (src/internal.ts): the Outlet never reads
// the core's private field layout, and a binding object that did not come from
// this package's core simply has no capability, so it resolves to `undefined`
// which the Outlet presents as absence — never as a component. Nothing is
// registered module-globally: the capability travels with the binding.
import type { ComponentType } from 'react'
import type { UiAvailability, UiBinding } from '../api/ui-components'
import { internalsOf } from '../src/internal'

/** The `required` flag fixed on the binding at bind time (contract §5). Takes `unknown`: it only reads a capability. */
export function bindingRequires(binding: unknown): boolean {
  return internalsOf(binding)?.required === true
}

/**
 * Resolve the component registered for the binding's currently-ready provider,
 * or `undefined` when the generation no longer matches (revoked, replaced) or the
 * binding was not created by this package's core.
 */
export function resolveUiComponent<P>(
  binding: UiBinding<P>,
  availability: Extract<UiAvailability, { status: 'ready' }>,
): ComponentType<P> | undefined {
  const component = internalsOf(binding)?.resolve(availability)
  return component as ComponentType<P> | undefined
}

/** One sanitized platform diagnostic; never carries props, values or causes beyond a short summary. */
export interface UiPlatformDiagnostic {
  readonly kind: 'ui-render-failed' | 'ui-action-failed'
  readonly code: 'UI_RENDER_FAILED' | 'UI_ACTION_FAILED'
  readonly componentId: string
  readonly major: number
  readonly providerId?: string
  readonly generation?: number
  /** Sanitized summary of the caught cause (message only, length-bounded). */
  readonly message: string
}

/** Same policy as the core's subscriber-failure reporting: message text, bounded length. */
export function sanitizeCause(cause: unknown): string {
  if (cause instanceof Error) return cause.message.length > 200 ? `${cause.message.slice(0, 200)}...` : cause.message
  const text = String(cause)
  return text.length > 200 ? `${text.slice(0, 200)}...` : text
}

/**
 * Report one diagnostic through the host diagnostic path: an optional
 * structured sink plus console.error. The payload is the sanitized
 * {@link UiPlatformDiagnostic} only — never props, inputs or full causes.
 */
export function reportUiDiagnostic(
  diagnostic: UiPlatformDiagnostic,
  sink?: (diagnostic: UiPlatformDiagnostic) => void,
): void {
  try {
    console.error('[ordessa.ui-components]', diagnostic)
  } catch { /* a broken console must not break the UI path */ }
  if (sink === undefined) return
  try {
    sink(diagnostic)
  } catch { /* a throwing sink must not break the UI path either */ }
}
