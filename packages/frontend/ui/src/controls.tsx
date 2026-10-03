// C8 foundations — native controls (plan "最小公开基础件").
// Every control is the plain HTML element with native keyboard, focus and form
// semantics; values are controlled by the consumer. `busy` is a repeat-fire
// guard plus `aria-busy` — not an async state machine and never an auto-retry.
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'
import { cx } from './layout'

export type ButtonVariant = 'default' | 'primary' | 'secondary' | 'ghost' | 'danger'
export type ControlSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ControlSize
  /** While busy the button reports `aria-busy="true"` and click handlers are
   * not fired; nothing else changes and nothing retries on its own. */
  busy?: boolean
}

/** Native `<button>`; `type` defaults to `'button'` (never submits by accident)
 * and stays overridable by the consumer. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'default', size = 'md', busy = false, disabled = false, type, onClick, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      {...rest}
      type={type ?? 'button'}
      disabled={disabled}
      aria-busy={busy ? true : undefined}
      data-busy={busy ? 'true' : undefined}
      onClick={disabled || busy ? undefined : onClick}
      className={cx('ods-ui-button', `ods-ui-button--${variant}`, `ods-ui-button--${size}`, className)}
    >
      {children}
    </button>
  )
})

/**
 * Icon-only Button. The accessible name is a required *type-level* prop: an
 * IconButton without `aria-label` does not compile (see tests/ui.typecheck.ts),
 * not merely a runtime warning.
 */
export interface IconButtonProps extends Omit<ButtonProps, 'aria-label'> {
  'aria-label': string
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { className, ...rest },
  ref,
) {
  return <Button ref={ref} className={cx('ods-ui-icon-button', className)} {...rest} />
})

export type InputProps = InputHTMLAttributes<HTMLInputElement>

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={cx('ods-ui-input', className)} {...rest} />
})

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={cx('ods-ui-textarea', className)} {...rest} />
})

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement>

/** Native `<select>` filled through native `<option>` children; the native
 * `multiple`/`size` capabilities stay usable exactly as the browser defines
 * them. No entity search, no tag chips. */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, children, ...rest },
  ref,
) {
  return (
    <select ref={ref} className={cx('ods-ui-select', className)} {...rest}>
      {children}
    </select>
  )
})

export type CheckboxProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} type="checkbox" className={cx('ods-ui-checkbox', className)} {...rest} />
})
