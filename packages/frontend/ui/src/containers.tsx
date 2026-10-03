// C8 foundations — presentational containers (plan "最小公开基础件").
// Card and Panel compose strictly through children and named parts: they take
// no componentId/providerId/registry props, no business modes and no feature
// booleans (F03). A Card is a plain information box: it never collapses,
// drags, closes windows or hijacks scrolling; Panel is a content-area skeleton
// whose header/footer keep their size while the body owns scrolling.
import { forwardRef, type HTMLAttributes } from 'react'
import { cx, type UiSpacing } from './layout'

export type CardVariant = 'outlined' | 'subtle' | 'plain'

export interface CardRootProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant
  /** Padding token applied to every Card section through `--ods-ui-card-pad`. */
  padding?: UiSpacing
}

export type CardSectionProps = HTMLAttributes<HTMLDivElement>

export const CardRoot = forwardRef<HTMLDivElement, CardRootProps>(function CardRoot(
  { variant = 'outlined', padding = 'md', className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cx('ods-ui-card', `ods-ui-card--${variant}`, `ods-ui-card--pad-${padding}`, className)}
      {...rest}
    >
      {children}
    </div>
  )
})

export const CardHeader = forwardRef<HTMLDivElement, CardSectionProps>(function CardHeader(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-card-header', className)} {...rest}>
      {children}
    </div>
  )
})

export const CardTitle = forwardRef<HTMLDivElement, CardSectionProps>(function CardTitle(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-card-title', className)} {...rest}>
      {children}
    </div>
  )
})

export const CardDescription = forwardRef<HTMLDivElement, CardSectionProps>(function CardDescription(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-card-description', className)} {...rest}>
      {children}
    </div>
  )
})

export const CardActions = forwardRef<HTMLDivElement, CardSectionProps>(function CardActions(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-card-actions', className)} {...rest}>
      {children}
    </div>
  )
})

export const CardBody = forwardRef<HTMLDivElement, CardSectionProps>(function CardBody(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-card-body', className)} {...rest}>
      {children}
    </div>
  )
})

export const CardFooter = forwardRef<HTMLDivElement, CardSectionProps>(function CardFooter(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-card-footer', className)} {...rest}>
      {children}
    </div>
  )
})

/** Namespaced view of the same implementations — one code path, two spellings. */
export const Card = {
  Root: CardRoot,
  Header: CardHeader,
  Title: CardTitle,
  Description: CardDescription,
  Actions: CardActions,
  Body: CardBody,
  Footer: CardFooter,
} as const

export type PanelRootProps = HTMLAttributes<HTMLDivElement>

export const PanelRoot = forwardRef<HTMLDivElement, PanelRootProps>(function PanelRoot(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-panel', className)} {...rest}>
      {children}
    </div>
  )
})

export const PanelHeader = forwardRef<HTMLDivElement, CardSectionProps>(function PanelHeader(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-panel-header', className)} {...rest}>
      {children}
    </div>
  )
})

export const PanelTitle = forwardRef<HTMLDivElement, CardSectionProps>(function PanelTitle(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-panel-title', className)} {...rest}>
      {children}
    </div>
  )
})

export const PanelActions = forwardRef<HTMLDivElement, CardSectionProps>(function PanelActions(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-panel-actions', className)} {...rest}>
      {children}
    </div>
  )
})

export const PanelBody = forwardRef<HTMLDivElement, CardSectionProps>(function PanelBody(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-panel-body', className)} {...rest}>
      {children}
    </div>
  )
})

export const PanelFooter = forwardRef<HTMLDivElement, CardSectionProps>(function PanelFooter(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cx('ods-ui-panel-footer', className)} {...rest}>
      {children}
    </div>
  )
})

export const Panel = {
  Root: PanelRoot,
  Header: PanelHeader,
  Title: PanelTitle,
  Actions: PanelActions,
  Body: PanelBody,
  Footer: PanelFooter,
} as const
