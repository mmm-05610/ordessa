// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/selector.tsx, verbatim)
import { useMemo, useState } from 'react'
import { ELIGIBILITY_GLYPHS, ELIGIBILITY_LABELS, type Eligibility } from '../../contracts/index'
import type { ModelProviderService, ProviderConfigView } from '../../contracts/index'
import type { ComposerLocation } from './stub-chat-contract'

/** Per-session eligibility evidence: the harness adapter's verdict for
 * (config, model) in THIS session. In this baseline the seam behind it is not
 * wired (integration dependency #2), so the adapter is usually absent - the
 * selector then answers "此会话暂不可选模型", never a fabricated ready. */
export interface SessionEligibilitySource {
  eligibility(harnessId: string, providerConfigId: string, modelId: string): Eligibility
  reason?(harnessId: string, providerConfigId: string, modelId: string): string | undefined
}

const ABSENT_SOURCE: SessionEligibilitySource = {
  eligibility: () => 'unknown',
  reason: (_h, _c, _m) => '本基线未接入会话配置能力（ACP seam），无法证明可在本会话下轮应用',
}

/** One queued "next turn" choice, atomic (Provider config + model). */
export interface QueuedChoice {
  harnessId: string
  providerConfigId: string
  modelId: string
}

export interface ModelSelectorProps {
  service: ModelProviderService
  location: ComposerLocation
  eligibilitySource?: SessionEligibilitySource
  queued?: QueuedChoice | null
  onQueue?(choice: QueuedChoice): void
}

/** The composer.footer selector: one compact `Provider › Model` control.
 * The harness is already bound by the session (or the draft target) - there
 * is deliberately no harness dropdown here; new sessions pick their harness
 * at creation, not in the composer. */
export function ModelSelector({ service, location, eligibilitySource,
                                queued, onQueue }: ModelSelectorProps) {
  const source = eligibilitySource ?? ABSENT_SOURCE
  const [open, setOpen] = useState(false)
  const [configs, setConfigs] = useState<ProviderConfigView[]>([])
  const harnessId = location.kind === 'session'
    ? location.session.harnessId
    : (location.target?.harnessId ?? '')

  useMemo(() => { service.list().then(setConfigs).catch(() => setConfigs([])) }, [service])

  const scoped = configs.filter((config) => config.harness === harnessId && config.archivedAt === null)
  const rows = scoped.flatMap((config) =>
    config.models.map((model) => ({
      config, modelId: model.modelId,
      eligibility: source.eligibility(harnessId, config.id, model.modelId),
      reason: source.reason?.(harnessId, config.id, model.modelId),
    })))

  return (
    <div data-testid="model-selector" style={{ position: 'relative' }}>
      <button data-testid="model-selector-trigger" onClick={() => setOpen(!open)}>
        {queued ? `${queued.providerConfigId} › ${queued.modelId}` : '模型'}
        {queued ? '（下轮使用）' : ''}
      </button>
      {open && (
        <div role="listbox" aria-label="Provider › Model" data-testid="model-selector-list">
          {harnessId === '' && <p>新建会话请先选择 Harness。</p>}
          {harnessId !== '' && rows.length === 0 && <p>此 Harness 暂无 Provider 配置。</p>}
          {rows.map((row) => {
            const selectable = row.eligibility === 'ready'
            return (
              <div key={`${row.config.id}/${row.modelId}`} role="option"
                aria-selected={queued?.modelId === row.modelId && queued?.providerConfigId === row.config.id}
                aria-disabled={!selectable}
                data-testid={`model-option-${row.config.id}-${row.modelId}`}
                style={{ opacity: selectable ? 1 : 0.6, cursor: selectable ? 'pointer' : 'not-allowed' }}
                onClick={() => {
                  if (!selectable) return
                  onQueue?.({ harnessId, providerConfigId: row.config.id, modelId: row.modelId })
                  setOpen(false)
                }}>
                <span>{row.config.displayName} › </span>
                <span style={{ fontFamily: 'monospace' }}>{row.modelId}</span>
                <span>
                  {ELIGIBILITY_GLYPHS[row.eligibility]} {ELIGIBILITY_LABELS[row.eligibility]}
                  {row.reason ? `：${row.reason}` : ''}
                </span>
              </div>
            )
          })}
          {harnessId !== '' && rows.every((row) => row.eligibility !== 'ready') && (
            <p data-testid="no-selectable">此会话暂不可选模型（无 ready 证据）。</p>
          )}
        </div>
      )}
    </div>
  )
}
