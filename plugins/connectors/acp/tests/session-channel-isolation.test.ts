import { expect, it } from 'vitest'
import { RequestError } from '@agentclientprotocol/sdk'
import { AcpClient } from '../src/client'
import type { AcpChannelHandle, AcpChannelSpec } from '../src/channel'
import { deferred, HarnessPeer } from '../../../../tests/integration/acp-connector/fixtures/acp-peer'

async function fixture() {
  const binding = { id: 'project', normalizedPath: '/private/project' }
  const peers: HarnessPeer[] = []
  const handles: AcpChannelHandle[] = []
  const scopes: (string | undefined)[] = []
  const releases: string[] = []
  const spec: AcpChannelSpec = {
    serverInstanceId: 'server', harness: { id: 'pi', title: 'Pi' },
    listProjects: async () => [binding],
    openProject: async id => { if (id !== binding.id) throw new Error('project-invalid'); return binding },
    acquireChannel: async (_projectId, scope) => {
      scopes.push(scope)
      const peer = new HarnessPeer()
      let down: ((reason: string) => void) | undefined
      const handle: AcpChannelHandle = {
        connectionId: `connection-${peers.length + 1}`, binding, stream: peer.stream,
        subscribeDown: listener => { down = listener; return () => { down = undefined } },
        release: async () => { releases.push(handle.connectionId); down?.('released'); peer.close() },
      }
      peers.push(peer); handles.push(handle)
      return handle
    },
  }
  const client = await AcpClient.connect(spec, 'acp:server')
  return { client, spec, peers, handles, scopes, releases }
}

it('selects a project without acquiring a channel, then isolates new sessions and old sends', async () => {
  const f = await fixture()
  try {
    await f.client.openWorkspace('project')
    expect(f.scopes).toEqual([])
    const first = await f.client.newSession()
    const second = await f.client.newSession()
    expect(first).not.toBe(second)
    expect(f.scopes).toHaveLength(2)
    expect(f.scopes.every(scope => typeof scope === 'string' && scope.length > 0)).toBe(true)
    expect(f.scopes[0]).not.toBe(f.scopes[1])
    expect(f.peers.map(peer => peer.recorded('initialize').length)).toEqual([1, 1])
    expect(f.peers.map(peer => peer.recorded('session/new').length)).toEqual([1, 1])
    await f.client.send(first, 'old channel')
    await f.client.send(second, 'new channel')
    expect(f.peers.map(peer => peer.recorded('session/prompt').map(frame => frame.params.prompt[0].text)))
      .toEqual([['old channel'], ['new channel']])
  } finally { f.client.dispose() }
  await f.client.releasesSettled
  expect(f.releases.sort()).toEqual(['connection-1', 'connection-2'])
})

it('keeps concurrent first-send acceptance separate even when both native ids match', async () => {
  const f = await fixture()
  const gates = [deferred(), deferred()]
  const original = f.spec.acquireChannel
  f.spec.acquireChannel = async (projectId, scope) => {
    const handle = await original(projectId, scope)
    const index = f.handles.indexOf(handle)
    f.peers[index].queueTurn(async () => { await gates[index].promise; return 'end_turn' })
    return handle
  }
  try {
    let firstAccepted = false, secondAccepted = false
    const first = f.client.createAndSend('project', 'first', 'first-request').then(result => { firstAccepted = true; return result })
    const second = f.client.createAndSend('project', 'second', 'second-request').then(result => { secondAccepted = true; return result })
    void first.catch(() => undefined); void second.catch(() => undefined)
    for (let i = 0; f.peers.length < 2 || f.peers.some(peer => peer.recorded('session/prompt').length === 0); i++) {
      if (i >= 100) throw new Error('first sends did not reach peers')
      await new Promise(resolve => setTimeout(resolve, 0))
    }
    expect(firstAccepted).toBe(false); expect(secondAccepted).toBe(false)
    gates[0].resolve()
    const one = await first
    expect(secondAccepted).toBe(false)
    gates[1].resolve()
    const two = await second
    expect(one.sessionId).not.toBe(two.sessionId)
    expect(f.scopes[0]).not.toBe(f.scopes[1])
    expect(f.peers.map(peer => peer.recorded('session/prompt').length)).toEqual([1, 1])
  } finally { gates.forEach(gate => gate.resolve()); f.client.dispose() }
})

