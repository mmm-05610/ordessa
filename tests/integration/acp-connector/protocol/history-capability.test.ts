import { expect, it } from 'vitest'
import { RequestError } from '@agentclientprotocol/sdk'
import { connectTarget } from '../fixtures/target-seam'

/**
 * History targets R19–R22 and R26: LIST and LOAD are two different capabilities, tested against
 * whatever the peer actually advertises over the project-bound channel (binding a project is what
 * establishes the channel and runs the `initialize` whose answer carries these capabilities). An
 * absent capability must show as absent — the connector may not keep a parallel frontend history.
 * A failed restore is a restore the PEER refused, not one the frontend pre-vetoed: absence from
 * a list never licenses refusing `session/load` (R22 vs R26 draw that line from both sides).
 */

it('R19 without session/list the history list honestly reports it cannot read one', async () => {
  const { peer, client } = await connectTarget({ capabilities: {} })
  await client.openWorkspace!('ws_app') // the capability read exists only from this initialize answer
  await expect(client.refreshSessions()).rejects.toBeInstanceOf(Error)
  const state = client.getSnapshot()
  expect(state.sessionList).toBe('error')
  expect(state.connection.capabilities.history).toBe('unsupported')
  // No invented fallback: not one `session/list` frame left this client.
  expect(peer.recorded('session/list')).toHaveLength(0)
  peer.close()
})

it('R19b with no project bound, asking for history is a quiet no-op — not a falsely reported failure', async () => {
  // Real-Pi acceptance (round 9): selecting the connection reads projects but binds no channel
  // (U1/R19 share that rule). Refreshing history before any project is selected must not surface
  // "history failed": there is simply no Harness to ask yet, and the UI has a project gate for that.
  const { client, closeAll } = await connectTarget({ capabilities: { sessionCapabilities: { list: {} } } })
  await expect(client.refreshSessions()).resolves.toBeUndefined()
  expect(client.getSnapshot().sessionList).toBe('unknown')
  // Binding a project afterwards reaches the real list path, which can still answer honestly.
  await client.openWorkspace!('ws_app')
  await client.refreshSessions()
  expect(client.getSnapshot().sessionList).toBe('ready')
  client.dispose()
  await closeAll()
  // And a bound Harness that does not list is STILL the real error (R19), not folded away:
  const unlistable = await connectTarget({ capabilities: {} })
  await unlistable.client.openWorkspace!('ws_app')
  await expect(unlistable.client.refreshSessions()).rejects.toThrow(/does not list sessions/)
  expect(unlistable.client.getSnapshot().sessionList).toBe('error')
  unlistable.peer.close()
})

it('R20 with session/list the native titles and timestamps drive the list, and a known cwd keeps its project', async () => {
  const { peer, client } = await connectTarget({ capabilities: { loadSession: true, sessionCapabilities: { list: {} } } })
  peer.listed = [
    { sessionId: 's-old', cwd: '/repo/app', title: 'Old thread', updatedAt: '2026-09-20T00:00:00Z' },
    { sessionId: 's-new', cwd: '/repo/app', title: 'New thread', updatedAt: '2026-09-23T00:00:00Z' },
    // A cwd no authoritative binding of this Server matches stays unaffiliated — never force-bound
    // to the nearest project.
    { sessionId: 's-stray', cwd: '/mnt/elsewhere', title: 'Stray thread', updatedAt: '2026-09-21T00:00:00Z' },
  ]
  await client.openWorkspace!('ws_app') // its binding: /repo/app — the two app threads match it
  await client.refreshSessions()
  expect(peer.recorded('session/list')).toHaveLength(1)
  const state = client.getSnapshot()
  expect(state.sessionList).toBe('ready')
  expect(state.sessions).toEqual([
    { id: 's-old', title: 'Old thread', updatedAt: '2026-09-20T00:00:00Z', workspaceId: 'ws_app' },
    { id: 's-new', title: 'New thread', updatedAt: '2026-09-23T00:00:00Z', workspaceId: 'ws_app' },
    { id: 's-stray', title: 'Stray thread', updatedAt: '2026-09-21T00:00:00Z', workspaceId: undefined },
  ])
  peer.close()
})

