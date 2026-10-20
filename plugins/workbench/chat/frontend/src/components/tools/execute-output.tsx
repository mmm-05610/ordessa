// Command output viewport, ported from ZCode
// packages/ui/src/ToolCallBlocks/renderers/ExecuteOutput.tsx + components/ui/
// scroll-fade-viewport.tsx @ 29628c9a (Apache-2.0). Ported: ~five-line preview
// height, programmatic follow-to-bottom while streaming, scrolling up freezes
// the visible text (reading position is never yanked), returning to the bottom
// resumes. Added over the upstream: an explicit 恢复跟随 button and a 新输出
// hint while frozen (upstream only had the scroll gesture); the fade mask via
// plain CSS instead of Tailwind arbitrary values; the logger dependency is
// dropped; the frozen snapshot is display-only (business state never freezes),
// and the snapshot clears when the tool id changes (keyed remount upstream).
import { useLayoutEffect, useRef, useState } from 'react'

export function ExecuteOutput({ text, running, exitCode, truncated }: {
  text: string
  running: boolean
  exitCode?: number | 'unknown'
  truncated: boolean
}) {
  const scroll = useRef<HTMLPreElement>(null)
  const previousTop = useRef(0)
  const hasStreamed = useRef(running)
  const [frozen, setFrozen] = useState<string | null>(null)
  const [hasNewOutput, setHasNewOutput] = useState(false)
  const following = frozen === null
  const display = frozen ?? text

  useLayoutEffect(() => {
    if (running) hasStreamed.current = true
    if (!hasStreamed.current || !following || !scroll.current) return
    scroll.current.scrollTop = scroll.current.scrollHeight
    // Record the actual post-scroll position: a shrinking tail must not be
    // misread as the user scrolling up.
    previousTop.current = scroll.current.scrollTop
  }, [display, following, running])

  useLayoutEffect(() => {
    if (!following) setHasNewOutput(true)
  }, [text, following])
  useLayoutEffect(() => {
    if (following) setHasNewOutput(false)
  }, [following])

  return (
    <div className="chat-execute" data-following={following ? 'true' : 'false'} data-testid="chat-execute-output">
      <pre className={`chat-execute-viewport ${truncated ? 'chat-execute-truncated' : ''}`} tabIndex={0}
        ref={scroll}
        onScroll={event => {
          const el = event.currentTarget
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 8
          if (hasStreamed.current && following && el.scrollTop < previousTop.current && !atBottom) {
            // Freeze exactly what the user was reading — not the newest text.
            setFrozen(el.textContent ?? display)
          } else if (!following && atBottom) {
            setFrozen(null)
          }
          previousTop.current = el.scrollTop
        }}>
        {display}
      </pre>
      {!following && (
        <div className="chat-execute-follow" data-testid="chat-execute-follow">
          {hasNewOutput && <span className="chat-execute-new" data-testid="chat-execute-new">有新输出</span>}
          <button type="button" className="chat-ghost-action" data-action="resume-follow"
            onClick={() => { setFrozen(null) }}>恢复跟随</button>
        </div>
      )}
      {(truncated || exitCode !== undefined) && (
        <div className="chat-execute-meta">
          {truncated && <span>输出已截断</span>}
          {exitCode !== undefined && <span data-testid="chat-execute-exit">退出码：{exitCode === 'unknown' ? '未知' : exitCode}</span>}
        </div>
      )}
    </div>
  )
}
