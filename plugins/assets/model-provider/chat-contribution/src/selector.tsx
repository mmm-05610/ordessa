import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ELIGIBILITY_GLYPHS, ELIGIBILITY_LABELS, type Eligibility } from '@extensions/ordessa.model-provider/contract.js'
import type { ModelProviderService, ProviderConfigView } from '@extensions/ordessa.model-provider/contract.js'

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
  reason: (_h, _c, _m) => '尚未取得此会话的模型应用证据，无法证明可在本会话下轮使用',
}

/** One queued "next turn" choice, atomic (Provider config + model). */
export interface QueuedChoice {
  harnessId: string
  providerConfigId: string
  modelId: string
  configVersion?: number
}

export interface ObservedModel {
  modelId: string
  provider: string | null
}

export interface ModelSelectorProps {
  service: ModelProviderService
  location: ComposerLocation
  eligibilitySource?: SessionEligibilitySource
  queued?: QueuedChoice | null
  onQueue?(choice: QueuedChoice): void
  inspectChoice?(choice: QueuedChoice, version: number): Promise<{ eligibility: Eligibility; reason?: string }>
  disabled?: boolean
  lastConfirmed?: QueuedChoice | null
  current?: ObservedModel | null
  onOpen?(): void
  /** Display-only explanation supplied by the native session owner. */
  statusReason?: string
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
                                queued, onQueue, inspectChoice, disabled, lastConfirmed, current, onOpen, statusReason }: ModelSelectorProps) {
  const source = eligibilitySource ?? ABSENT_SOURCE
  const [open, setOpen] = useState(false)
  const [catalog, setCatalog] = useState<Catalog>({ state: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [inspectionAttempt, setInspectionAttempt] = useState(0)
  const [evidence, setEvidence] = useState<Record<string, { eligibility: Eligibility; reason?: string }>>({})
  const trigger = useRef<HTMLButtonElement>(null)
  const popup = useRef<HTMLDivElement>(null)
  const reposition = useRef<(() => void) | null>(null)
  const [position, setPosition] = useState({ left: 8, top: 8, width: 320, maxHeight: 360 })
  const close = useCallback(() => { setOpen(false); trigger.current?.focus({ preventScroll: true }) }, [])
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const rect = trigger.current?.getBoundingClientRect()
      if (!rect) return
      if (rect.bottom < 0 || rect.top > window.innerHeight || rect.right < 0 || rect.left > window.innerWidth) {
        close()
        return
      }
      const width = Math.min(344, Math.max(0, window.innerWidth - 16))
      const above = rect.top - 16
      const below = window.innerHeight - rect.bottom - 16
      const upward = above > below
      const maxHeight = Math.max(0, Math.min(400, upward ? above : below))
      const contentHeight = popup.current ? popup.current.scrollHeight + popup.current.offsetHeight - popup.current.clientHeight : maxHeight
      const next = { width, maxHeight, left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
        top: upward ? Math.max(8, rect.top - Math.min(contentHeight, maxHeight) - 8) : rect.bottom + 8 }
      setPosition(current => current.width === next.width && current.maxHeight === next.maxHeight
        && current.left === next.left && current.top === next.top ? current : next)
    }
    reposition.current = place
    place()
    const initial = popup.current?.querySelector<HTMLElement>('[aria-selected="true"]')
      ?? popup.current?.querySelector<HTMLElement>('[role="option"]') ?? popup.current
    initial?.focus()
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !popup.current?.contains(event.target) && !trigger.current?.contains(event.target)) close()
    }
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    document.addEventListener('pointerdown', outside)
    // Width constraints and late evidence can change wrapping/height without
    // changing the anchor. Re-measure locally, without refocusing the menu.
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(place)
    if (popup.current) observer?.observe(popup.current)
    if (trigger.current) observer?.observe(trigger.current)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
      document.removeEventListener('pointerdown', outside)
      observer?.disconnect()
      reposition.current = null
    }
  }, [open, close, catalog])
  useLayoutEffect(() => {
    if (open) reposition.current?.()
  }, [open, evidence])
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
  useEffect(() => {
    let live = true
    setEvidence({})
    if (inspectChoice && catalog.state === 'ready' && !disabled) {
      for (const config of catalog.configs.filter(item => item.harness === harnessId && item.archivedAt === null)) {
        for (const model of config.models.filter(item => item.availability === 'available')) {
          const key = `${config.id}\u0000${model.modelId}`
          void inspectChoice({ harnessId, providerConfigId: config.id, modelId: model.modelId }, config.version)
            .then(value => { if (live) setEvidence(current => ({ ...current, [key]: value })) },
              cause => { if (live) setEvidence(current => ({ ...current, [key]: { eligibility: 'unknown', reason: describe(cause) } })) })
        }
      }
    }
    return () => { live = false }
  }, [inspectChoice, catalog, harnessId, disabled, inspectionAttempt])
  const rows = scoped.flatMap((config) =>
    config.models.map((model) => {
      // The backend's per-model availability is authoritative and can never be
      // overridden by a session eligibility verdict.
      const available = model.availability === 'available'
      return {
        config, modelId: model.modelId, displayName: model.displayName || model.modelId,
        available,
        unavailableReason: model.unavailableReason ?? undefined,
        eligibility: inspectChoice ? evidence[`${config.id}\u0000${model.modelId}`]?.eligibility ?? 'unknown'
          : source.eligibility(harnessId, config.id, model.modelId),
        reason: inspectChoice ? (evidence[`${config.id}\u0000${model.modelId}`]
          ? evidence[`${config.id}\u0000${model.modelId}`].reason : location.kind === 'draft'
            ? '创建会话后才能核实模型。' : disabled ? '当前会话暂不能选择模型。' : '正在核实此会话的模型可选择性。')
          : source.reason?.(harnessId, config.id, model.modelId),
      }
    }))
  const selectable = (row: (typeof rows)[number]) => !disabled && row.available && row.eligibility === 'ready'
  const chosen = queued
  const chosenConfig = configs.find(config => config.id === chosen?.providerConfigId)
  const chosenModel = chosenConfig?.models.find(model => model.modelId === chosen?.modelId)
  const currentRows = current ? rows.filter(row => row.modelId === current.modelId && row.config.provider === current.provider) : []

  return (
    <div data-testid="model-selector" style={{ display: 'inline-flex', minWidth: 0, maxWidth: '100%' }}>
      <style>{selectorStyles}</style>
      <button type="button" ref={trigger} className="mp-selector-trigger" aria-haspopup="listbox" aria-expanded={open}
        data-testid="model-selector-trigger" onClick={() => {
        if (!open) {
          // Native readiness may change without a new session identity. Opening
          // is an explicit fresh read, not a poll or a configuration mutation.
          setEvidence({})
          setInspectionAttempt(value => value + 1)
          onOpen?.()
        }
        setOpen(!open)
      }}>
        <span>{chosen ? `${chosenConfig?.displayName ?? '已选供应商'} › ${chosenModel?.displayName || chosen.modelId}`
          : current ? `${current.provider ? `${current.provider} › ` : ''}${current.modelId}` : '模型'}</span>
        {queued && <small>下轮使用</small>}<span aria-hidden="true">⌄</span>
      </button>
      {open && createPortal(
        <div ref={popup} className="mp-selector-popover" style={{ position: 'fixed', ...position }} tabIndex={-1}
          role="listbox" aria-label="Provider › Model" data-testid="model-selector-list" onKeyDown={event => {
            if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close() }
            if (event.key === 'Tab') close()
            if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
              event.preventDefault()
              const options = Array.from(popup.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? [])
              const index = options.indexOf(document.activeElement as HTMLButtonElement)
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
                : (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length
              options[next]?.focus()
            }
          }}>
          <div className="mp-selector-heading">模型<span>{location.kind === 'draft' ? '新建会话' : '当前会话'} · {harnessId || '未选择 Harness'}</span></div>
          {statusReason && <p role="status" data-testid="model-owner-note-details">{statusReason}</p>}
          {catalog.state === 'loading' && <p data-testid="model-load-pending">正在加载模型列表…</p>}
          {catalog.state === 'error' && (
            <div role="alert" data-testid="model-load-error">
              <p>模型列表加载失败：{catalog.message}</p>
              <button type="button" data-testid="model-load-retry" onClick={retry}>重试</button>
            </div>
          )}
          {catalog.state === 'ready' && harnessId === '' && <p>新建会话请先选择 Harness。</p>}
          {catalog.state === 'ready' && harnessId !== '' && rows.length === 0 && <p>此 Harness 暂无 Provider 配置。</p>}
          {rows.map((row, index) => {
            const isSelectable = selectable(row)
            return (
              <div key={`${row.config.id}/${row.modelId}`}>
              {(index === 0 || rows[index - 1].config.id !== row.config.id) && <div className="mp-selector-group">{row.config.displayName}</div>}
              <button type="button" className="mp-selector-option" role="option"
                aria-selected={queued ? queued.modelId === row.modelId && queued.providerConfigId === row.config.id
                  : currentRows.length === 1 && currentRows[0] === row}
                aria-disabled={!isSelectable}
                data-testid={`model-option-${row.config.id}-${row.modelId}`}
                onClick={() => {
                  if (!isSelectable) return
                  onQueue?.({ harnessId, providerConfigId: row.config.id, modelId: row.modelId,
                    ...(inspectChoice ? { configVersion: row.config.version } : {}) })
                  close()
                }}>
                <span className="mp-selector-model">{row.displayName}<span aria-hidden="true">{queued?.modelId === row.modelId && queued?.providerConfigId === row.config.id ? '✓' : ''}</span></span>
                <span className="mp-selector-evidence">
                  {!row.available
                    ? `${ELIGIBILITY_GLYPHS.unsupported} ${row.unavailableReason ?? ELIGIBILITY_LABELS.unsupported}`
                    : `${ELIGIBILITY_GLYPHS[row.eligibility]} ${ELIGIBILITY_LABELS[row.eligibility]}`}
                  {row.reason ? `：${row.reason}` : ''}
                </span>
              </button>
              </div>
            )
          })}
          {catalog.state === 'ready' && harnessId !== '' && rows.length > 0
            && rows.every((row) => !selectable(row)) && (
            <p data-testid="no-selectable">此会话暂不可选模型（尚无可用证据）。</p>
          )}
        </div>, document.body,
      )}
    </div>
  )
}

