// ToolFrame + ToolSummaryRow, ported from ZCode
// packages/ui/src/ToolCallBlocks/ToolLayout.tsx and ToolSummaryRow.tsx @
// 29628c9a (Apache-2.0, see THIRD-PARTY-NOTICES.md). Ported: the compact
// "icon + kind + target + status" summary row, lazy detail mounting with the
// 300ms collapse-unmount delay, one-shot auto-open and running→completed
// auto-collapse edges, Enter/Space keyboard activation on the summary row,
// nested interactive elements never double-trigger the row toggle.
// Adapted: the upstream module-level open-state Map is now view-scoped
// (ViewExpansionState); no Tailwind/intl/diagnostics; the failure reason is
// keyboard-reachable inside the expanded detail (and via a visible copy
// action) instead of a hover-only tooltip; queued-summary animation is
// deliberately not ported (research-plan verdict).
import { memo, useEffect, useRef, useState, type ReactNode } from 'react'
import { Collapsible } from 'radix-ui'
import type { ChatToolActivityProps, ChatToolState } from '@extensions/ordessa.chat-api/contract.js'
import type { ViewExpansionState } from '../../state/expansion'
import { ExecuteOutput } from './execute-output'

const CONTENT_COLLAPSE_UNMOUNT_DELAY_MS = 300

export const toolStateLabels: Record<ChatToolState, string> = {
  running: '运行中', completed: '完成', failed: '失败', unknown: '结果未知',
}

export function ToolStateIcon({ state }: { state: ChatToolState }) {
  const shape = { width: 13, height: 13, viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, 'aria-hidden': true } as const
  if (state === 'completed') return <svg {...shape}><path d="M3 8.5l3.2 3.2L13 5" /></svg>
  if (state === 'failed') return <svg {...shape}><path d="M4.5 4.5l7 7m0-7l-7 7" /></svg>
  if (state === 'running') return <svg {...shape} className="chat-tool-spin"><circle cx="8" cy="8" r="5.4" strokeDasharray="25 9" /></svg>
  return <svg {...shape}><circle cx="8" cy="8" r="5.4" /><path d="M8 5.4v3.2M8 10.6v.6" /></svg>
}

interface ToolFrameProps {
  readonly expansionKey: string
  readonly expansion: ViewExpansionState
  readonly kindLabel: ReactNode
  readonly primaryText: ReactNode
  readonly secondaryText?: ReactNode
  readonly statusNode?: ReactNode
  readonly running?: boolean
  /** One-shot: the first time it turns true the row opens (user can close). */
  readonly autoOpen?: boolean
  /** One-shot running→completed edge collapses the row. */
  readonly autoCollapseOnComplete?: boolean
  readonly summaryAriaLabel: string
  readonly children: ReactNode
}

export const ToolFrame = memo(function ToolFrame(props: ToolFrameProps) {
  const { expansion, expansionKey } = props
  const [isOpen, setIsOpen] = useState(() => expansion.isOpen(expansionKey))
  const setExpanded = (open: boolean) => { setIsOpen(open); expansion.setOpen(expansionKey, open) }
  const [shouldRenderContent, setShouldRenderContent] = useState(isOpen)
  const contentUnmountDelay = useRef<number | null>(null)
  const hasAutoOpened = useRef(false)
  const previousRunning = useRef(props.running ?? false)
  const [synced, setSynced] = useState(false)

  // Adopt the view-owned state when the key changes (session switch remount).
  useEffect(() => {
    setIsOpen(expansion.isOpen(expansionKey))
    setSynced(true)
  }, [expansion, expansionKey])

  useEffect(() => {
    if (!props.autoOpen || hasAutoOpened.current || !synced) return
    if (props.running) {
      hasAutoOpened.current = true
      setExpanded(true)
    }
  }, [props.autoOpen, props.running, synced])

  useEffect(() => {
    const wasRunning = previousRunning.current
    previousRunning.current = props.running ?? false
    if (props.autoCollapseOnComplete && wasRunning && props.running === false) setExpanded(false)
  }, [props.autoCollapseOnComplete, props.running])

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

  return (
    <Collapsible.Root className="chat-tool" data-open={isOpen ? 'true' : 'false'} open={isOpen}
      onOpenChange={open => setExpanded(open)}>
      <Collapsible.Trigger className="chat-tool-summary" aria-label={props.summaryAriaLabel} data-testid="chat-tool-summary">
        <span className="chat-tool-chevron" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
        {props.kindLabel != null && <span className="chat-tool-kind">{props.kindLabel}</span>}
        <span className="chat-tool-primary">{props.primaryText}</span>
        {props.secondaryText != null && !isOpen && <span className="chat-tool-secondary">{props.secondaryText}</span>}
        {props.statusNode}
      </Collapsible.Trigger>
      {shouldRenderContent && (
        <Collapsible.Content className="chat-tool-content">
          {props.children}
        </Collapsible.Content>
      )}
    </Collapsible.Root>
  )
})

