// Conversation scroll container, ported from ZCode
// packages/ui/src/components/ai-elements/conversation.tsx @ 29628c9a
// (Apache-2.0) with use-stick-to-bottom@1.1.3. Ported: follow only near the
// bottom, active reading is never yanked, and an explicit 回到底部 entry
// appears when following disengages. Dropped: upstream messagesToMarkdown/
// download and AI-SDK bindings. The composer lives OUTSIDE this viewport
// (input-spec C01) — this component renders only the scroller.
import type { ReactNode } from 'react'
import { useStickToBottom } from 'use-stick-to-bottom'

export function ConversationScroll({ children, testid }: { children: ReactNode; testid?: string }) {
  const stick = useStickToBottom()
  const away = !(stick.isAtBottom || stick.isNearBottom)
  return (
    <div className="chat-scroll-wrap">
      <div className="chat-scroll-viewport" ref={stick.scrollRef} data-testid={testid}>
        <div ref={stick.contentRef} className="chat-scroll-content">
          {children}
        </div>
      </div>
      {away && (
        <div className="chat-scroll-resume">
          <button type="button" className="chat-ghost-action" data-testid="chat-scroll-resume"
            onClick={() => { void stick.scrollToBottom() }}>回到底部</button>
        </div>
      )}
    </div>
  )
}