const selectorStyles = `
.mp-selector-trigger{display:inline-flex;align-items:center;gap:6px;max-width:100%;height:28px;padding:0 7px;border:0;border-radius:7px;background:transparent;color:inherit;font:inherit;font-size:12px;cursor:pointer;white-space:nowrap}
.mp-selector-trigger>span:first-child{overflow:hidden;text-overflow:ellipsis}.mp-selector-trigger small{color:#858589;font-size:10px}.mp-selector-trigger:hover{background:#88888812}
.mp-selector-trigger:focus-visible,.mp-selector-option:focus-visible{outline:2px solid #548fe5;outline-offset:2px}
.mp-selector-popover{z-index:1000;box-sizing:border-box;overflow:auto;padding:8px;background:var(--ordessa-color-surface,#fff);color:var(--ordessa-color-text,#242426);border:1px solid var(--ordessa-color-border,#88888830);border-radius:14px;box-shadow:0 8px 30px #00000018;font:12px/1.5 system-ui,sans-serif}
.mp-selector-heading{display:flex;justify-content:space-between;gap:12px;padding:6px 8px;font-weight:600}.mp-selector-heading span{color:#858589;font-size:11px;font-weight:400}
.mp-selector-group{padding:10px 8px 4px;color:#77777e;font-size:11px}.mp-selector-option{display:block;width:100%;text-align:left;padding:7px 9px;background:transparent;color:inherit;border:0;border-radius:8px;font:inherit;cursor:pointer}.mp-selector-option:hover,.mp-selector-option:focus{background:#88888812}.mp-selector-option[aria-disabled=true]{cursor:not-allowed}.mp-selector-model{display:flex;justify-content:space-between;font-size:13px}.mp-selector-evidence{display:block;color:#77777e;font-size:11px;overflow-wrap:anywhere}.mp-selector-popover p{padding:4px 8px;margin:6px 0;font-size:12px;overflow-wrap:anywhere}
.mp-selector-heading span,.mp-selector-group,.mp-selector-evidence{color:var(--ordessa-color-muted,#77777e)}
@media(prefers-color-scheme:dark){.mp-selector-popover{background:var(--ordessa-color-surface,#252526);color:var(--ordessa-color-text,#eee)}}
`
