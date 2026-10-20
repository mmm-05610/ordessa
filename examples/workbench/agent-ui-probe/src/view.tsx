import { useCallback, useSyncExternalStore } from 'react'
import { AssistantRuntimeProvider, useExternalStoreRuntime, ThreadPrimitive, MessagePrimitive, MessagePartPrimitive, ComposerPrimitive,
  type AppendMessage, type ThreadMessageLike, type ToolCallMessagePartProps } from '@assistant-ui/react'
import type { Fixture, Message } from './store'

export function convertMessage(message: Message): ThreadMessageLike {
  return {
    id: message.id, role: message.role,
    content: [
      { type: 'text', text: message.text },
      ...(message.tool ? [{ type: 'tool-call' as const, toolCallId: message.tool.id, toolName: message.tool.name,
        args: message.tool.args, argsText: JSON.stringify(message.tool.args), result: message.tool.result }] : []),
    ],
    ...(message.role === 'assistant' ? { status: message.state === 'running' ? { type: 'running' as const }
      : message.state === 'cancelled' ? { type: 'incomplete' as const, reason: 'cancelled' as const }
      : message.state === 'error' ? { type: 'incomplete' as const, reason: 'error' as const, error: '受控服务错误' }
      : { type: 'complete' as const, reason: 'stop' as const } } : {}),
  }
}
function Tool({ toolName, args, result }: ToolCallMessagePartProps) {
  return <details open data-testid="agent-tool"><summary>{toolName} · {result === undefined ? '执行中' : '已返回'}</summary>
    <pre>{JSON.stringify(args, null, 2)}</pre>{result !== undefined && <pre>{JSON.stringify(result)}</pre>}</details>
}
// Probe displays actual received snapshots, without library-added typewriter timing.
function TextPart() { return <MessagePartPrimitive.Text smooth={false} /> }
function ChatMessage() {
  return <MessagePrimitive.Root className="probe-message"><MessagePrimitive.Parts components={{ Text: TextPart, tools: { Fallback: Tool } }} /></MessagePrimitive.Root>
}
export function ConversationProbe({ fixture }: { fixture: Fixture }) {
  const state = useSyncExternalStore(fixture.subscribe, fixture.getSnapshot)
  const onNew = useCallback(async (message: AppendMessage) => {
    await fixture.begin(message.content.filter(p => p.type === 'text').map(p => p.text).join('\n'))
  }, [fixture])
  const runtime = useExternalStoreRuntime({ messages: state.messages, isRunning: state.running, convertMessage,
    onNew,
    onCancel: fixture.cancel,
  })
  return <AssistantRuntimeProvider runtime={runtime}><section className="agent-probe">
    <style>{`.agent-probe{height:100%;display:flex;flex-direction:column;gap:12px;padding:18px;box-sizing:border-box;font:14px system-ui;color:#27364a}.probe-controls{display:flex;flex-wrap:wrap;gap:8px}.agent-probe button{padding:6px 10px;border:1px solid #ccd5df;border-radius:5px;background:#fff;cursor:pointer}.agent-probe button:disabled{opacity:.45;cursor:default}.probe-thread{display:flex;flex-direction:column;min-height:0;flex:1}.probe-viewport{overflow:auto;flex:1}.probe-message{padding:12px;margin:8px 0;background:#f2f5f8;border-radius:8px;white-space:pre-wrap}.agent-probe form{display:flex;gap:8px}.agent-probe textarea{flex:1;min-height:58px;resize:vertical;border:1px solid #ccd5df;border-radius:6px;padding:10px}.agent-probe pre{overflow:auto}.probe-notice{font-size:12px;color:#66788d}`}</style>
    <strong>Agent UI 复用验证 · 受控数据，未连接服务</strong>
    <div className="probe-controls">
      <button onClick={() => fixture.switchSession('A')}>会话 A</button><button onClick={() => fixture.switchSession('B')}>会话 B</button>
      <button disabled={!state.running} onClick={() => fixture.receive(fixture.token(), { text: '第一段流式输出' })}>流式①</button>
      <button disabled={!state.running} onClick={() => fixture.receive(fixture.token(), { text: '第一段流式输出，第二段已到达' })}>流式②</button>
      <button disabled={!state.running} onClick={() => fixture.receive(fixture.token(), { tool: { id: 'tool-1', name: 'read_file', args: { path: 'README.md' } } })}>工具开始</button>
      <button disabled={!state.running} onClick={() => fixture.receive(fixture.token(), { tool: { id: 'tool-1', name: 'read_file', args: { path: 'README.md' }, result: '文件内容（模拟）' } })}>工具结果</button>
      <button disabled={!state.running} onClick={() => fixture.receive(fixture.token(), { state: 'done' })}>完成</button>
      <button disabled={!state.running} onClick={() => fixture.receive(fixture.token(), { state: 'error' })}>失败</button>
      <button onClick={() => fixture.receive(fixture.token() - 1, { text: 'STALE_EVENT_SHOULD_NOT_RENDER' })}>迟到事件</button>
    </div>
    <div data-testid="agent-state" className="probe-notice">会话 {state.session} · {state.running ? 'running' : state.messages.at(-1)?.state ?? 'idle'}</div>
    <ThreadPrimitive.Root className="probe-thread"><ThreadPrimitive.Viewport className="probe-viewport">
      <ThreadPrimitive.Messages components={{ Message: ChatMessage }} />
    </ThreadPrimitive.Viewport><ComposerPrimitive.Root>
      <ComposerPrimitive.Input placeholder="输入消息，开始受控执行" aria-label="消息" />
      <ComposerPrimitive.Send>发送</ComposerPrimitive.Send><ComposerPrimitive.Cancel>停止</ComposerPrimitive.Cancel>
    </ComposerPrimitive.Root></ThreadPrimitive.Root>
  </section></AssistantRuntimeProvider>
}
