// Reasoning block, ported from ZCode packages/ui/src/components/ai-elements/
// reasoning.tsx @ 29628c9a (derived from vercel/ai-elements, Apache-2.0 — see
// THIRD-PARTY-NOTICES.md). Ported: default-collapsed, user choice beats every
// later state transition (userInteractedRef), auto-collapse only on a turn-key
// change when the user never interacted, lazy unmount of heavy content 300ms
// after collapse (Radix height animation), streaming summary in the trigger.
// Adapted per research-plan: durations come only from real props (no UI timer
// faking backend latency), no intl/diagnostics/test-id dependencies, no global
// collapse cache, no queued-summary animation (explicit product divergence).
import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { Collapsible } from 'radix-ui'
import type { ChatReasoningProps } from '@extensions/ordessa.chat-api/contract.js'

const CONTENT_COLLAPSE_UNMOUNT_DELAY_MS = 300

export const ReasoningBlock = memo(function ReasoningBlock({ props }: { props: ChatReasoningProps }) {
  const streaming = props.status === 'streaming'
  const [isOpen, setIsOpen] = useState(false)
  const [userInteracted, setUserInteracted] = useState(false)
  const [shouldRenderContent, setShouldRenderContent] = useState(false)
  const contentUnmountDelay = useRef<number | null>(null)
  const previousPartRef = useRef<string | undefined>(undefined)

  // A NEW reasoning part (autoCollapseKey analog) starts collapsed again — but
  // only when the user never manually opened this block.
  useEffect(() => {
    const previous = previousPartRef.current
    previousPartRef.current = props.partId
    if (userInteracted) return
    if (previous !== undefined && previous !== props.partId) setIsOpen(false)
  }, [props.partId, userInteracted])

  useEffect(() => {
    if (isOpen) {
      if (contentUnmountDelay.current !== null) {
        window.clearTimeout(contentUnmountDelay.current)
        contentUnmountDelay.current = null
      }
      setShouldRenderContent(true)
      return
    }
    if (!shouldRenderContent) return
    // Radix's collapse animation reads the real content height during the
    // closed phase; unmount only after the 300ms transition finished.
    contentUnmountDelay.current = window.setTimeout(() => {
      setShouldRenderContent(false)
      contentUnmountDelay.current = null
    }, CONTENT_COLLAPSE_UNMOUNT_DELAY_MS)
    return () => {
      if (contentUnmountDelay.current !== null) {
        window.clearTimeout(contentUnmountDelay.current)
        contentUnmountDelay.current = null
      }
    }
  }, [isOpen, shouldRenderContent])

  useEffect(() => () => {
    if (contentUnmountDelay.current !== null) window.clearTimeout(contentUnmountDelay.current)
  }, [])

  const handleToggle = useCallback((next: boolean) => {
    setUserInteracted(true)
    setIsOpen(next)
  }, [])

  const streamingLabel = streaming ? '思考中…' : '思考'
  const durationLabel = props.durationMs !== undefined
    ? `（${Math.max(1, Math.round(props.durationMs / 1000))} 秒）` : ''

  return (
    <Collapsible.Root className="chat-reasoning" data-streaming={streaming ? 'true' : 'false'} open={isOpen}
      onOpenChange={handleToggle} data-part-id={props.partId}>
      <Collapsible.Trigger className="chat-reasoning-trigger" data-testid="chat-reasoning-trigger"
        aria-label={`${streamingLabel} ${durationLabel}，${isOpen ? '收起' : '展开'}`}>
        <span className="chat-reasoning-chevron" aria-hidden="true">▸</span>
        <span className="chat-reasoning-label">{streamingLabel}{durationLabel}</span>
        {props.copy && (
          <button type="button" className="chat-ghost-action" data-action="copy-reasoning"
            aria-label="复制思考内容" onClick={event => { event.stopPropagation(); void props.copy?.() }}>复制</button>
        )}
      </Collapsible.Trigger>
      {shouldRenderContent && (
        <Collapsible.Content className="chat-reasoning-content">
          <pre className="chat-reasoning-text">{props.text}</pre>
        </Collapsible.Content>
      )}
    </Collapsible.Root>
  )
})
