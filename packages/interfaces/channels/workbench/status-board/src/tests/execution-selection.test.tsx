import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { QueryClient } from '@ordessa/system-access-client'
import { ExecutionSelectionDetails } from '../details/execution-selection'
import { Board } from '../frame/Board'
import { BoardStore } from '../state/store'

;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true

const selection = {
  agentId: 'agent-local',
  profileRevision: {
    environmentNamespace: 'environment-local',
    profileId: 'profile-local',
    manifestRevision: 3,
    contentDigest: `sha256:${'a'.repeat(64)}`,
  },
  environmentId: 'environment-local',
  environmentProvider: 'local',
  isolation: 'none',
  sharing: false,
  harnessId: 'pi',
  provider: 'opencode',
  model: 'selected-model',
}

it('shows only validated selected runtime facts and labels none as non-sandbox', async () => {
  const element = document.createElement('div')
  const root = createRoot(element)
  await act(async () => root.render(<ExecutionSelectionDetails selection={selection}/>))
  expect(element.textContent).toContain('环境 environment-local')
  expect(element.textContent).toContain('环境提供方 local')
  expect(element.textContent).toContain('运行提供方 opencode')
  expect(element.textContent).toContain('模型 selected-model')
  expect(element.textContent).toContain('非沙箱（none）')
  expect(element.textContent).not.toContain('agent-local')
  await act(async () => root.unmount())
})

it('renders missing and malformed selection as unselected without coercion', async () => {
  const element = document.createElement('div')
  const root = createRoot(element)
  const hostile = {
    ...selection,
    environmentId: { toString: () => 'forged-selected-environment' },
  }
  await act(async () => root.render(<>
    <ExecutionSelectionDetails selection={undefined}/>
    <ExecutionSelectionDetails selection={{ ...selection, model: undefined }}/>
    <ExecutionSelectionDetails selection={hostile}/>
    <ExecutionSelectionDetails selection={{ ...selection, profileRevision: {}}}/>
    <ExecutionSelectionDetails selection={{ ...selection, profileRevision: { ...selection.profileRevision, manifestRevision: 0 }}}/>
    <ExecutionSelectionDetails selection={{ ...selection, profileRevision: { ...selection.profileRevision, manifestRevision: '3' }}}/>
    <ExecutionSelectionDetails selection={{ ...selection, profileRevision: { ...selection.profileRevision, contentDigest: 'sha256:bad' }}}/>
    <ExecutionSelectionDetails selection={['not', 'an', 'object']}/>
  </>))
  expect(element.textContent?.match(/未选择执行环境/g)).toHaveLength(8)
  expect(element.textContent).not.toContain('forged-selected-environment')
  await act(async () => root.unmount())
})

it('places the read-only execution selection in service discovery', async () => {
  const element = document.createElement('div')
  const root = createRoot(element)
  const discovery = new QueryClient({ call: async () => ({
    kind: 'Accepted' as const,
    requestId: 'selection-test',
    result: { serverId: 'server-local', capabilities: [], executionSelection: selection },
  }) }, 'server.hello')
  await act(async () => {
    root.render(<Board store={new BoardStore()} discovery={discovery}/>)
    await discovery.refresh()
  })
  expect(element.querySelector('.service')?.textContent).toContain('环境 environment-local')
  expect(element.querySelector('.service')?.textContent).toContain('模型 selected-model')
  await act(async () => root.unmount())
})