it('R21 opening a session replays exactly what session/load streams, in order', async () => {
  const { peer, client } = await connectTarget({ capabilities: { loadSession: true, sessionCapabilities: { list: {} } } })
  peer.listed = [{ sessionId: 's-1', cwd: '/repo/app', title: 'Thread' }]
  peer.onLoadReplay('s-1', [
    { sessionUpdate: 'user_message_chunk', messageId: 'u1', content: { type: 'text', text: 'was asked' } },
    { sessionUpdate: 'agent_message_chunk', messageId: 'a1', content: { type: 'text', text: 'was answered' } },
    { sessionUpdate: 'tool_call', toolCallId: 'tc1', title: 'grep', status: 'completed' },
  ])
  await client.openWorkspace!('ws_app')
  await client.refreshSessions()
  await client.openSession('s-1')
  // The cwd is the authoritative binding, and the replay order is the peer's, untouched.
  expect(peer.recorded('session/load')[0].params).toMatchObject({ sessionId: 's-1', cwd: '/repo/app' })
  expect(client.getSnapshot().selectedSessionId).toBe('s-1')
  const messages = client.getSnapshot().messages['s-1'] ?? []
  // The native ids survive the projection; the frontend keeps no second authority for them.
  expect(messages.map(m => m.id)).toEqual(['u1', 'a1', expect.stringContaining('tc1')])
  expect(messages[0]).toMatchObject({ role: 'user', text: 'was asked' })
  expect(messages[1]).toMatchObject({ role: 'assistant', text: 'was answered' })
  expect(messages[2].tools?.[0]).toMatchObject({ id: 'tc1', status: 'completed' })
  peer.close()
})

it('R22 a restore the peer refuses on session/load surfaces as refused, never as a fake success', async () => {
  // Reviewed correction: R22 must test a REAL load failure. The peer declares loadSession; the
  // rejection comes from the wire, not from the session being missing in some list. The frontend
  // may not veto native restore capability on its own, and may not render a refused restore as
  // having succeeded.
  const { peer, client } = await connectTarget({ capabilities: { loadSession: true } })
  await client.openWorkspace!('ws_app') // channel up and initialized: load is a declared capability
  peer.armFailure('session/load', new RequestError(-32603, 'this session can not be restored'))
  const failure = await client.openSession('s-lost').catch(error => error)
  expect(failure).toBeInstanceOf(Error)
  // The connector really tried — it did not pre-refuse on its own.
  expect(peer.recorded('session/load')).toHaveLength(1)
  expect(peer.recorded('session/load')[0].params).toMatchObject({ sessionId: 's-lost', cwd: '/repo/app' })
  // No fabricated success: the session is not selected, and no content was conjured for it.
  const state = client.getSnapshot()
  expect(state.selectedSessionId ?? '').not.toBe('s-lost')
  expect(state.messages['s-lost']).toBeUndefined()
  // The honest error text is what the caller gets — the wire's own reason, not a generic one.
  expect(String(failure)).toContain('can not be restored')
  peer.close()
})

it('R26 with load but no list, restore is still legal: session/load replays without any prior listing', async () => {
  // The other side of the R22 line: a Harness that can restore but cannot list. Not being in a
  // list (here: there is no list at all) must never be taken as "cannot be restored".
  const { peer, client } = await connectTarget({ capabilities: { loadSession: true } })
  await client.openWorkspace!('ws_app')
  peer.onLoadReplay('s-remote', [
    { sessionUpdate: 'user_message_chunk', messageId: 'u9', content: { type: 'text', text: 'asked before' } },
    { sessionUpdate: 'agent_message_chunk', messageId: 'a9', content: { type: 'text', text: 'answered before' } },
  ])
  // No session/list exists here; asking for one is honestly refused...
  await expect(client.refreshSessions()).rejects.toBeInstanceOf(Error)
  // ...yet opening a known native id goes straight to session/load and renders the replay.
  await client.openSession('s-remote')
  expect(peer.recorded('session/list')).toHaveLength(0)
  expect(peer.recorded('session/load')[0].params).toMatchObject({ sessionId: 's-remote', cwd: '/repo/app' })
  const state = client.getSnapshot()
  expect(state.selectedSessionId).toBe('s-remote')
  const messages = state.messages['s-remote'] ?? []
  expect(messages.map(m => m.id)).toEqual(['u9', 'a9'])
  expect(messages.map(m => m.text)).toEqual(['asked before', 'answered before'])
  peer.close()
})