it('rejects a failed project before channel acquisition or native frames', async () => {
  const f = await fixture()
  try {
    await expect(f.client.openWorkspace('missing')).rejects.toThrow('project-invalid')
    await expect(f.client.createAndSend('missing', 'text', 'invalid-request')).rejects.toThrow('project-invalid')
    expect(f.scopes).toEqual([])
    expect(f.peers).toEqual([])
  } finally { f.client.dispose() }
})

it('releasing one same-project channel leaves the other session routable', async () => {
  const f = await fixture()
  try {
    await f.client.openWorkspace('project')
    const first = await f.client.newSession()
    const second = await f.client.newSession()
    await f.handles[0].release()
    expect(f.client.getNativeCommands(first)).toEqual({ kind: 'unknown', reason: 'channel-down' })
    expect(f.client.getNativeCommands(second)).toEqual({ kind: 'absent' })
    await f.client.send(second, 'still live')
    expect(f.peers[1].recorded('session/prompt')).toHaveLength(1)
  } finally { f.client.dispose() }
})

it('does not allocate another scope when a first-send acquisition has an unknown outcome', async () => {
  const f = await fixture()
  const observed: string[] = []
  f.spec.acquireChannel = async (_projectId, scope) => {
    observed.push(scope!)
    throw new Error('lost acquisition receipt')
  }
  try {
    await expect(f.client.createAndSend('project', 'text', 'unknown-request')).rejects.toThrow('lost acquisition receipt')
    await expect(f.client.createAndSend('project', 'text', 'unknown-request')).rejects.toThrow('outcome unknown')
    expect(observed).toHaveLength(1)
    expect(observed[0]).toBeTruthy()
  } finally { f.client.dispose() }
})

it('refuses a reused connection identity without damaging the existing native session', async () => {
  const f = await fixture()
  try {
    await f.client.openWorkspace('project')
    const first = await f.client.newSession()
    f.spec.acquireChannel = async () => f.handles[0]
    await expect(f.client.newSession()).rejects.toThrow('reused a live connection identity')
    expect(f.peers[0].recorded('initialize')).toHaveLength(1)
    expect(f.peers[0].recorded('session/new')).toHaveLength(1)
    expect(f.releases).toEqual([])
    await f.client.send(first, 'still owned')
    expect(f.peers[0].recorded('session/prompt')).toHaveLength(1)
  } finally { f.client.dispose() }
})

it('refuses a moved project binding before acquiring any channel', async () => {
  const f = await fixture()
  f.spec.openProject = async () => ({ id: 'another-project', normalizedPath: '/private/other' })
  try {
    await expect(f.client.createAndSend('project', 'text', 'moved-request')).rejects.toThrow('project binding changed')
    expect(f.scopes).toEqual([])
    expect(f.peers).toEqual([])
  } finally { f.client.dispose() }
})

for (const method of ['session/new', 'session/prompt']) {
  it(`keeps an authoritative ${method} wire refusal distinct from an unknown outcome`, async () => {
    const f = await fixture()
    const original = f.spec.acquireChannel
    f.spec.acquireChannel = async (projectId, scope) => {
      const handle = await original(projectId, scope)
      f.peers[f.handles.indexOf(handle)].armFailure(method, new RequestError(-32603, 'native refused this operation'))
      return handle
    }
    try {
      const error = await f.client.createAndSend('project', 'text', `refused-${method}`).catch(error => error)
      expect(error).toBeInstanceOf(RequestError)
      expect(error.code).not.toBe('SUBMISSION_OUTCOME_UNKNOWN')
      expect(f.peers[0].recorded('session/new')).toHaveLength(1)
      expect(f.peers[0].recorded('session/prompt')).toHaveLength(method === 'session/new' ? 0 : 1)
      if (method === 'session/prompt') expect(Object.values(f.client.getSnapshot().runs).map(run => run.status)).toEqual(['failed'])
    } finally { f.client.dispose() }
  })
}

