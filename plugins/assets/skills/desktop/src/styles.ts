/**
 * Page styles plus the one responsive behaviour the G14 counterexample names:
 * 窄屏不可操作. Below the width threshold the two-column "本层设置 / 最终结果"
 * rows stack (`[data-narrow=stack]`), so both cells and every tri-state button
 * stay reachable without horizontal scrolling; nothing is hidden behind a
 * hover or a wider viewport.
 *
 * `useNarrow` reads the same breakpoint the CSS uses, so the structural change
 * and the visual one cannot disagree. `window.matchMedia` is absent in some
 * renderer/test contexts; absence means "not narrow", never "hide controls".
 */
import { useEffect, useState } from 'react'

export const NARROW_QUERY = '(max-width: 720px)'

export const styles = `
.skills-settings { display:flex; flex-direction:column; gap:18px; font-size:13px; line-height:1.5; padding:10px 12px; overflow:auto; }
.skills-settings section { border:1px solid var(--ui-line,#e8e8e8); border-radius:10px; padding:10px 12px; background:var(--ui-surface,#fff); min-width:0; }
.skills-settings h3 { margin:0 0 6px; font-size:14px; font-weight:650; }
.skills-settings h4 { margin:0 0 4px; font-size:13px; }
.skills-settings [role=group] { display:inline-flex; gap:2px; }
.skills-settings button { border:0; border-radius:8px; background:transparent; padding:4px 9px; font-size:12px; color:inherit; }
.skills-settings button:hover:not(:disabled) { background:var(--ui-hover,#eaeaea); }
.skills-settings button[aria-pressed=true] { background:var(--ui-selected,#e3e4e6); font-weight:600; }
.skills-settings button:disabled { opacity:.35; }
.skills-settings :focus-visible { outline:2px solid var(--ui-accent,#3b82f6); outline-offset:2px; }
.skills-settings table { width:100%; border-collapse:collapse; table-layout:fixed; }
.skills-settings th, .skills-settings td { text-align:left; vertical-align:top; padding:6px 8px; border-top:1px solid var(--ui-line,#e8e8e8); overflow-wrap:anywhere; }
.skills-settings thead th { border-top:0; font-size:11px; color:var(--ui-ink-secondary,#6b6e73); font-weight:600; }
.skills-settings select, .skills-settings input { font:inherit; padding:3px 6px; max-width:100%; }
.skills-settings ul { margin:4px 0; padding-left:18px; }
.skills-settings [data-testid=skills-list] { list-style:none; padding-left:0; }
.skills-settings [data-testid=skills-list] button { width:100%; text-align:left; }
.skills-settings [data-testid=skills-list] [aria-selected=true] button, .skills-settings [data-testid=skills-list] button[aria-selected=true] { background:var(--ui-selected,#e3e4e6); }
.skills-settings pre { background:var(--ui-sunken,#f0f0f1); padding:8px; border-radius:8px; white-space:pre-wrap; overflow-wrap:anywhere; max-height:220px; overflow:auto; }
.skills-settings [role=alert] { color:var(--ui-error,#b3261e); }
.skills-settings [data-narrow=stack] th, .skills-settings [data-narrow=stack] td { display:block; border-top:0; }
.skills-settings [data-narrow=stack] th { padding-bottom:0; font-weight:650; }
@media (max-width: 720px) {
  .skills-settings table, .skills-settings tbody, .skills-settings tr, .skills-settings th, .skills-settings td { display:block; width:100%; }
  .skills-settings thead { display:none; }
  .skills-settings tr { border-top:1px solid var(--ui-line,#e8e8e8); padding:4px 0; }
  .skills-settings [role=group] { flex-wrap:wrap; }
}
`

/** The narrow flag the structural change keys off. */
export function useNarrow(query = NARROW_QUERY): boolean {
  const read = () => (typeof window !== 'undefined' && window.matchMedia) ? window.matchMedia(query).matches : false
  const [narrow, setNarrow] = useState(read)
  useEffect(() => {
    if (typeof window === 'undefined' || window.matchMedia === undefined) return
    const list = window.matchMedia(query)
    const onChange = () => setNarrow(list.matches)
    onChange()
    list.addEventListener('change', onChange)
    return () => list.removeEventListener('change', onChange)
  }, [query])
  return narrow
}
