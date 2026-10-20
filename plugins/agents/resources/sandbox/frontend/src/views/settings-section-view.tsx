// Presentational half of the Sandbox Settings region. It renders one thing:
// whatever `resolveSandboxRegionState` took from `sandbox.describe@1`. No
// option, platform or coverage string is written here, and no container or
// popover is invented — the Workbench owns the Settings page, and the C8
// foundations own the controls (UX §文案和可访问性).
import { useSyncExternalStore } from 'react'
import { Badge, Button, Notice, Stack, type UiTone } from '@ordessa/ui'
import {
  sandboxCopy,
  sandboxCoverageText,
  sandboxRowDisablement,
  type SandboxSettingsRegion,
  type SandboxRegionState,
} from '../settings-region'
import type { SandboxOption } from '../contract'

const STATUS_LABEL: Record<SandboxOption['status'], string> = {
  supported: '支持',
  unsupported: '不支持',
  unknown: '未证实',
}
const STATUS_TONE: Record<SandboxOption['status'], UiTone> = {
  supported: 'success',
  unsupported: 'warning',
  unknown: 'neutral',
}

export interface SandboxSettingsSectionViewProps { region: SandboxSettingsRegion }

export function SandboxSettingsSectionView({ region }: SandboxSettingsSectionViewProps) {
  const snapshot = useSyncExternalStore(region.subscribe, region.getSnapshot, region.getSnapshot)
  const { state } = snapshot
  const headingId = `${region.sectionId}-summary`

  return (
    <Stack spacing="sm" className="sandbox-settings-region" data-sandbox-region={state.kind}>
      {state.kind === 'provider-error' && (
        <Notice tone="danger" role="alert" live>{sandboxCopy.providerError(state.code)}</Notice>
      )}
      {state.kind === 'unknown-pin' && (
        <Notice tone="warning" role="alert" live>{sandboxCopy.unknownPin}</Notice>
      )}
      {state.kind !== 'ready' && (
        <p id={headingId}>{state.kind === 'provider-error' ? '原生隔离状态待后端恢复。' : '原生隔离当前没有可显示的选项。'}</p>
      )}
      {state.kind === 'ready' && (
        <>
          <p id={headingId}>{sandboxCopy.regionDescription}</p>
          <div
            role="radiogroup"
            aria-labelledby={headingId}
            className="sandbox-settings-options"
          >
            {state.result.options.map(option => (
              <OptionRow key={option.optionId} region={region} state={state} option={option}
                selected={snapshot.draft?.optionId === option.optionId} generation={snapshot.generation} />
            ))}
          </div>
        </>
      )}
      {snapshot.lastOutcome !== undefined && (
        <p role="status" aria-live="polite" data-sandbox-outcome={snapshot.lastOutcome.status}>
          {snapshot.lastOutcome.status === 'applied'
            ? sandboxCopy.applied(snapshot.lastOutcome.optionId)
            : sandboxCopy.refused(snapshot.lastOutcome)}
        </p>
      )}
    </Stack>
  )
}

function OptionRow(props: {
  region: SandboxSettingsRegion
  state: Extract<SandboxRegionState, { kind: 'ready' }>
  option: SandboxOption
  selected: boolean
  generation: number
}) {
  const { region, state, option, selected, generation } = props
  const { disabled, reason } = sandboxRowDisablement(state, option)
  const reasonId = `${region.sectionId}-${option.optionId}-reason`
  const coverageId = `${region.sectionId}-${option.optionId}-coverage`
  return (
    <Button
      className="sandbox-settings-option"
      data-option-id={option.optionId}
      role="radio"
      aria-checked={selected}
      // Read-only rows stay focusable on purpose: the reason below is only
      // announced to a user who can reach the row.
      aria-disabled={disabled || undefined}
      aria-describedby={disabled ? `${coverageId} ${reasonId}` : coverageId}
      onClick={() => { void region.select(option.optionId, generation) }}
    >
      <span className="sandbox-settings-option-name">{option.optionId}</span>
      <Badge tone={STATUS_TONE[option.status]}>{STATUS_LABEL[option.status]}</Badge>
      <span id={coverageId} className="sandbox-settings-option-coverage">{sandboxCoverageText(option)}</span>
      <span className="sandbox-settings-option-source">来源：{option.source}</span>
      {disabled && <span id={reasonId} className="sandbox-settings-option-reason">{reason}</span>}
    </Button>
  )
}