/** The full tool-activity row: dispatcher between the structured command
 * renderer and the generic fallback. `failed` and `unknown` never merge — a
 * failed run has a readable error, an unknown one keeps its own state word. */
export function ToolActivity({ props, conversationKey, expansion }: {
  props: ChatToolActivityProps
  conversationKey: string
  expansion: ViewExpansionState
}) {
  const expansionKey = `${conversationKey}\u0000${props.toolId}`
  const detail = (
    <div className="chat-tool-detail">
      {props.paramsText !== undefined && <pre className="chat-tool-params" data-testid="chat-tool-params">{props.paramsText}</pre>}
      {props.command
        ? <CommandToolDisplay command={props.command} running={props.state === 'running'} />
        : props.outputText !== undefined && <pre className="chat-tool-output" data-testid="chat-tool-output">{props.outputText}</pre>}
      {props.truncationNote !== undefined && <div className="chat-tool-note">{props.truncationNote}</div>}
      {props.errorText !== undefined && (
        <div className="chat-tool-error" role="status" data-testid="chat-tool-error">
          <span>{props.errorText}</span>
          <button type="button" className="chat-ghost-action" data-action="copy-error"
            onClick={() => { void navigator.clipboard?.writeText(props.errorText ?? '') }}>复制失败原因</button>
        </div>
      )}
      {props.actions?.viewFullOutput && (
        <button type="button" className="chat-ghost-action" data-action="view-full-output"
          onClick={() => { void props.actions?.viewFullOutput?.() }}>查看完整输出</button>
      )}
      {props.actions?.openRelated && (
        <button type="button" className="chat-ghost-action" data-action="open-related"
          onClick={() => { void props.actions?.openRelated?.() }}>打开关联内容</button>
      )}
    </div>
  )
  return (
    <ToolFrame expansion={expansion} expansionKey={expansionKey}
      kindLabel={props.command ? '命令' : '工具'}
      primaryText={<span className="chat-tool-title">{props.title}</span>}
      statusNode={<span className="chat-tool-state" data-state={props.state}><ToolStateIcon state={props.state} />{toolStateLabels[props.state]}</span>}
      running={props.state === 'running'}
      summaryAriaLabel={`${props.title}，${toolStateLabels[props.state]}，${'展开或收起详情'}`}>
      {detail}
    </ToolFrame>
  )
}

function CommandToolDisplay({ command, running }: {
  command: NonNullable<ChatToolActivityProps['command']>
  running: boolean
}) {
  return (
    <div className="chat-command">
      <div className="chat-command-line" data-testid="chat-command-text"><span aria-hidden="true">$ </span>{command.command}</div>
      {command.output !== undefined && (
        <ExecuteOutput text={command.output.text} running={running} exitCode={command.output.exitCode}
          truncated={command.output.truncated === true} />
      )}
    </div>
  )
}
