// Shared plus/slash input panel (input-spec US6 P01–P06), consuming the
// chat-api input-source query view. One panel instance at a time is enforced
// by the composer (the owner of `mode`); a transparent backdrop closes it on
// outside click and focus is restored by the composer when it closes.
// Semantics ported from the upstream slash/mention panels (token query,
// grouped rendering, loading/error separation, stable ordering); the groups
// and entries come from registered sources only — installed plugins never
// appear implicitly (P05).
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChatInputEntry, ChatInputSourceView, ObservableValues } from '@extensions/ordessa.chat-api/contract.js'
import { useSyncExternalStore } from 'react'

export interface InputPanelProps {
  readonly mode: 'plus' | 'slash'
  readonly sources: ObservableValues<ChatInputSourceView>
  /** plus 模式：面板自带搜索框，不修改草稿文本 */
  readonly initialPlusQuery?: string
  readonly onPick: (entry: ChatInputEntry) => void
  readonly onClose: () => void
  readonly onRetry: () => void
  /** slash 建议态下 Tab 补全高亮 insert-command */
  readonly onComplete?: (entry: ChatInputEntry) => void
  /** Focus stays in the textarea while the panel is open; the panel
   * registers its key handler here so forwarded keys (Enter/Tab/arrows) are
   * consumed by the panel before the input acts (input-spec C04). */
  readonly keyForwardRef?: { current?: (event: React_KeyboardEvent) => boolean }
}

type React_KeyboardEvent = { key: string; preventDefault(): void; defaultPrevented: boolean }

interface FlatRow { readonly entry: ChatInputEntry; readonly source: ChatInputSourceView; readonly groupTitle?: string }

function flatten(view: readonly ChatInputSourceView[]): FlatRow[] {
  const rows: FlatRow[] = []
  for (const source of view) {
    const groupTitle = new Map(source.source.groups.map(group => [group.id, group.title] as const))
    for (const entry of source.entries) {
      // The query was already issued with the right surface; entries arrive
      // stably ordered from the registry, so the panel only flattens.
      rows.push({ entry, source, groupTitle: groupTitle.get(entry.groupId) })
    }
  }
  return rows
}

export function InputPanel(props: InputPanelProps) {
  const view = useSyncExternalStore(props.sources.subscribe, props.sources.getSnapshot, props.sources.getSnapshot)
  const [plusQuery, setPlusQuery] = useState(props.initialPlusQuery ?? '')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)

  const rows = useMemo(() => {
    const all = flatten(view).filter(row => row.entry.surfaces.includes(props.mode === 'plus' ? 'plus' : 'slash'))
    const needle = plusQuery.trim().toLowerCase()
    if (!needle || props.mode !== 'plus') return all
    // plus 搜索是浏览过滤：只过滤已加载条目，不产生新的来源查询副作用
    return all.filter(row => row.entry.title.toLowerCase().includes(needle)
      || (row.entry.description ?? '').toLowerCase().includes(needle))
  }, [view, props.mode, plusQuery])
  const enabledRows = useMemo(() => rows.filter(row => row.entry.availability.kind === 'ready'), [rows])

  useEffect(() => { setSelectedIndex(0) }, [rows.length, plusQuery])

  useEffect(() => {
    const item = listRef.current?.querySelectorAll('[data-panel-row="true"]')[selectedIndex]
    item?.scrollIntoView({ block: 'nearest' })
  }, [selectedIndex])

  const pickRow = (row: FlatRow | undefined) => {
    if (!row) return
    if (row.entry.availability.kind !== 'ready') return
    props.onPick(row.entry)
  }

  const handleKeyDown = (event: React_KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setSelectedIndex(index => Math.min(index + 1, enabledRows.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setSelectedIndex(index => Math.max(index - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      pickRow(enabledRows[selectedIndex])
    } else if (event.key === 'Tab' && props.mode === 'slash') {
      const row = enabledRows[selectedIndex]
      if (row && row.entry.action.kind === 'insert-command') {
        event.preventDefault()
        props.onComplete?.(row.entry)
      }
    } else if (event.key === 'Escape') {
      event.preventDefault()
      props.onClose()
    }
  }

  useEffect(() => {
    if (!props.keyForwardRef) return
    props.keyForwardRef.current = event => {
      handleKeyDown(event)
      return event.defaultPrevented
    }
    return () => {
      if (props.keyForwardRef) props.keyForwardRef.current = undefined
    }
  })

  const searchId = 'chat-panel-search'
  return (
    <div className="chat-panel-backdrop" data-testid="chat-input-panel" data-mode={props.mode}
      onMouseDown={() => props.onClose()}>
      <div className="chat-panel" role="listbox" aria-label={props.mode === 'plus' ? '添加与操作面板' : '命令建议'}
        onMouseDown={event => event.stopPropagation()} onKeyDown={handleKeyDown}>
        {props.mode === 'plus' && (
          <div className="chat-panel-search">
            <input id={searchId} data-testid="chat-panel-search" placeholder="搜索添加与操作…" value={plusQuery}
              autoFocus onChange={event => { setPlusQuery(event.currentTarget.value); }} />
          </div>
        )}
        <div className="chat-panel-list" ref={listRef}>
          {view.some(source => source.state.status === 'loading') && (
            <div className="chat-panel-note" data-state="loading">正在加载可用项…</div>
          )}
          {rows.length === 0 && !view.some(source => source.state.status === 'loading') && (
            <div className="chat-panel-note" data-state="empty">没有匹配项</div>
          )}
          {view.map(source => {
            if (source.state.status === 'error') {
              return (
                <div key={source.source.id} className="chat-panel-source-error" data-state="error">
                  <span>来源「{source.source.title}」加载失败：{source.state.error}</span>
                  <button type="button" className="chat-ghost-action" data-action="retry-source"
                    onClick={() => props.onRetry()}>重试</button>
                </div>
              )
            }
            const sourceRows = rows.filter(row => row.source.source.id === source.source.id)
            if (sourceRows.length === 0) return null
            let lastGroup = ''
            return sourceRows.map(row => {
              const enabled = row.entry.availability.kind === 'ready'
              const index = enabledRows.indexOf(row)
              const groupHeader = row.groupTitle !== lastGroup && row.groupTitle !== undefined
                ? (lastGroup = row.groupTitle, row.groupTitle)
                : undefined
              return (
                <div key={row.entry.id}>
                  {groupHeader && <div className="chat-panel-group">{groupHeader}</div>}
                  <button type="button" className="chat-panel-row" data-panel-row="true" role="option"
                    aria-selected={index === selectedIndex} aria-disabled={!enabled}
                    data-entry-id={row.entry.id} data-source-id={source.source.id}
                    data-selected={index === selectedIndex ? 'true' : 'false'}
                    title={row.entry.title}
                    onClick={() => pickRow(row)}
                    onMouseMove={() => { if (enabled) setSelectedIndex(index) }}>
                    <span className="chat-panel-row-main">
                      <span className="chat-panel-row-title">{row.entry.title}</span>
                      {row.entry.description && <span className="chat-panel-row-desc">{row.entry.description}</span>}
                    </span>
                    <span className="chat-panel-row-source">{source.source.title}</span>
                    {!enabled && row.entry.availability.kind === 'disabled' && (
                      <span className="chat-panel-row-disabled" data-testid="chat-panel-disabled-reason">{row.entry.availability.reason}</span>
                    )}
                  </button>
                </div>
              )
            })
          })}
        </div>
      </div>
    </div>
  )
}
