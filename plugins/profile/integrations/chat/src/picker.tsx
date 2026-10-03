/**
 * The composer's Profile selector (composer.toolbar contribution view).
 * Grouped Radix menu: selecting the current item is a new explicit intent,
 * unlike a native select whose unchanged value emits no change event.
 * Portal placement/focus/keyboard/dismissal reuse the existing UI dependency.
 */
import { useSyncExternalStore, type ReactNode } from 'react'
import { DropdownMenu } from 'radix-ui'
import type { ProfilePickerProps } from './picker-model'
import { pickerOptionGroups, selectedOptionValue } from './picker-model'

const idleSubscribe = () => () => {}
const idleSnapshot = () => 0

export function ProfilePicker(input: ProfilePickerProps): ReactNode {
  useSyncExternalStore(input.subscribe ?? idleSubscribe, input.getSnapshot ?? idleSnapshot, input.getSnapshot ?? idleSnapshot)
  const props = input.getLiveProps?.() ?? input
  const groups = pickerOptionGroups(props.groups)
  const value = selectedOptionValue(props.groups, props.label)
  return (
    <span
      data-profile-picker=""
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, minWidth: 0, maxWidth: '100%', fontSize: 12 }}
    >
      <style>{`[data-profile-picker] select{height:28px!important;max-width:180px;padding:0 20px 0 7px!important;border:0!important;border-radius:7px!important;background-color:transparent!important;color:inherit;font:inherit!important;cursor:pointer}[data-profile-picker] button{height:26px;padding:0 6px;border:0;border-radius:6px;background:transparent;color:#77777e;font:inherit;cursor:pointer}[data-profile-picker] select:hover,[data-profile-picker] button:hover{background-color:#88888812!important}[data-profile-picker] :focus-visible{outline:2px solid #548fe5;outline-offset:2px}[data-profile-picker] [role=status],[data-profile-picker] [role=alert]{max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:#77777e}`}</style>
      <DropdownMenu.Root onOpenChange={(open) => { if (open) props.onOpenSelector?.() }}>
      <DropdownMenu.Trigger
        aria-label="配置预设"
        disabled={props.disabledReason !== undefined}
        title={props.disabledReason}
        data-profile-trigger=""
      >
        {props.label ?? '选择预设'} <span aria-hidden="true">⌄</span>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
      <DropdownMenu.Content data-profile-menu="" side="top" align="end" sideOffset={8} collisionPadding={8}
        style={{ zIndex: 1000, minWidth: 240, maxWidth: 'calc(100vw - 16px)', maxHeight: 'var(--radix-dropdown-menu-content-available-height)', overflowY: 'auto', padding: 6, borderRadius: 12, border: '1px solid #dedee3', background: 'var(--surface, white)', color: 'var(--foreground, #222)', boxShadow: '0 8px 28px #00000018', fontSize: 13 }}>
        {props.label && props.onClearSelection && <DropdownMenu.Item onSelect={props.onClearSelection}>清除预设选择</DropdownMenu.Item>}
        {groups.map((group) => (
          <DropdownMenu.Group key={group.harnessId}>
            <DropdownMenu.Label style={{ padding: '8px 10px 4px', color: '#77777e', fontSize: 11 }}>{group.harnessTitle}</DropdownMenu.Label>
            {group.options.map((option) => (
              <DropdownMenu.Item
                key={option.value}
                disabled={option.archived}
                data-profile-value={option.value}
                data-selected={option.value === value ? '' : undefined}
                onSelect={() => props.onSelect(option.selection)}
              >
                {option.label} {option.value === value && <span aria-hidden="true">✓</span>}
              </DropdownMenu.Item>
            ))}
          </DropdownMenu.Group>
        ))}
      </DropdownMenu.Content>
      </DropdownMenu.Portal>
      </DropdownMenu.Root>
      <style>{`[data-profile-menu] [role=menuitem]{padding:8px 10px;border-radius:7px;outline:0;cursor:pointer}[data-profile-menu] [data-highlighted]{background:#88888816}[data-profile-menu] [data-disabled]{opacity:.45;cursor:default}[data-profile-trigger]{max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}`}</style>
      {props.onRefresh && <button type="button" aria-label="刷新预设" title="刷新预设" data-profile-refresh="" onClick={props.onRefresh}><span aria-hidden="true">↻</span></button>}
      {props.statusMessage && <span role="status" style={{ minWidth: 0 }} title={props.statusMessage}>{props.statusMessage}</span>}
      {/* 021 §6c F1.1: a click registration that failed is a visible fact, so
        * the user knows the pick is NOT yet registered and can retry. */}
      {props.registrationError && (
        <span role="alert" title={`预设登记失败：${props.registrationError}；选择已保留，重新发送时将重试。`} data-profile-registration-error="">
          预设登记失败：{props.registrationError}；选择已保留，重新发送时将重试。
        </span>
      )}
      {props.onOpenManager && (
        <button
          type="button"
          data-profile-manage=""
          onClick={props.onOpenManager}
        >
          管理
        </button>
      )}
      <style>{`[data-profile-picker] select{min-width:0;flex:0 1 auto}[data-profile-picker] [role=status],[data-profile-picker] [role=alert]{min-width:0;flex:0 1 auto}[data-profile-picker] [role=alert]{min-width:64px}[data-profile-picker] button{flex-shrink:0}`}</style>
    </span>
  )
}
