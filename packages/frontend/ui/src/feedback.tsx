// C8 foundations — generic feedback display (plan "最小公开基础件").
// Badge/Notice/EmptyState render the five generic tones; a tone is a colour
// decision, never an interpretation of an execution result, and Notice's live
// region is strictly opt-in (F05/F06): nothing here announces by itself.
import { forwardRef, type HTMLAttributes, type ReactNode } from 'react'
import { cx } from './layout'

export type UiTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: UiTone
}

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { tone = 'neutral', className, children, ...rest },
  ref,
) {
  return (
    <span ref={ref} className={cx('ods-ui-badge', `ods-ui-badge--${tone}`, className)} {...rest}>
      {children}
    </span>
  )
})

export interface NoticeProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  tone?: UiTone
  /** Opt-in only: with `live` the notice becomes an aria-live polite region.
   * Without it there is no live-region attribute at all. */
  live?: boolean
  title?: ReactNode
}

export const Notice = forwardRef<HTMLDivElement, NoticeProps>(function Notice(
  { tone = 'neutral', live = false, title, className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cx('ods-ui-notice', `ods-ui-notice--${tone}`, className)}
      {...rest}
      aria-live={live ? 'polite' : undefined}
    >
      {title !== undefined && <div className="ods-ui-notice-title">{title}</div>}
      {children !== undefined && <div className="ods-ui-notice-body">{children}</div>}
    </div>
  )
})

export interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: ReactNode
  description?: ReactNode
}

export const EmptyState = forwardRef<HTMLDivElement, EmptyStateProps>(function EmptyState(
  { title, description, className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-empty-state', className)} {...rest}>
      {title !== undefined && <div className="ods-ui-empty-state-title">{title}</div>}
      {description !== undefined && <div className="ods-ui-empty-state-description">{description}</div>}
      {children}
    </div>
  )
})