it('marks a lost session/new receipt unknown and never starts or repeats its prompt', async () => {
  const f = await fixture()
  const original = f.spec.acquireChannel
  f.spec.acquireChannel = async (projectId, scope) => {
    const handle = await original(projectId, scope)
    const peer = f.peers[f.handles.indexOf(handle)]
    return { ...handle, stream: { ...handle.stream,
      readable: handle.stream.readable.pipeThrough(new TransformStream({
        transform(frame, controller) {
          if ((frame as { result?: { sessionId?: string } }).result?.sessionId) {
            peer.drop(new Error('new-session receipt lost'))
            throw new Error('new-session receipt lost')
          }
          controller.enqueue(frame)
        },
      })) } }
  }
  try {
    await expect(f.client.createAndSend('project', 'text', 'new-receipt-request'))
      .rejects.toMatchObject({ code: 'SUBMISSION_OUTCOME_UNKNOWN' })
    await expect(f.client.createAndSend('project', 'text', 'new-receipt-request'))
      .rejects.toMatchObject({ code: 'SUBMISSION_OUTCOME_UNKNOWN' })
    expect(f.scopes).toHaveLength(1)
    expect(f.peers[0].recorded('session/new')).toHaveLength(1)
    expect(f.peers[0].recorded('session/prompt')).toHaveLength(0)
  } finally { f.client.dispose() }
})

it('marks a lost first prompt outcome unknown while a sibling channel still sends', async () => {
  const f = await fixture()
  const hold = deferred()
  try {
    await f.client.openWorkspace('project')
    const sibling = await f.client.newSession()
    const original = f.spec.acquireChannel
    f.spec.acquireChannel = async (projectId, scope) => {
      const handle = await original(projectId, scope)
      f.peers[f.handles.indexOf(handle)].queueTurn(async () => { await hold.promise; return 'end_turn' })
      return handle
    }
    const pending = f.client.createAndSend('project', 'text', 'prompt-lost-request').catch(error => error)
    for (let i = 0; !f.peers[1]?.recorded('session/prompt').length; i++) {
      if (i >= 100) throw new Error('prompt did not reach its channel')
      await new Promise(resolve => setTimeout(resolve, 0))
    }
    f.peers[1].drop(new Error('first prompt receipt lost'))
    expect(await pending).toMatchObject({ code: 'SUBMISSION_OUTCOME_UNKNOWN' })
    expect(f.client.getSnapshot().connection.status).toBe('connected')
    await f.client.send(sibling, 'sibling survives')
    expect(f.peers[0].recorded('session/prompt')).toHaveLength(1)
    expect(f.peers[1].recorded('session/prompt')).toHaveLength(1)
  } finally { hold.resolve(); f.client.dispose() }
})

it('marks disposal during an unaccepted first prompt unknown', async () => {
  const f = await fixture()
  const hold = deferred()
  const original = f.spec.acquireChannel
  f.spec.acquireChannel = async (projectId, scope) => {
    const handle = await original(projectId, scope)
    f.peers[f.handles.indexOf(handle)].queueTurn(async () => { await hold.promise; return 'end_turn' })
    return handle
  }
  try {
    const pending = f.client.createAndSend('project', 'text', 'dispose-request').catch(error => error)
    for (let i = 0; !f.peers[0]?.recorded('session/prompt').length; i++) {
      if (i >= 100) throw new Error('prompt did not reach its channel')
      await new Promise(resolve => setTimeout(resolve, 0))
    }
    f.client.dispose()
    expect(await pending).toMatchObject({ code: 'SUBMISSION_OUTCOME_UNKNOWN' })
    expect(f.peers[0].recorded('session/prompt')).toHaveLength(1)
  } finally { hold.resolve(); f.client.dispose() }
})

it('keeps a project precondition refusal unmarked and emits zero native frames', async () => {
  const f = await fixture()
  try {
    const error = await f.client.createAndSend('missing', 'text', 'precondition-request').catch(error => error)
    expect(error).toBeInstanceOf(Error)
    expect(error.code).toBeUndefined()
    expect(f.scopes).toEqual([])
    expect(f.peers).toEqual([])
  } finally { f.client.dispose() }
})
