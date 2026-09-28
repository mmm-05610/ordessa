// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { ConversationProbe, convertMessage } from '../../../examples/agent-ui-probe/src/view'
import { createFixture } from '../../../examples/agent-ui-probe/src/store'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
Element.prototype.scrollTo = () => {}
Element.prototype.scrollIntoView = () => {}
const cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const f of cleanup.splice(0)) await f() })

it('renders external history, incremental snapshots and tool results through the real assistant-ui runtime', async () => {
  const fixture = createFixture(), node = document.createElement('div'), root = createRoot(node)
  document.body.append(node)
  cleanup.push(async () => { await act(async () => root.unmount()); fixture.dispose(); node.remove() })
  await act(async () => root.render(<ConversationProbe fixture={fixture} />))
  expect(node.textContent).toContain('恢复的历史回答')
  await act(async () => fixture.begin('读取文件'))
  const token = fixture.token()
  await act(async () => { fixture.receive(token, { text: '部分输出' }) })
  expect(node.textContent).toContain('部分输出')
  await act(async () => { fixture.receive(token, { text: '部分输出继续', tool: { id: 't', name: 'read_file', args: { path: 'README.md' } } }) })
  expect(node.querySelector('[data-testid="agent-tool"]')?.textContent).toContain('执行中')
  await act(async () => { fixture.receive(token, { tool: { id: 't', name: 'read_file', args: { path: 'README.md' }, result: '工具结果正文' } }) })
  expect(node.querySelector('[data-testid="agent-tool"]')?.textContent).toContain('工具结果正文')
  const stop = [...node.querySelectorAll('button')].find(b => b.textContent === '停止')!
  expect(stop.disabled).toBe(false)
  await act(async () => stop.click())
  expect(fixture.getSnapshot().running).toBe(false)
  expect(fixture.getSnapshot().messages.at(-1)?.state).toBe('cancelled')
  await act(async () => { expect(fixture.receive(token, { text: 'LATE' })).toBe(false) })
  expect(node.textContent).not.toContain('LATE')
  await act(async () => fixture.switchSession('B'))
  expect(node.textContent).not.toContain('部分输出继续')
  await act(async () => fixture.switchSession('A'))
  expect(node.textContent).toContain('部分输出继续')
  expect(node.textContent).toContain('恢复的历史回答')
})

it('rejects stale generations, late terminal writes and writes after disposal', async () => {
  const fixture = createFixture()
  await fixture.begin('A'); const old = fixture.token()
  fixture.switchSession('B'); await fixture.begin('B'); const current = fixture.token()
  expect(fixture.receive(old, { text: 'wrong session' })).toBe(false)
  expect(fixture.receive(current, { text: 'B response', state: 'done' })).toBe(true)
  expect(fixture.receive(current, { text: 'late' })).toBe(false)
  const snapshot = fixture.getSnapshot(); fixture.dispose(); await fixture.begin('disposed')
  expect(fixture.getSnapshot()).toBe(snapshot)
})

it('preserves complete, cancelled and error as distinct library statuses', () => {
  for (const [state, status] of [
    ['done', { type: 'complete', reason: 'stop' }],
    ['cancelled', { type: 'incomplete', reason: 'cancelled' }],
    ['error', { type: 'incomplete', reason: 'error' }],
  ] as const) expect(convertMessage({ id: 'm', role: 'assistant', text: '', state }).status).toMatchObject(status)
})
