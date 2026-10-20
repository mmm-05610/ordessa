// @ordessa/ui-components/react — T033 React consumption layer on top of the
// T032 runtime core (contract §4 rendering/actions, §5 errors/accessibility;
// acceptance U09–U13). Domain-neutral: no business components, no Agent/Chat
// vocabulary. The implementation component is reached only through the
// package-internal accessor in ./internal.ts; nothing here exports a raw
// component getter to consumers.
//
// Diagnostics channel choice for this layer: render failures (UI_RENDER_FAILED)
// and swallowed action failures (UI_ACTION_FAILED) are reported through
// console.error with a sanitized payload, and action/guard call sites accept an
// optional structured sink so a host can route them into its own diagnostics.
// Payloads carry component id, major, provider id, generation and a bounded
// summary — never props, values or untrimmed causes (contract §5).
import {
  Component,
  createElement,
  useSyncExternalStore,
  type ComponentType,
  type ErrorInfo,
  type ReactElement,
  type ReactNode,
} from 'react'
import type {
  UiAction,
  UiActionResult,
  UiAvailability,
  UiBinding,
} from '../api/ui-components'
import {
  bindingRequires,
  reportUiDiagnostic,
  resolveUiComponent,
  sanitizeCause,
  type UiPlatformDiagnostic,
} from './internal'

export type { UiPlatformDiagnostic } from './internal'

/** Props of {@link ComponentOutlet} (contract §4). */
export interface ComponentOutletProps<P> {
  readonly binding: UiBinding<P>
  readonly value: P
  /** Explicit absence content; overrides the per-requiredness default. */
  readonly missing?: ReactNode
}

/** Options for the guarded helpers; a host-side sink for sanitized diagnostics. */
export interface UiGuardOptions {
  readonly onDiagnostics?: (diagnostic: UiPlatformDiagnostic) => void
}

/** Generic, display-safe wording for a swallowed action failure (§5). */
export const UI_ACTION_FAILURE_MESSAGE = '界面操作未能完成，请稍后重试。'

/** Subscribe to a binding's availability snapshot outside an Outlet (§4). */
export function useUiBinding<P>(binding: UiBinding<P>): UiAvailability {
  return useSyncExternalStore(binding.subscribe, binding.getSnapshot, binding.getSnapshot)
}

interface OutletBoundaryProps {
  readonly componentId: string
  readonly major: number
  readonly providerId: string
  readonly generation: number
  readonly children?: ReactNode
}

interface OutletBoundaryState {
  readonly failed: boolean
}

/**
 * Per-outlet error boundary (§5): only this position shows the error; a new
 * generation remounts (and thereby clears) it through the Outlet's `key`;
 * within the same generation only the explicit retry affordance resets it —
 * there is no automatic re-render loop.
 */
class OutletErrorBoundary extends Component<OutletBoundaryProps, OutletBoundaryState> {
  override state: OutletBoundaryState = { failed: false }

  static getDerivedStateFromError(): OutletBoundaryState {
    return { failed: true }
  }

  override componentDidCatch(error: unknown, _info: ErrorInfo): void {
    // The error object is a foreign implementation's; report only its bounded
    // summary, never the props that produced it.
    reportUiDiagnostic({
      kind: 'ui-render-failed',
      code: 'UI_RENDER_FAILED',
      componentId: this.props.componentId,
      major: this.props.major,
      providerId: this.props.providerId,
      generation: this.props.generation,
      message: sanitizeCause(error),
    })
  }

  private readonly retry = (): void => {
    this.setState({ failed: false })
  }

  override render(): ReactNode {
    if (!this.state.failed) return this.props.children
    return createElement(
      'div',
      { role: 'alert', 'data-ui-outlet-error': 'true' },
      createElement('span', null, '此位置的界面组件渲染失败。'),
      createElement(
        'button',
        {
          type: 'button',
          'data-ui-outlet-retry': 'true',
          'aria-label': '重试加载此位置的界面组件',
          onClick: this.retry,
        },
        '重试',
      ),
    )
  }
}

/** Stable wrapper so an explicit `missing` node keeps one element position. */
function AbsentContent(props: { children: ReactNode }): ReactElement | null {
  return props.children as ReactElement | null
}

