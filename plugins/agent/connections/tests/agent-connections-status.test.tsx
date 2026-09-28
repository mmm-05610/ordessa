// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createConnections } from '../../../../packages/desktop-platform/connections/src/index'
import { createAgentConnections } from '../../../../plugins/agent/connections/src/entry'
import { ConnectionStatus } from '../../../../plugins/agent/connections/src/status'
import type { AgentClient, AgentReleaseState, AgentSnapshot } from '../../../../plugins/agent/contracts/src/contract'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

async function mount(element: ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}

const snapshotFor = (id: string): AgentSnapshot => ({
  connection: { id, title: id, status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported',
    interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
  sessions: [], sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [],
})

function liveClient(id: string, initial: AgentSnapshot): AgentClient {
  return { isDisposed: false, dispose() {}, getSnapshot: () => initial, subscribe: () => () => {},
    refreshSessions: async () => {}, newSession: async () => 's', openSession: async () => {},
    send: async () => {}, stop: async () => {}, respond: async () => {}, setOption: async () => {} }
}

/** Same announced-release lifecycle as the workspace tests, in DOM form: the backend answer
 * arrives on the notification channel only, and React must re-render because `publish()` ran —
 * no selection, no click, no forced refresh after the failure lands. */
function managedReleaseClient(id: string, outcomes: boolean[]) {
  const base = liveClient(id, snapshotFor(id))
  const connectionId = `chan_${id}`
  const ledger = new Map<string, { status: 'in-flight' | 'failed'; reason?: string }>()
  const watchers = new Set<(state: AgentReleaseState) => void>()
  const outstanding = new Map<string, Promise<void>>()
  const deferred: (() => void)[] = []
  let next = 0, confirmed = false
  const announce = (status: 'in-flight' | 'failed' | 'confirmed', reason?: string) => {
    if (status === 'confirmed') ledger.delete(connectionId)
    else ledger.set(connectionId, { status, ...(reason === undefined ? {} : { reason }) })
    const state: AgentReleaseState = { connectionId, status, ...(reason === undefined ? {} : { reason }) }
    for (const watcher of [...watchers]) watcher(state)
  }
  const startRelease = (): Promise<void> => {
    const existing = outstanding.get(connectionId)
    if (existing) return existing
    if (confirmed) return Promise.resolve()
    announce('in-flight')
    const attempt = new Promise<void>((resolve, reject) => {
      deferred.push(() => {
        const confirms = outcomes[next++] ?? true
        outstanding.delete(connectionId)
        if (confirms) { confirmed = true; announce('confirmed'); resolve() }
        else { announce('failed', 'backend unreachable'); reject(Error('backend unreachable')) }
      })
    })
    outstanding.set(connectionId, attempt)
    return attempt
  }
  const value: AgentClient = {
    ...base,
    get releaseFailures() {
      const record = ledger.get(connectionId)
      return record?.status === 'failed' ? [{ connectionId, reason: record.reason ?? '' }] : []
    },
    releaseStates: () => [...ledger].map(([id, record]) =>
      ({ connectionId: id, status: record.status, ...(record.reason === undefined ? {} : { reason: record.reason }) })),
    subscribeReleaseStates(listener) { watchers.add(listener); return () => { watchers.delete(listener) } },
    dispose() { void startRelease().catch(() => {}) },
    retryReleases: async () => { await startRelease() },
  }
  return { value, answerOne() { deferred.shift()!() } }
}

it('the status bar shows a late release failure automatically, with no selection or click after it lands', async () => {
  const registryScope = new OwnedResources(), connectorScope = new OwnedResources()
  const evicted = managedReleaseClient('acp', [false])
  const current = liveClient('acp', snapshotFor('acp'))
  let connects = 0
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'acp', title: 'ACP', connect: async () => (++connects === 1 ? evicted.value : current) })
  const workspace = registry.workspace
  await act(async () => { await workspace.selectConnection('acp') })
  const container = await mount(<ConnectionStatus workspace={workspace} />)
  // Open the popover before the failure exists; nothing else touches the UI afterwards.
  const toggle = container.querySelector('.conn-status-toggle') as HTMLButtonElement
  await act(async () => { toggle.click() })
  await act(async () => { await workspace.reconnect('acp') })
  expect(container.textContent).toContain('in-flight')
  // The refusal arrives after the reconnect completed, with no further user action at all:
  // the client's announcement re-publishes the workspace, and the store notification renders it.
  await act(async () => { evicted.answerOne() })
  expect(container.textContent).toContain('chan_acp: backend unreachable')
  expect(container.querySelector('[role="alert"]')).not.toBeNull()
  expect(container.textContent).toContain('Retry backend release')
  registryScope.dispose(); connectorScope.dispose()
})
