/**
 * The composer's Profile selector (composer.toolbar contribution view).
 * Grouped native select through the platform Select control: Harness groups
 * as option groups, profiles as options — the interaction shape reuses the
 * model-picker structure without pretending to be a two-level tree widget
 * (reuse-map: "现有 Select 是基础 select").
 */
import type { ReactNode } from 'react'
import { Select } from '@ordessa/ui'
import type { ProfilePickerProps } from './picker-model'
import { pickerOptionGroups, selectedOptionValue } from './picker-model'

export function ProfilePicker(props: ProfilePickerProps): ReactNode {
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
        onChange={(event) => {
          const raw = event.target.value
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
        <option value="">{props.label ?? '选择预设'}</option>
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
