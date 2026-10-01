import { useCallback, useEffect, useState } from 'react'
import { ELIGIBILITY_GLYPHS, ELIGIBILITY_LABELS, type Eligibility } from '../../contracts/index'
import type { ModelProviderService, ProviderConfigView } from '../../contracts/index'

/** This domain's own view of where the composer is: a bound session, or a draft
 * that has no native session yet. It is deliberately NOT the Chat contract's
 * `ChatLocation` — `chat-api-entry.tsx` adapts that onto this shape, so the
 * selector and the queue client never import a contract, a stub or a host
 * internals. */
export type ComposerLocation =
  | { kind: 'session'; session: { serverInstanceId: string; harnessId: string; acpSessionId: string } }
  | { kind: 'draft'; target?: { serverInstanceId: string; harnessId: string; projectId: string } }

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

/** D04: a load failure is its own visible state with an explicit retry. It is
 * never rendered as an empty-but-plausible list — "this Harness has no
 * Provider config" and "the catalogue could not be read" are different facts
 * and the user must be able to retry the second one. */
type Catalog =
  | { readonly state: 'loading' }
  | { readonly state: 'ready'; readonly configs: readonly ProviderConfigView[] }
  | { readonly state: 'error'; readonly message: string }

const describe = (cause: unknown): string =>
  cause instanceof Error && cause.message ? cause.message : String(cause)

/** The composer model selector: one compact `Provider › Model` control.
 * The harness is already bound by the session (or the draft target) - there
 * is deliberately no harness dropdown here; new sessions pick their harness
 * at creation, not in the composer. */
export function ModelSelector({ service, location, eligibilitySource,
                                queued, onQueue }: ModelSelectorProps) {
  const source = eligibilitySource ?? ABSENT_SOURCE
  const [open, setOpen] = useState(false)
  const [catalog, setCatalog] = useState<Catalog>({ state: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let live = true
    setCatalog({ state: 'loading' })
    service.list().then(
      configs => { if (live) setCatalog({ state: 'ready', configs }) },
      cause => { if (live) setCatalog({ state: 'error', message: describe(cause) }) })
    return () => { live = false }
  }, [service, attempt])
  const retry = useCallback(() => setAttempt(value => value + 1), [])

  const harnessId = location.kind === 'session'
    ? location.session.harnessId
    : (location.target?.harnessId ?? '')
  const configs = catalog.state === 'ready' ? catalog.configs : []
  const scoped = configs.filter((config) => config.harness === harnessId && config.archivedAt === null)
  const rows = scoped.flatMap((config) =>
    config.models.map((model) => {
      // The backend's per-model availability is authoritative and can never be
      // overridden by a session eligibility verdict.
      const available = model.availability === 'available'
      return {
        config, modelId: model.modelId,
        available,
        unavailableReason: model.unavailableReason ?? undefined,
        eligibility: source.eligibility(harnessId, config.id, model.modelId),
        reason: source.reason?.(harnessId, config.id, model.modelId),
      }
    }))
  const selectable = (row: (typeof rows)[number]) => row.available && row.eligibility === 'ready'

  return (
    <div data-testid="model-selector" style={{ position: 'relative' }}>
      <button data-testid="model-selector-trigger" onClick={() => setOpen(!open)}>
        {queued ? `${queued.providerConfigId} › ${queued.modelId}` : '模型'}
        {queued ? '（下轮使用）' : ''}
      </button>
      {open && (
        <div role="listbox" aria-label="Provider › Model" data-testid="model-selector-list">
          {catalog.state === 'loading' && <p data-testid="model-load-pending">正在加载模型列表…</p>}
          {catalog.state === 'error' && (
            <div role="alert" data-testid="model-load-error">
              <p>模型列表加载失败：{catalog.message}</p>
              <button type="button" data-testid="model-load-retry" onClick={retry}>重试</button>
            </div>
          )}
          {catalog.state === 'ready' && harnessId === '' && <p>新建会话请先选择 Harness。</p>}
          {catalog.state === 'ready' && harnessId !== '' && rows.length === 0 && <p>此 Harness 暂无 Provider 配置。</p>}
          {rows.map((row) => {
            const isSelectable = selectable(row)
            return (
              <div key={`${row.config.id}/${row.modelId}`} role="option"
                aria-selected={queued?.modelId === row.modelId && queued?.providerConfigId === row.config.id}
                aria-disabled={!isSelectable}
                data-testid={`model-option-${row.config.id}-${row.modelId}`}
                style={{ opacity: isSelectable ? 1 : 0.6, cursor: isSelectable ? 'pointer' : 'not-allowed' }}
                onClick={() => {
                  if (!isSelectable) return
                  onQueue?.({ harnessId, providerConfigId: row.config.id, modelId: row.modelId })
                  setOpen(false)
                }}>
                <span>{row.config.displayName} › </span>
                <span style={{ fontFamily: 'monospace' }}>{row.modelId}</span>
                <span>
                  {!row.available
                    ? `${ELIGIBILITY_GLYPHS.unsupported} ${row.unavailableReason ?? ELIGIBILITY_LABELS.unsupported}`
                    : `${ELIGIBILITY_GLYPHS[row.eligibility]} ${ELIGIBILITY_LABELS[row.eligibility]}`}
                  {row.reason ? `：${row.reason}` : ''}
                </span>
              </div>
            )
          })}
          {catalog.state === 'ready' && harnessId !== '' && rows.length > 0
            && rows.every((row) => !selectable(row)) && (
            <p data-testid="no-selectable">此会话暂不可选模型（无 ready 证据）。</p>
          )}
        </div>
      )}
    </div>
  )
}
