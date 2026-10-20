import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { it, expect } from 'vitest'
import { Board } from '../frame/Board'
import { BoardStore } from '../state/store'
import { QueryClient } from '@ordessa/system-access-client'
import type { BoardSnapshot } from '../contracts/client'
// Isolated fixture, never imported by the app or normal startup.
const data: BoardSnapshot = { revision: 'test-only', scope: 'fixture', works: [{ id: 'w', title: 'TEST FIXTURE 跨目录工作', scope: 'a + b', version: 'v1', phase: 'result', status: 'Agent结束 / 未验收', change: 'test only', method: { name: '自定义方法', steps: [{ id: 'x', label: '实际绑定步骤', status: '待审核' }] }, basis: [], review: [], approval: [], execution: [], evidence: [] }], structure: [{ id: 'n', title: 'TEST FIXTURE 目标', workIds: ['w'], design: '批准', implementation: '进行中', acceptance: '未通过' }] }
;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
it('same-window detail returns to saved scroll and expansion; method is not hardcoded', async () => {
  const el = document.createElement('div'); document.body.append(el); const root = createRoot(el)
  const store = new BoardStore({ read: async () => data })
  const discovery = new QueryClient({ call: async () => ({ kind: 'Unknown', requestId: 'test', reason: 'port-absent' }) }, 'server.hello')
  await act(async () => root.render(<Board store={store} discovery={discovery}/>))
  const click = async (text: string) => { const btn = [...el.querySelectorAll('button')].find(b => b.textContent?.includes(text)); expect(btn).toBeDefined(); await act(async () => btn!.click()) }
  await click('结构'); await click('TEST FIXTURE 目标')
  const main = el.querySelector('main')!; main.scrollTop = 180
  await click('跨目录工作'); expect(el.textContent).toContain('实际绑定步骤'); expect(el.textContent).toContain('可信确认未接通'); expect(el.querySelector('main')!.scrollTop).toBe(0)
  await click('返回结构'); expect(el.querySelector('main')!.scrollTop).toBe(180); expect(el.querySelector('[aria-expanded=true]')).not.toBeNull(); expect(el.textContent).toContain('未通过')
  await act(async () => root.unmount()); el.remove()
})
it('normal empty startup shows unknown counts and unavailable authority', async () => {
  const el = document.createElement('div'); const root = createRoot(el)
  const discovery = new QueryClient({ call: async () => ({ kind: 'Unknown', requestId: 'test', reason: 'port-absent' }) }, 'server.hello')
  await act(async () => root.render(<Board store={new BoardStore()} discovery={discovery}/>))
  expect(el.textContent).toContain('数量未知'); expect(el.textContent).toContain('尚未连接'); expect(el.textContent).not.toContain('TEST FIXTURE')
  await act(async () => root.unmount())
})
