import type { DragEvent } from 'react'
import type { Region, View } from '@extensions/ordessa.contracts/contract.js'

export const regions: Region[] = ['left', 'main', 'right', 'top', 'bottom']
export const labels: Record<Region, string> = { left: '左侧栏', right: '右侧栏', bottom: '底部面板', top: '顶部面板', main: '主区' }

/** Multi-view tab strip. Its exact shape is pinned by out-of-scope harnesses
 * ([data-region] header [role="group"] button, tab text = view title, see
 * apps/desktop/electron/main.ts and preview-main.ts) — do not alter it here. */
export function ViewTabs({ name, list, active, open, onDragStart, onDragEnd }: {
  name: Region; list: readonly View[]; active: View | undefined; open(id: string): void
  onDragStart(event: DragEvent<HTMLButtonElement>, view: View): void; onDragEnd(): void
}) {
  // A tab strip is worth showing only for two or more views; a single view
  // renders bare and keeps its move/close controls in wb-region-actions.
  if (list.length < 2) return null
  return <div role="group" aria-label={`${name}视图`}>{list.map(v => <button key={v.id} draggable aria-pressed={v.id === active?.id}
    onDragStart={e => onDragStart(e, v)} onDragEnd={onDragEnd} onClick={() => open(v.id)} title={`${v.title} · 拖动以移动`}>{v.title}</button>)}</div>
}

/** The "移动…" select and close control for the active view. The whole block
 * stays out of the permanent visual focus area (revealed on header hover or
 * once focus enters — keyboard reachable, never removed from the DOM). */
export function RegionActions({ name, active, showCollapse, move, close, collapse }: {
  name: Region; active: View | undefined; showCollapse: boolean
  move(id: string, region: Region): void; close(id: string): void; collapse(region: Region): void
}) {
  return <div className="wb-region-actions">{active && <>
    <select aria-label={`移动 ${active.title} 到`} value="" onChange={e => { if (e.target.value) move(active.id, e.target.value as Region) }}>
      <option value="">移动…</option>{regions.filter(r => r !== name).map(r => <option key={r} value={r}>{labels[r]}</option>)}
    </select>
    <button aria-label={`关闭${active.title}`} title="关闭视图" onClick={() => close(active.id)}>×</button>
  </>}{showCollapse && <button aria-label={`收起${labels[name]}`} title={`收起${labels[name]}`} onClick={() => collapse(name)}>−</button>}</div>
}
