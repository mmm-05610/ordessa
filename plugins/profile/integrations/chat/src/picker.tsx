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
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
    >
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
      {props.onRefresh && <button type="button" data-profile-refresh="" onClick={props.onRefresh}>刷新预设</button>}
      {props.statusMessage && <span role="status">{props.statusMessage}</span>}
      {props.onOpenManager && (
        <button
          type="button"
          data-profile-manage=""
          onClick={props.onOpenManager}
        >
          管理
        </button>
      )}
    </span>
  )
}
