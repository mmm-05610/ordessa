// Thin streaming Markdown surface, ported from ZCode
// packages/ui/src/components/ai-elements/message.tsx @ 29628c9acdb81b703bbd4080c207a0e7ce5e276e
// (Apache-2.0, see THIRD-PARTY-NOTICES.md). Ported: the streaming/static mode
// split (`resolveMessageStreamdownMode`), the render-error → original-text
// fallback boundary, the render key that carries theme/wrap but NOT the
// streaming flag, the CJK plugin with singleTilde disabled, and the custom
// stable code-block renderer replacing Streamdown's built-in one.
// Dropped by design: ZCode citations, artifact readers, workspace path
// rewriting, editor/browser services, math/mermaid plugins; link opening is a
// consumer-provided verified action (chat-api contract), never a local fetch.
import { Component, useMemo, type ComponentProps, type ReactNode } from 'react'
import { Streamdown } from 'streamdown'
import { cjk } from '@streamdown/cjk'
import type { ChatActionResult } from '@extensions/ordessa.chat-api/contract.js'
import { ChatCodeBlock } from './code-block'

export type ChatTheme = 'light' | 'dark'

/** Only genuinely streaming output parses in streaming mode; history and
 * completed messages stay static so a remount never re-enters the update loop
 * (upstream React #185 note). */
export function resolveChatMarkdownMode(streaming: boolean): 'streaming' | 'static' {
  return streaming ? 'streaming' : 'static'
}

/** Theme/wrap participate in the React key so late theme switches remount the
 * subtree; the streaming flag must NOT (it would remount the whole markdown on
 * every status flicker). */
export function buildChatMarkdownRenderKey(params: { theme: ChatTheme; codeWrap: boolean }): string {
  return [params.theme, params.codeWrap ? 'wrap' : 'scroll'].join(':')
}

interface MarkdownBoundaryState { error: boolean }

/** One markdown render failure degrades this body to its original text — the
 * error never bubbles to the session boundary, and the text is never lost. */
class MarkdownBoundary extends Component<{ fallbackText: string; resetKey: string; children: ReactNode }, MarkdownBoundaryState> {
  override state: MarkdownBoundaryState = { error: false }
  static getDerivedStateFromError(): MarkdownBoundaryState { return { error: true } }
  override componentDidUpdate(previous: { resetKey: string }) {
    if (this.state.error && previous.resetKey !== this.props.resetKey) this.setState({ error: false })
  }
  override render() {
    if (this.state.error) return <div className="chat-md chat-md-fallback">{this.props.fallbackText}</div>
    return this.props.children
  }
}

// remark-gfm and the Streamdown CJK strikethrough extension both default to
// singleTilde; both must disable it or `~text~` stops matching GFM (upstream
// disableSingleTilde).
const chatCjkPlugin: typeof cjk = {
  ...cjk,
  remarkPlugins: cjk.remarkPluginsBefore,
  remarkPluginsAfter: cjk.remarkPluginsAfter,
}
const chatPlugins = { cjk: chatCjkPlugin }
const chatLinkSafety = { enabled: false } as const

export interface MarkdownBodyProps {
  readonly text: string
  /** True only while this content is actively arriving from the stream. */
  readonly streaming: boolean
  readonly theme: ChatTheme
  readonly codeWrap?: boolean
  /** Consumer-verified external link action; absent → links render as inert
   * text. Streamdown's harden step already blocks unsafe schemes. */
  readonly onOpenLink?: (url: string) => Promise<ChatActionResult>
}

export function MarkdownBody({ text, streaming, theme, codeWrap = false, onOpenLink }: MarkdownBodyProps) {
  const mode = resolveChatMarkdownMode(streaming)
  const renderKey = buildChatMarkdownRenderKey({ theme, codeWrap })
  const components = useMemo(() => ({
    a: ({ children: linkChildren, className: linkClassName, href, node: _node }: ComponentProps<'a'> & { node?: unknown }) => {
      const resolved = typeof href === 'string' ? href : ''
      if (onOpenLink && /^https?:\/\//i.test(resolved)) {
        return <button type="button" className={`chat-md-link ${linkClassName ?? ''}`} title={resolved}
          onClick={() => { void onOpenLink(resolved) }}>{linkChildren}</button>
      }
      return <span className={`chat-md-link chat-md-link-inert ${linkClassName ?? ''}`} title={resolved || undefined}>{linkChildren}</span>
    },
    code: ({ children: codeChildren, className: codeClassName, node: _node, ...rest }: ComponentProps<'code'> & { node?: unknown; 'data-block'?: unknown }) => {
      const isBlock = 'data-block' in rest
      if (!isBlock) return <code className="chat-md-inline-code" {...rest}>{codeChildren}</code>
      const codeText = trimCodeFenceTrailingNewlines(extractCodeText(codeChildren))
      const language = codeClassName?.match(/(?:^|\s)language-([^\s]+)/)?.[1] ?? 'text'
      return <ChatCodeBlock code={codeText} language={language} theme={theme} wrap={codeWrap} highlight={!streaming} />
    },
  }), [onOpenLink, theme, codeWrap, streaming])
  return (
    <MarkdownBoundary fallbackText={text} resetKey={renderKey}>
      <Streamdown
        key={renderKey}
        className="chat-md"
        mode={mode}
        components={components}
        parseIncompleteMarkdown={streaming}
        linkSafety={chatLinkSafety}
        plugins={chatPlugins}
        animated={false}
        isAnimating={false}
      >
        {text}
      </Streamdown>
    </MarkdownBoundary>
  )
}

function extractCodeText(children: ReactNode): string {
  if (typeof children === 'string' || typeof children === 'number') return String(children)
  if (Array.isArray(children)) return children.map(extractCodeText).join('')
  if (children && typeof children === 'object' && 'props' in (children as { props?: unknown })) {
    const props = (children as { props?: { children?: ReactNode } }).props
    return extractCodeText(props?.children)
  }
  return ''
}

function trimCodeFenceTrailingNewlines(text: string): string {
  return text.replace(/\n+$/, '')
}
