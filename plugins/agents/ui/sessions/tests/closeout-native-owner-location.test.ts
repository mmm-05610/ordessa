import type { AgentConnections } from '../../contracts/src/connections'
import { expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createAgentSessions } from '../src/model'
import type { AgentClient, AgentNativeSessionOwner, AgentSnapshot } from '../../contracts/src/agent'

it('resolves the exact route while keeping frontend connection and backend channel IDs distinct', () => {
  const routeKey = 'frontend-connector-7:native-route-4'
  const owner: AgentNativeSessionOwner = {
    sessionId: routeKey,
    serverInstanceId: 'server-2',
    connectionId: 'backend-channel-22',
    nativeSessionId: 'native-route-4',
    harnessId: 'acp',
    workspaceId: '/workspace/one',
  }
  const snapshot: AgentSnapshot = {
    connection: {
      id: 'frontend-connector-7', title: 'ACP', status: 'connected', serverInstanceId: 'server-2',
      capabilities: { history: 'supported', reasoning: 'unknown', tools: 'unknown', stop: 'supported',
        interactions: 'unknown', models: 'unknown', modes: 'unknown' },
    },
    sessions: [{ id: routeKey, title: 'Conversation' }], sessionList: 'ready', messages: {}, runs: {},
    interactions: [], options: [], selectedSessionId: routeKey,
  }
  const observedRoutes: string[] = []
  const client = {
    isDisposed: false,
    getSnapshot: () => snapshot,
    nativeSessionOwner(sessionId: string) { observedRoutes.push(sessionId); return owner },
  } as unknown as AgentClient
  const workspace = {
    getSnapshot: () => ({ selectedConnectionId: 'frontend-connector-7' }),
    selected: () => client,
    subscribe: () => () => undefined,
  }
  const connections = { workspace } as unknown as AgentConnections
  const sessions = createAgentSessions(new OwnedResources(), connections)

  expect(sessions.nativeOwnerForLocation!({
    kind: 'session', sessionId: routeKey, connectionId: 'frontend-connector-7',
    serverInstanceId: 'server-2', harnessId: 'acp',
  })).toEqual(owner)
  expect(observedRoutes).toEqual([routeKey])
})
