// Message layout, ported from ZCode packages/ui/src/components/ai-elements/
// message.tsx @ 29628c9a (Apache-2.0): user messages keep a light bubble,
// assistant output is full-width readable text — no card wrapper. Adapted:
// role comes from the chat-api display DTO, actions are consumer-provided
// (copy visible body / open verified link); the component never reads a
// message service. Copying the body never mixes in reasoning or tool logs —
// those are separate parts (research-plan §5).
import type { ChatMessageBodyProps } from '@extensions/ordessa.chat-api/contract.js'
import { MarkdownBody, type ChatTheme } from './markdown-body'

export function MessageLayout({ props, theme }: { props: ChatMessageBodyProps; theme: ChatTheme }) {
  const isUser = props.role === 'user'
  const streaming = props.status === 'streaming'
  return (
    <article className={`chat-message ${isUser ? 'chat-message-user' : 'chat-message-assistant'}`}
      data-role={props.role} data-status={props.status} data-message-id={props.messageId}>
      <div className="chat-message-body">
        {isUser
          ? <div className="chat-user-text">{props.body}</div>
          : <MarkdownBody text={props.body} streaming={streaming} theme={theme} codeWrap={props.display?.codeWrap}
              onOpenLink={props.actions?.openLink} />}
      </div>
      {(props.actions?.copyVisibleBody) && (
        <div className="chat-message-actions">
          <button type="button" className="chat-ghost-action" data-action="copy-body"
            onClick={() => { void props.actions?.copyVisibleBody?.() }}>复制正文</button>
        </div>
      )}
      {props.status === 'interrupted' && <div className="chat-status-note" data-note="interrupted">这条回复已被中断。</div>}
      {props.status === 'unknown' && <div className="chat-status-note" data-note="unknown">这条回复的最终状态未知，可能不完整。</div>}
    </article>
  )
}
