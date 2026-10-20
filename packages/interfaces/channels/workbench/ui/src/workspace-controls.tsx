// UI01 workspace controls. These are content-only React primitives: consumers
// own values, callbacks and state; Workbench owns overlay/submenu placement.
import {
  cloneElement,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type ComponentProps,
  type HTMLAttributes,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
} from 'react'
import { Button, Input } from './controls'
import { cx } from './layout'

export interface MenuContentProps extends Omit<HTMLAttributes<HTMLDivElement>, 'role'> {
  label: string
  onEscape?: () => void
}

/** Menu content only; the caller mounts it in Workbench's existing overlay stack. */
export function MenuContent({ label, onEscape, className, onKeyDown, ...rest }: MenuContentProps) {
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown?.(event)
    if (event.defaultPrevented) return
    if (event.key === 'Escape') {
      event.preventDefault()
      onEscape?.()
      return
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    const items = [...event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]')]
      .filter(item => item.closest('[role="menu"]') === event.currentTarget && item.getAttribute('aria-disabled') !== 'true')
    if (!items.length) return
    event.preventDefault()
    const current = items.findIndex(item => item === event.target || item.contains(event.target as Node))
    const next = event.key === 'Home' ? 0
      : event.key === 'End' ? items.length - 1
        : current < 0 ? (event.key === 'ArrowUp' ? items.length - 1 : 0)
          : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
    items[next]?.focus()
  }
  return <div {...rest} role="menu" aria-label={label} className={cx('ods-ui-menu-content', className)} onKeyDown={handleKeyDown} />
}

export interface MenuGroupProps extends Omit<HTMLAttributes<HTMLDivElement>, 'role'> { label: string }
export function MenuGroup({ label, className, ...rest }: MenuGroupProps) {
  return <div {...rest} role="group" aria-label={label} className={cx('ods-ui-menu-group', className)} />
}

export interface MenuItemProps extends Omit<ComponentProps<typeof Button>, 'variant'> {
  label: string
  disabled?: boolean
  danger?: boolean
  shortcut?: string
}
export function MenuItem({ label, disabled = false, danger = false, shortcut, className, children, ...rest }: MenuItemProps) {
  return <Button {...rest} role="menuitem" aria-label={label} aria-disabled={disabled || undefined} disabled={disabled}
    variant={danger ? 'danger' : 'ghost'} className={cx('ods-ui-menu-item', className)}>
    <span className="ods-ui-menu-item-label">{children ?? label}</span>
    {shortcut && <span className="ods-ui-menu-item-shortcut" aria-hidden="true">{shortcut}</span>}
  </Button>
}

export interface SubmenuItemProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onChange'> {
  label: string
  open: boolean
  disabled?: boolean
  onOpenChange(open: boolean): void
  children: ReactNode
}
/** Controlled submenu content; it does not create a portal or overlay layer. */
export function SubmenuItem({ label, open, disabled = false, onOpenChange, children, className, ...rest }: SubmenuItemProps) {
  return <div {...rest} role="none" className={cx('ods-ui-submenu-item', className)}>
    <Button role="menuitem" aria-label={label} aria-haspopup="menu" aria-expanded={open} aria-disabled={disabled || undefined}
      disabled={disabled} variant="ghost" className="ods-ui-submenu-trigger"
      onClick={() => onOpenChange(!open)}
      onKeyDown={event => { if (event.key === 'ArrowRight' && !open && !disabled) { event.preventDefault(); onOpenChange(true) } }}>
      <span>{label}</span><span aria-hidden="true">›</span>
    </Button>
    {open && <div className="ods-ui-submenu-content">{children}</div>}
  </div>
}

export interface TooltipProps { content: string; children: ReactElement<{ 'aria-describedby'?: string }> }
/** Inline tooltip description; positioning and visibility are CSS-only, never portalled. */
export function Tooltip({ content, children }: TooltipProps) {
  const id = useId()
  const existing = children.props['aria-describedby']
  const describedBy = [existing, id].filter(Boolean).join(' ')
  const trigger = cloneElement(children, { 'aria-describedby': describedBy } as Partial<typeof children.props>)
  return <span className="ods-ui-tooltip">
    {trigger}<span id={id} role="tooltip" className="ods-ui-tooltip-content">{content}</span>
  </span>
}

export interface ListGroupProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  label: string
  description?: string
}
export function ListGroup({ label, description, className, children, ...rest }: ListGroupProps) {
  return <section {...rest} role="listbox" aria-label={label} className={cx('ods-ui-list-group', className)}>
    <h3 className="ods-ui-list-group-title">{label}</h3>
    {description && <p className="ods-ui-list-group-description">{description}</p>}
    <div className="ods-ui-list-group-items">{children}</div>
  </section>
}

export interface ListRowProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onSelect'> {
  label: string
  selected?: boolean
  disabled?: boolean
  onSelect?(): void
  actions?: ReactNode
}
export function ListRow({ label, selected = false, disabled = false, onSelect, actions, className, children, ...rest }: ListRowProps) {
  return <div {...rest} role="group" aria-label={label} className={cx('ods-ui-list-row', className)}>
    <button type="button" role="option" aria-label={label} aria-selected={selected} disabled={disabled}
      className="ods-ui-list-row-select" onClick={onSelect}>
      <span className="ods-ui-list-row-content">{children ?? label}</span>
    </button>
    {actions != null && <div className="ods-ui-list-row-actions" role="group" aria-label={`${label} 操作`}>{actions}</div>}
  </div>
}

