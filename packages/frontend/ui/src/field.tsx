// C8 foundations — Field composition (plan "最小公开基础件" + the documented
// Field.Control render-prop exception).
// Field only wires ids and presentation state between label/description/error
// and the consumer's own control: one stable id from `useId` (two Field.Root
// instances can never collide), `aria-describedby` listing only the parts that
// are actually rendered, and a children *function* on Field.Control carrying
// `{ id, 'aria-describedby', 'aria-invalid', ... }` to the real control.
// No cloneElement of arbitrary children, no `asChild`, no schema, no
// validation engine, no persistence, no requests (F04).
import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useReducer,
  type HTMLAttributes,
  type ReactNode,
} from 'react'
import { cx } from './layout'

export type FieldPart = 'description' | 'error'

/** The a11y/presentation bundle Field.Control hands to its children function. */
export interface FieldControlState {
  id: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean
  required?: boolean
  disabled?: boolean
  readOnly?: boolean
}

interface FieldContextValue {
  controlId: string
  descriptionId: string
  errorId: string
  /** Ids of the parts currently mounted, in description→error order. */
  describedBy: string | undefined
  invalid?: boolean
  required?: boolean
  disabled?: boolean
  readOnly?: boolean
  registerPart: (part: FieldPart) => void
  unregisterPart: (part: FieldPart) => void
}

const FieldContext = createContext<FieldContextValue | null>(null)

function useFieldContext(component: string): FieldContextValue {
  const value = useContext(FieldContext)
  if (value === null) {
    throw new Error(`${component} must be rendered inside a Field.Root`)
  }
  return value
}

type PresentState = { description: number; error: number }

function presentReducer(state: PresentState, action: { type: 'add' | 'remove'; part: FieldPart }): PresentState {
  const delta = action.type === 'add' ? 1 : -1
  if (action.part === 'description') {
    return { ...state, description: Math.max(0, state.description + delta) }
  }
  return { ...state, error: Math.max(0, state.error + delta) }
}

export interface FieldRootProps extends HTMLAttributes<HTMLDivElement> {
  /** Presentation states only — Field never computes them itself. */
  invalid?: boolean
  required?: boolean
  disabled?: boolean
  readOnly?: boolean
}

export const FieldRoot = forwardRef<HTMLDivElement, FieldRootProps>(function FieldRoot(
  { invalid, required, disabled, readOnly, className, children, ...rest },
  ref,
) {
  const base = useId()
  const [present, apply] = useReducer(presentReducer, { description: 0, error: 0 })
  const registerPart = useCallback((part: FieldPart) => apply({ type: 'add', part }), [])
  const unregisterPart = useCallback((part: FieldPart) => apply({ type: 'remove', part }), [])
  const descriptionId = `${base}-description`
  const errorId = `${base}-error`
  const describedBy =
    [present.description > 0 ? descriptionId : undefined, present.error > 0 ? errorId : undefined]
      .filter((part): part is string => part !== undefined)
      .join(' ') || undefined
  const value = useMemo<FieldContextValue>(
    () => ({
      controlId: `${base}-control`,
      descriptionId,
      errorId,
      describedBy,
      invalid,
      required,
      disabled,
      readOnly,
      registerPart,
      unregisterPart,
    }),
    [base, descriptionId, errorId, describedBy, invalid, required, disabled, readOnly, registerPart, unregisterPart],
  )
  return (
    <div ref={ref} className={cx('ods-ui-field', className)} {...rest}>
      <FieldContext.Provider value={value}>{children}</FieldContext.Provider>
    </div>
  )
})

export const FieldLabel = forwardRef<HTMLLabelElement, HTMLAttributes<HTMLLabelElement>>(function FieldLabel(
  { className, children, ...rest },
  ref,
) {
  const { controlId } = useFieldContext('Field.Label')
  return (
    <label ref={ref} className={cx('ods-ui-field-label', className)} {...rest} htmlFor={controlId}>
      {children}
    </label>
  )
})

/** The documented exception: a children function, not cloned arbitrary nodes. */
export interface FieldControlProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  children: (state: FieldControlState) => ReactNode
}

export const FieldControl = forwardRef<HTMLDivElement, FieldControlProps>(function FieldControl(
  { className, children, ...rest },
  ref,
) {
  const ctx = useFieldContext('Field.Control')
  const state: FieldControlState = {
    id: ctx.controlId,
    'aria-describedby': ctx.describedBy,
    'aria-invalid': ctx.invalid ? true : undefined,
    required: ctx.required ? true : undefined,
    disabled: ctx.disabled ? true : undefined,
    readOnly: ctx.readOnly ? true : undefined,
  }
  return (
    <div ref={ref} className={cx('ods-ui-field-control', className)} {...rest}>
      {children(state)}
    </div>
  )
})

function useFieldPartRegistration(part: FieldPart, register: (p: FieldPart) => void, unregister: (p: FieldPart) => void): void {
  useEffect(() => {
    register(part)
    return () => unregister(part)
  }, [part, register, unregister])
}

export const FieldDescription = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function FieldDescription(
  { className, children, ...rest },
  ref,
) {
  const ctx = useFieldContext('Field.Description')
  useFieldPartRegistration('description', ctx.registerPart, ctx.unregisterPart)
  return (
    <div ref={ref} className={cx('ods-ui-field-description', className)} {...rest} id={ctx.descriptionId}>
      {children}
    </div>
  )
})

/**
 * Plain text node — it never focuses itself when it appears (F04 "Error 不凭
 * 存在就每次抢焦点") and it carries no live-region semantics of its own.
 */
export const FieldError = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function FieldError(
  { className, children, ...rest },
  ref,
) {
  const ctx = useFieldContext('Field.Error')
  useFieldPartRegistration('error', ctx.registerPart, ctx.unregisterPart)
  return (
    <div ref={ref} className={cx('ods-ui-field-error', className)} {...rest} id={ctx.errorId}>
      {children}
    </div>
  )
})

export const Field = {
  Root: FieldRoot,
  Label: FieldLabel,
  Control: FieldControl,
  Description: FieldDescription,
  Error: FieldError,
} as const
