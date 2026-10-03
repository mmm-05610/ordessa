import { expect, it } from 'vitest'
import { RequestError } from '@agentclientprotocol/sdk'
import { AcpClient } from '../src/client'
import type { AcpChannelSpec } from '../src/channel'
import { HarnessPeer } from '../../../../tests/integration/acp-connector/fixtures/acp-peer'

async function fixture(refuse = false) {
  const peers: HarnessPeer[] = [], acquisitions: unknown[][] = []
  const spec: AcpChannelSpec = {
    serverInstanceId: 'server', harness: { id: 'pi', title: 'Pi' },
    listProjects: async () => [{ id: 'project', normalizedPath: '/project' }],
    openProject: async id => ({ id, normalizedPath: '/project' }),
    listSessionHistory: async () => [{ id: 'history', title: 'hello', workspaceId: 'project' }],
    acquireChannel: async (...args) => {
      acquisitions.push(args)
      const peer = new HarnessPeer({ capabilities: { loadSession: true } })
      peer.onLoadReplay('native', [
        { sessionUpdate: 'user_message_chunk', content: { type: 'text', text: 'hello' } },
        { sessionUpdate: 'agent_thought_chunk', content: { type: 'text', text: 'historical thought' } },
        { sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'historical answer' } },
      ])
      if (refuse) peer.armFailure('session/load', new RequestError(-32603, 'load refused'))
      peers.push(peer)
      return { connectionId: `channel-${peers.length}`, binding: { id: 'project', normalizedPath: '/project' },
        historySessionId: 'history', nativeSessionId: 'native', stream: peer.stream,
        release: async () => { peer.close() } }
    },
  }
  return { client: await AcpClient.connect(spec, 'connector'), spec, peers, acquisitions }
}

it('cold connect lists without launching; explicit click loads the original native target without Profile or inference', async () => {
  const f = await fixture()
  try {
    expect(f.acquisitions).toEqual([])
    expect(f.client.getSnapshot().sessions).toEqual([{ id: 'history', title: 'hello', workspaceId: 'project' }])
    await f.client.openSession('history')
    expect(f.acquisitions).toEqual([['project', 'history:history', undefined, 'history']])
    expect(f.peers[0].recorded('session/load')[0].params.sessionId).toBe('native')
    expect(f.peers[0].recorded('session/new')).toEqual([])
    expect(f.peers[0].recorded('session/prompt')).toEqual([])
    expect(f.client.getSnapshot().selectedSessionId).toBe('history')
    expect(f.client.getSnapshot().sessions).toHaveLength(1)
    expect(f.client.getSnapshot().messages.history.map(message => message.status)).not.toContain('running')
    await f.client.openSession('history')
    expect(f.peers[0].recorded('session/load')).toHaveLength(1)
    expect(f.client.getSnapshot().messages.history).toHaveLength(2)
  } finally { f.client.dispose() }
})

it('native load refusal retains history and does not select a fake restored session', async () => {
  const f = await fixture(true)
  try {
    await expect(f.client.openSession('history')).rejects.toMatchObject({ code: -32603 })
    expect(f.client.getSnapshot().selectedSessionId).toBeUndefined()
    expect(f.client.getSnapshot().sessions).toHaveLength(1)
    expect(f.peers[0].recorded('session/prompt')).toEqual([])
  } finally { f.client.dispose() }
})
