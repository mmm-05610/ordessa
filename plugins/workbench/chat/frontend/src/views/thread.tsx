// Thread body: renders one conversation's snapshot parts. Ported behavior:
// completed history renders static, streaming only while content is arriving,
// thinking default-collapsed with per-part user choice, tools as compact rows
// with view-scoped expansion state. Unknown/interrupted states render explicit
// notes — never a fake completed look (spec US1).
import { memo } from 'react'
import type { ChatContributionsService, ObservableValues } from '@extensions/ordessa.chat-api/contract.js'
import type { ChatConversationDisplay, ConversationPart } from '../adapters/agent'
import type { ViewExpansionState } from '../state/expansion'
import type { ChatTheme } from '../components/messages/markdown-body'
import { MessageLayout } from '../components/messages/message-layout'
import { ReasoningBlock } from '../components/messages/reasoning-block'
import { ToolActivity } from '../components/tools/tool-frame'
import { ConversationScroll } from '../components/conversation/conversation-scroll'
import { createElement, useSyncExternalStore, type ComponentType } from 'react'

/** Resolution of a contribution key to a component. Pre-foundation this is the
 * chat default provider's own table (chat-internal keys only); a foreign key
 * means its provider is absent and the position stays empty — never an error
 * visible to the whole page (contracts.md §4). The erased read side hands the
 * component untyped props; the key↔props pairing was enforced at registration. */
export type ErasedComponent = ComponentType<Record<string, unknown>>
export type ComponentResolver = (keyId: string) => ErasedComponent | undefined

export function makeDefaultResolver(overrides: Record<string, ErasedComponent> = {}): ComponentResolver {
  const table: Record<string, ErasedComponent> = { ...overrides }
  return keyId => table[keyId]
}

export const ThreadBody = memo(function ThreadBody({ display, expansion, theme, toolbarSlot }: {
  display: ChatConversationDisplay
  expansion: ViewExpansionState
  theme: ChatTheme
  /** Live toolbar contributions for message.actions (consumed per part). */
  toolbarSlot?: ObservableValues<import('@extensions/ordessa.chat-api/contract.js').ChatContributionView>
}) {
  void toolbarSlot
  return (
    <ConversationScroll testid="chat-thread">
      <div className="chat-thread-list">
        {display.parts.map((part: ConversationPart, index: number) => {
          const key = `${display.conversationKey}:${index}`
          if (part.kind === 'reasoning' && part.reasoning) {
            return <ReasoningBlock key={`r${key}`} props={part.reasoning} />
          }
          if (part.kind === 'body' && part.body) {
            return <MessageLayout key={`b${key}`} props={part.body} theme={theme} />
          }
          if (part.kind === 'tool' && part.tool) {
            return <ToolActivity key={`t${key}`} props={part.tool} conversationKey={display.conversationKey} expansion={expansion} />
          }
          return null
        })}
      </div>
    </ConversationScroll>
  )
})

/** Live subscription helper shared by the page for slot views. */
export function useSlot(slot: ObservableValues<ChatContributionViewLike>): readonly ChatContributionViewLike[] {
  return useSyncExternalStore(slot.subscribe, slot.getSnapshot, slot.getSnapshot)
}
type ChatContributionViewLike = import('@extensions/ordessa.chat-api/contract.js').ChatContributionView