/** Absence rendering per §5: explicit override, else required prompt, else nothing. */
function renderAbsent<P>(binding: UiBinding<P>, missing: ReactNode | undefined): ReactElement | null {
  if (missing !== undefined) return createElement(AbsentContent, null, missing)
  if (!bindingRequires(binding)) return null
  return createElement(
    'div',
    { role: 'alert', 'data-ui-outlet-missing': 'required' },
    '此位置必需的界面组件当前不可用。',
  )
}

/** Renders the resolved implementation; kept as a helper so `P` can be object-constrained for createElement. */
function renderImplementation(component: ComponentType<object>, value: object): ReactElement {
  return createElement(component, value)
}

/**
 * Render the currently selected implementation for a binding (§4/§5).
 * Absence: `missing` override, else required shows a generic prompt and
 * optional renders nothing. The implementation subtree is keyed by provider
 * generation, so a new generation remounts it while unchanged generations keep
 * identity. An implementation that exists but throws shows an error at its
 * position — never the absence prompt.
 */
export function ComponentOutlet<P>(props: ComponentOutletProps<P>): ReactElement | null {
  const { binding, value, missing } = props
  const availability = useUiBinding(binding)

  if (availability.status !== 'ready') return renderAbsent(binding, missing)
  const component = resolveUiComponent(binding, availability)
  if (component === undefined) {
    // Ready snapshot without a resolvable record: treat as absence (the
    // binding no longer denotes a component in this host).
    return renderAbsent(binding, missing)
  }
  return createElement(
    OutletErrorBoundary,
    {
      key: `generation:${availability.generation}`,
      componentId: binding.key.id,
      major: binding.key.major,
      providerId: availability.providerId,
      generation: availability.generation,
    },
    renderImplementation(component as unknown as ComponentType<object>, value as unknown as object),
  )
}

/** The binding still denotes the exact generation observed when the guard was created. */
function sameGeneration(observed: UiAvailability, current: UiAvailability): boolean {
  return observed.status === 'ready'
    && current.status === 'ready'
    && observed.providerId === current.providerId
    && observed.generation === current.generation
}

/**
 * Guarded asynchronous action (§4). The guard fixes the binding AND the
 * generation observed at creation; at call time it re-checks both and returns
 * `unavailable` with zero business calls if either lapsed — including a
 * re-activation of the same provider id under a new generation. A guarded
 * action created while `missing` is permanently unavailable. Synchronous
 * throws and rejections are caught, reported with a sanitized diagnostic, and
 * turned into a generic `refused`; `accepted` is passed through untouched and
 * never reinterpreted as completion. After the start-time check passes, later
 * revocation/unmount does not cancel accepted work and this layer writes no
 * state anywhere.
 */
export function guardUiAction<P, I>(
  binding: UiBinding<P>,
  action: UiAction<I>,
  options?: UiGuardOptions,
): UiAction<I> {
  const observed = binding.getSnapshot()
  return async (input: I): Promise<UiActionResult> => {
    if (observed.status !== 'ready' || !sameGeneration(observed, binding.getSnapshot())) {
      return { status: 'unavailable' }
    }
    try {
      return await action(input)
    } catch (cause) {
      reportUiDiagnostic({
        kind: 'ui-action-failed',
        code: 'UI_ACTION_FAILED',
        componentId: binding.key.id,
        major: binding.key.major,
        providerId: observed.providerId,
        generation: observed.generation,
        message: sanitizeCause(cause),
      }, options?.onDiagnostics)
      return { status: 'refused', message: UI_ACTION_FAILURE_MESSAGE }
    }
  }
}

/**
 * Synchronous guard variant for pure callbacks (§4): when the binding or the
 * fixed generation is no longer current the original callback is not invoked
 * at all. Callback errors are not swallowed — this is a revocation check, not
 * an error boundary.
 */
export function guardUiCallback<P, A extends readonly unknown[]>(
  binding: UiBinding<P>,
  callback: (...args: A) => void,
): (...args: A) => void {
  const observed = binding.getSnapshot()
  return (...args: A): void => {
    if (observed.status !== 'ready' || !sameGeneration(observed, binding.getSnapshot())) return
    callback(...args)
  }
}
