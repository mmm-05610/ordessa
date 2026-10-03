// C8 foundations — layout primitives (plan "最小公开基础件").
// Pure presentational React components over native div semantics: no state
// services, no registry, no side effects on import. Every element carries an
// `.ods-ui-*` class so styles.css can scope every rule to this package.
import { forwardRef, type HTMLAttributes } from 'react'

/** Shared spacing token scale consumed via `--ods-ui-space-*` theme hooks. */
export type UiSpacing = 'none' | 'xs' | 'sm' | 'md' | 'lg'
export type UiAlign = 'start' | 'center' | 'end' | 'stretch'
export type UiJustify = 'start' | 'center' | 'end' | 'between'

/** Class joiner used by every foundation in this package (internal helper). */
export function cx(...parts: Array<string | false | undefined>): string {
  return parts.filter((part): part is string => typeof part === 'string' && part.length > 0).join(' ')
}

export interface StackProps extends HTMLAttributes<HTMLDivElement> {
  spacing?: UiSpacing
  align?: UiAlign
  justify?: UiJustify
}

/** Vertical flex stack. Layout only — children own all content semantics. */
export const Stack = forwardRef<HTMLDivElement, StackProps>(function Stack(
  { spacing, align, justify, className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cx(
        'ods-ui-stack',
        spacing !== undefined && `ods-ui-stack--gap-${spacing}`,
        align !== undefined && `ods-ui-stack--align-${align}`,
        justify !== undefined && `ods-ui-stack--justify-${justify}`,
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  )
})

export interface InlineProps extends HTMLAttributes<HTMLDivElement> {
  spacing?: UiSpacing
  align?: UiAlign
  justify?: UiJustify
  wrap?: boolean
}

/** Horizontal flex row; `wrap` opts into line-wrapping at narrow widths. */
export const Inline = forwardRef<HTMLDivElement, InlineProps>(function Inline(
  { spacing, align, justify, wrap, className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cx(
        'ods-ui-inline',
        spacing !== undefined && `ods-ui-inline--gap-${spacing}`,
        align !== undefined && `ods-ui-inline--align-${align}`,
        justify !== undefined && `ods-ui-inline--justify-${justify}`,
        wrap && 'ods-ui-inline--wrap',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  )
})

export interface ToolbarProps extends Omit<HTMLAttributes<HTMLDivElement>, 'role'> {
  orientation?: 'horizontal' | 'vertical'
}

/**
 * A named action group (`role="group"`, accessible name via aria-label /
 * aria-labelledby). v1 keeps the native Tab order — no roving tabindex is
 * claimed or simulated here.
 */
export const Toolbar = forwardRef<HTMLDivElement, ToolbarProps>(function Toolbar(
  { orientation = 'horizontal', className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      {...rest}
      role="group"
      className={cx(
        'ods-ui-toolbar',
        orientation === 'vertical' && 'ods-ui-toolbar--vertical',
        className,
      )}
    >
      {children}
    </div>
  )
})

export interface ScrollAreaProps extends HTMLAttributes<HTMLDivElement> {
  direction?: 'vertical' | 'horizontal' | 'both'
}

/**
 * Native overflow container. It forwards its ref, never auto-follows content,
 * never virtualises and never listens for wheel events.
 */
export const ScrollArea = forwardRef<HTMLDivElement, ScrollAreaProps>(function ScrollArea(
  { direction = 'both', className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cx('ods-ui-scroll-area', `ods-ui-scroll-area--${direction}`, className)}
      {...rest}
    >
      {children}
    </div>
  )
})

export interface SeparatorProps extends Omit<HTMLAttributes<HTMLDivElement>, 'role'> {
  orientation?: 'horizontal' | 'vertical'
  /** When true the separator is exposed via `role="separator"`; by default it
   * is purely decorative (`aria-hidden`) so it never appears in the a11y tree. */
  semantic?: boolean
}

export function Separator({
  orientation = 'horizontal',
  semantic = false,
  className,
  ...rest
}: SeparatorProps) {
  return (
    <div
      className={cx('ods-ui-separator', `ods-ui-separator--${orientation}`, className)}
      role={semantic ? 'separator' : undefined}
      aria-orientation={semantic ? orientation : undefined}
      aria-hidden={semantic ? undefined : true}
      {...rest}
    />
  )
}