export interface SearchInputProps extends Omit<ComponentProps<typeof Input>, 'type'> {
  'aria-label': string
}
export function SearchInput({ className, ...rest }: SearchInputProps) {
  return <Input {...rest} type="search" className={cx('ods-ui-search-input', className)} />
}

export interface TabDefinition { id: string; label: string; disabled?: boolean; panelId?: string }
export interface TabsProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onChange' | 'value'> {
  label: string
  tabs: readonly TabDefinition[]
  value: string
  onValueChange(value: string): void
  orientation?: 'horizontal' | 'vertical'
}
export function Tabs({ label, tabs, value, onValueChange, orientation = 'horizontal', className, onKeyDown, ...rest }: TabsProps) {
  const refs = useRef(new Map<string, HTMLButtonElement>())
  const tabsId = useSafeId(label)
  const onTabsKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown?.(event)
    if (event.defaultPrevented || !['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    const enabled = tabs.filter(tab => !tab.disabled)
    if (!enabled.length) return
    const current = Math.max(0, enabled.findIndex(tab => tab.id === value))
    const forward = orientation === 'horizontal' ? event.key === 'ArrowRight' : event.key === 'ArrowDown'
    const backward = orientation === 'horizontal' ? event.key === 'ArrowLeft' : event.key === 'ArrowUp'
    if (event.key !== 'Home' && event.key !== 'End' && !forward && !backward) return
    event.preventDefault()
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? enabled.length - 1
      : (current + (forward ? 1 : -1) + enabled.length) % enabled.length
    const next = enabled[nextIndex]!
    onValueChange(next.id)
    refs.current.get(next.id)?.focus()
  }
  return <div {...rest} role="tablist" aria-label={label} aria-orientation={orientation}
    className={cx('ods-ui-tabs', `ods-ui-tabs--${orientation}`, className)} onKeyDown={onTabsKeyDown}>
    {tabs.map(tab => <button key={tab.id} ref={node => { if (node) refs.current.set(tab.id, node); else refs.current.delete(tab.id) }}
      type="button" role="tab" id={`${tabsId}-${tab.id}`} aria-selected={value === tab.id}
      aria-controls={tab.panelId}
      tabIndex={value === tab.id ? 0 : -1} disabled={tab.disabled}
      className="ods-ui-tab" onClick={() => !tab.disabled && onValueChange(tab.id)}>{tab.label}</button>)}
  </div>
}

function useSafeId(label: string): string {
  const id = useId()
  return `ods-ui-tabs-${id.replace(/[^a-zA-Z0-9_-]/g, '')}-${label.replace(/[^a-zA-Z0-9_-]/g, '-')}`
}

export interface SwitchProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onChange' | 'aria-label'> {
  label: string
  checked: boolean
  onCheckedChange(checked: boolean): void
  disabled?: boolean
}
export function Switch({ label, checked, onCheckedChange, disabled = false, className, ...rest }: SwitchProps) {
  return <button {...rest} type="button" role="switch" aria-label={label} aria-checked={checked} disabled={disabled}
    className={cx('ods-ui-switch', checked && 'ods-ui-switch--checked', className)} onClick={() => onCheckedChange(!checked)}>
    <span className="ods-ui-switch-track" aria-hidden="true"><span className="ods-ui-switch-thumb" /></span>
    <span className="ods-ui-switch-label">{label}</span>
  </button>
}

export interface SettingsRowProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  label: string
  description?: string
  children: ReactNode
}
export function SettingsRow({ label, description, className, children, ...rest }: SettingsRowProps) {
  const id = useId()
  return <div {...rest} className={cx('ods-ui-settings-row', className)}>
    <div className="ods-ui-settings-row-copy"><div className="ods-ui-settings-row-label" id={`${id}-label`}>{label}</div>
      {description && <div className="ods-ui-settings-row-description" id={`${id}-description`}>{description}</div>}</div>
    <div className="ods-ui-settings-row-control" aria-labelledby={`${id}-label`} aria-describedby={description ? `${id}-description` : undefined}>{children}</div>
  </div>
}

export interface SettingsGroupProps extends Omit<HTMLAttributes<HTMLFieldSetElement>, 'title'> {
  label: string
  description?: string
}
export function SettingsGroup({ label, description, className, children, ...rest }: SettingsGroupProps) {
  return <fieldset {...rest} className={cx('ods-ui-settings-group', className)}>
    <legend className="ods-ui-settings-group-title">{label}</legend>
    {description && <p className="ods-ui-settings-group-description">{description}</p>}
    {children}
  </fieldset>
}

export interface DisclosureProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title' | 'onChange'> {
  label: string
  open: boolean
  onOpenChange(open: boolean): void
  children: ReactNode
}
export function Disclosure({ label, open, onOpenChange, className, children, ...rest }: DisclosureProps) {
  const id = useId()
  return <div {...rest} className={cx('ods-ui-disclosure', className)}>
    <button type="button" className="ods-ui-disclosure-trigger" aria-expanded={open} aria-controls={`${id}-content`}
      onClick={() => onOpenChange(!open)}><span>{label}</span><span aria-hidden="true">{open ? '−' : '+'}</span></button>
    <div id={`${id}-content`} className="ods-ui-disclosure-content" hidden={!open}>{children}</div>
  </div>
}

export interface LoadingStateProps extends Omit<HTMLAttributes<HTMLDivElement>, 'role'> { label: string }
export function LoadingState({ label, className, ...rest }: LoadingStateProps) {
  return <div {...rest} role="status" aria-live="polite" className={cx('ods-ui-loading-state', className)}>
    <span className="ods-ui-loading-indicator" aria-hidden="true" />{label}
  </div>
}
