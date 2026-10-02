/**
 * The composer's Profile selector (composer.toolbar contribution view).
 * Grouped native select through the platform Select control: Harness groups
 * as option groups, profiles as options — the interaction shape reuses the
 * model-picker structure without pretending to be a two-level tree widget
 * (reuse-map: "现有 Select 是基础 select").
 */
import { useSyncExternalStore, type ReactNode } from 'react'
import { Select } from '@ordessa/ui'
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
      <Select
        aria-label="配置预设"
        disabled={props.disabledReason !== undefined}
        title={props.disabledReason}
        value={value}
        onPointerDown={props.onOpenSelector}
        onKeyDown={(event) => { if (['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(event.key)) props.onOpenSelector?.() }}
        onChange={(event) => {
          const raw = event.target.value
          if (raw === '') {
            props.onClearSelection?.()
            return
          }
          for (const group of groups) {
            for (const option of group.options) {
              if (option.value === raw) {
                props.onSelect(option.selection)
                return
              }
            }
          }
        }}
      >
        <option value="">{props.label ? `${props.label}（清除选择）` : '选择预设'}</option>
        {groups.map((group) => (
          <optgroup key={group.harnessId} label={group.harnessTitle}>
            {group.options.map((option) => (
              <option
                key={option.value}
                value={option.value}
                disabled={option.archived}
              >
                {option.label}
              </option>
            ))}
          </optgroup>
        ))}
      </Select>
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
