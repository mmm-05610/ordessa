import { expect, it } from 'vitest'
import { connectTarget } from '../fixtures/target-seam'

it('explicit history initializes a dedicated scoped channel without creating or prompting a session', async () => {
  const f = await connectTarget({ capabilities: { loadSession: true, sessionCapabilities: { list: {} } } })
  try {
    f.peer.listed = [{ sessionId: 'acp-session-1', cwd: '/repo/app', title: 'Saved history' }]
    await f.client.refreshSessions()
    expect(f.acquired).toEqual([])
    await f.client.openWorkspace!('ws_app')
    expect(f.acquired).toEqual([])
    await f.client.refreshSessions()
    expect(f.acquired).toEqual(['ws_app'])
    expect(f.scopes).toEqual([expect.any(String)])
    expect(f.peer.recorded('initialize')).toHaveLength(1)
    expect(f.peer.recorded('session/new')).toHaveLength(0)
    expect(f.peer.recorded('session/prompt')).toHaveLength(0)
    await f.client.refreshSessions()
    expect(f.acquired).toEqual(['ws_app'])
    expect(f.peer.recorded('session/list')).toHaveLength(2)
    const newKey = await f.client.newSession()
    const sessionPeer = f.peerFor('ws_app', 1)
    expect(f.scopes[1]).not.toBe(f.scopes[0])
    expect(newKey).not.toBe('acp-session-1')
    await f.client.send(newKey, 'on the new session')
    expect(sessionPeer.recorded('session/prompt')).toHaveLength(1)
    expect(f.peer.recorded('session/prompt')).toHaveLength(0)
    await f.client.openSession('acp-session-1')
    expect(f.peer.recorded('session/load')).toHaveLength(1)
    expect(sessionPeer.recorded('session/load')).toHaveLength(0)
    expect(f.client.getSnapshot().sessions.find(session => session.id === 'acp-session-1')?.title).toBe('Saved history')
  } finally { f.client.dispose(); await f.closeAll() }
})

it('an explicit history acquisition retry preserves its unknown attempt scope', async () => {
  const f = await connectTarget({ capabilities: { sessionCapabilities: { list: {} } } })
  const scopes: (string | undefined)[] = []
  const original = f.spec.acquireChannel
  f.spec.acquireChannel = async (projectId, scope) => {
    scopes.push(scope)
    if (scopes.length === 1) throw new Error('history acquisition receipt lost')
    return original(projectId, scope)
  }
  try {
    await f.client.openWorkspace!('ws_app')
    await expect(f.client.refreshSessions()).rejects.toThrow('history acquisition receipt lost')
    expect(f.acquired).toEqual([])
    await f.client.refreshSessions()
    expect(scopes).toHaveLength(2)
    expect(scopes[0]).toBeTruthy()
    expect(scopes[1]).toBe(scopes[0])
    expect(f.peer.recorded('initialize')).toHaveLength(1)
    expect(f.peer.recorded('session/new')).toHaveLength(0)
    expect(f.peer.recorded('session/prompt')).toHaveLength(0)
  } finally { f.client.dispose(); await f.closeAll() }
})
