import { expect, it } from 'vitest'
import { connectTargetFor, loadAcpTarget } from '../fixtures/target-seam'
import type { AcpChannelHandle } from '../fixtures/target-seam'
import { HarnessPeer, deferred } from '../fixtures/acp-peer'

/**
 * Switch/isolation targets R23–R27 (reviewed policy): switching the selected Server/Harness in the
 * UI is NOT the same as disposing the old connection. A switch may only be trusted to isolate —
 * state and in-flight requests of the connection being switched away from must not leak into, or
 * migrate onto, the one switched to, and must not be implicitly cancelled or answered.
 *
 * Second review round makes the three lifecycle events explicit: dropping the transport, switching
 * the view, and RELEASING the backend channel are different things. The seam hands back a managed
 * handle (connectionId + authoritative binding + stream + release()); only release() stands the
 * backend channel down. So R23/R25/R27 assert a plain switch records ZERO releases, and R24 — the
 * separate explicit-dispose case — asserts the release actually happened.
 */

async function twoHarnesses() {
  const target = await loadAcpTarget()
  const peerA = new HarnessPeer(), peerB = new HarnessPeer()
  const releasedA: string[] = [], releasedB: string[] = []
  const spec = (instance: string, peer: HarnessPeer, released: string[], project: { id: string; path: string }) => ({
    serverInstanceId: `https://harness.test|${instance}`,
    harness: { id: instance.toLowerCase(), title: instance.toUpperCase() },
    listProjects: async () => [{ id: project.id, normalizedPath: project.path }],
    openProject: async (pid: string) => {
      if (pid !== project.id) throw new Error(`project-invalid: ${pid}`)
      return { id: project.id, normalizedPath: project.path }
    },
    acquireChannel: async (pid: string): Promise<AcpChannelHandle> => {
      if (pid !== project.id) throw new Error(`project-invalid: ${pid}`)
      return {
        connectionId: `chan_${instance}`,
        binding: { id: project.id, normalizedPath: project.path },
        stream: peer.stream,
        release: async () => { released.push(pid); peer.close() },
      }
    },
  })
  const a = target.createConnector(spec('A', peerA, releasedA, { id: 'ws_a', path: '/repo/a' }))
  const b = target.createConnector(spec('B', peerB, releasedB, { id: 'ws_b', path: '/repo/b' }))
  return { peerA, peerB, releasedA, releasedB, clientA: await a.connect(), clientB: await b.connect() }
}

it('R23 two ACP clients on one renderer keep strictly separate native sessions', async () => {
  const { peerA, peerB, releasedA, releasedB, clientA, clientB } = await twoHarnesses()
  const { sessionId: sessionA } = await clientA.createAndSend!('ws_a', 'talk to A', 'req_a')
  const { sessionId: sessionB } = await clientB.createAndSend!('ws_b', 'talk to B', 'req_b')
  expect(clientA.getSnapshot().connection.serverInstanceId).not.toBe(clientB.getSnapshot().connection.serverInstanceId)
  // A's native traffic left on A's channel only, and vice versa — no shared broadcast.
  expect(peerA.recorded('session/prompt').map(p => p.params.prompt[0].text)).toEqual(['talk to A'])
  expect(peerB.recorded('session/prompt').map(p => p.params.prompt[0].text)).toEqual(['talk to B'])
  // A late A-channel update can never touch B's transcript, even under the same session-shaped id.
  await peerA.update(sessionA, { sessionUpdate: 'agent_message_chunk', messageId: 'late', content: { type: 'text', text: 'A only' } })
  expect((clientB.getSnapshot().messages[sessionB] ?? []).flatMap(m => m.text).join('')).not.toContain('A only')
  expect(clientB.getSnapshot().messages['late']).toBeUndefined()
  // Both channels live on: coexistence is not a release. Cleanup-only releases come after the asserts.
  expect(releasedA).toEqual([])
  expect(releasedB).toEqual([])
  clientA.dispose(); clientB.dispose(); peerA.close(); peerB.close()
})

it('R24 an EXPLICIT dispose releases the old connection: its backend channel is released and open work settles as unknown', async () => {
  const { peerA, peerB, releasedA, clientA } = await twoHarnesses()
  const { sessionId } = await clientA.createAndSend!('ws_a', 'go', 'req_a')
  peerA.queueTurn(async api => { await api.cancelled(); return 'cancelled' })
  const stuckPrompt = clientA.send(sessionId, 'run that never answers')
  await peerA.waitFor('the running prompt', () => peerA.recorded('session/prompt').length === 2)
  expect(releasedA).toEqual([])
  // This is the separate explicit-dispose case: the user chose to release the connection.
  clientA.dispose()
  // The release is asserted as a release — the handle's explicit release() ran, not just a
  // stream close the fixture could not tell apart from a view change. The link itself ends too.
  await peerA.waitFor('the explicit backend release', () => releasedA.length === 1)
  expect(releasedA).toEqual(['ws_a'])
  await peerA.closed
  // And the unfinished turn is neither re-issued nor migrated onward: the caller's promise rejects
  // with an unknown outcome, and the text never leaves on the other Harness's channel.
  expect(await stuckPrompt.then(() => undefined, error => error)).toBeInstanceOf(Error)
  expect(peerB.recorded('session/prompt')).toHaveLength(0)
  peerA.close(); peerB.close()
})

it('R25 switching away keeps a pending permission answerable only on its own connection, never the new one', async () => {
  const { peerA, peerB, releasedA, clientA, clientB } = await twoHarnesses()
  const { sessionId } = await clientA.createAndSend!('ws_a', 'go', 'req_a')
  peerA.queueTurn(async api => {
    await api.permission({ toolCallId: 'c1', title: 'ask on A', status: 'pending' },
      [{ optionId: 'proceed_once', name: 'Allow', kind: 'allow_once' }])
    return 'end_turn'
  })
  const prompt = clientA.send(sessionId, 'ask me')
  await peerA.waitFor('the ask', () => clientA.getSnapshot().interactions.length === 1)
  const pending = clientA.getSnapshot().interactions[0]
  // Switching away (selection moves to B): the new connection must not carry the old interaction,
  // and must refuse its id. This is isolation only — B never sees or answers A's request.
  expect(clientB.getSnapshot().interactions).toEqual([])
  await expect(clientB.respond(pending.id, { kind: 'choice', choiceId: 'proceed_once' })).rejects.toBeInstanceOf(Error)
  // Nothing of A's pending request crossed onto B's channel, and the switch released nothing:
  // A's channel is still up, still awaiting its own unanswered request.
  expect(peerB.requests.filter(r => r.method === 'session/prompt')).toHaveLength(0)
  expect(releasedA).toEqual([])
  // Only the explicit dispose below releases it (cleanup), and it must actually reach the handle.
  clientA.dispose()
  await prompt.then(() => undefined, () => undefined)
  expect(releasedA).toEqual(['ws_a'])
  peerA.close(); peerB.close()
})

it('R27 one AgentClient, two project channels, identical native session ids: messages, runs, approvals and cancels route by channel across a project switch', async () => {
  // Reviewed correction: this is NOT two Servers or two clients — same serverInstanceId, same
  // harness, ONE AgentClient, with the A and B project channels alive at once. Both fixture
  // peers number sessions from 1, so the wire really carries the same native id; a connector
  // that keys state by native id alone collides here. R23's two-client case stays as
  // connection isolation; it cannot substitute for this per-channel routing inside one client.
  // createAndSend's contract is session-created-and-first-send-accepted — it is NOT asked to
  // await the whole turn (A's turn is held by its own permission; requiring that here would
  // deadlock the test). Every fact read afterwards is therefore awaited with a bounded
  // `waitFor` — no fixed sleeps — and gates/resources are released in `finally` so a failed
  // assertion never strands a held peer turn.
  const { client, peerFor, released } = await connectTargetFor({ projects: { ws_a: '/repo/a', ws_b: '/repo/b' } })
  const peerA = peerFor('ws_a'), peerB = peerFor('ws_b')

  // A: a turn that streams, asks a permission (held by the answer), then runs until cancelled.
  let answerA: any
  const holdAfterAnswer = deferred()
  peerA.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm-A', content: { type: 'text', text: 'A is working' } })
    answerA = await api.permission({ toolCallId: 'call-A', title: 'ask on A', status: 'pending' },
      [{ optionId: 'proceed_A', name: 'Allow A', kind: 'allow_once' }])
    await api.cancelled()
    await holdAfterAnswer.promise
    return 'cancelled'
  })
  await client.openWorkspace!('ws_a')
  const { sessionId: idA } = await client.createAndSend!('ws_a', 'work in A', 'req_a')

  // B: a plain completed turn on the other project's channel.
  peerB.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm-B', content: { type: 'text', text: 'B is working' } })
    return 'end_turn'
  })
  await client.openWorkspace!('ws_b') // the project switch proper: same client, other binding
  const { sessionId: idB } = await client.createAndSend!('ws_b', 'work in B', 'req_b')
  try {
    // Wire facts first: each prompt frame must actually have arrived before it is read.
    await peerA.waitFor('the A prompt frame', () => peerA.recorded('session/prompt').length === 1)
    await peerB.waitFor('the B prompt frame', () => peerB.recorded('session/prompt').length === 1)
    const wireA = peerA.recorded('session/prompt')[0].params.sessionId
    const wireB = peerB.recorded('session/prompt')[0].params.sessionId
    expect(wireA).toBe(wireB)
    const sharedId = wireA
    expect(peerA.recorded('session/new')[0].params.cwd).toBe('/repo/a')
    expect(peerB.recorded('session/new')[0].params.cwd).toBe('/repo/b')

    // Messages: wait for each positive projection to land, only then assert non-bleed.
    const textOf = (id: string) => (client.getSnapshot().messages[id] ?? []).flatMap(m => m.text).join(' ')
    await peerA.waitFor("A's stream text projected", () => textOf(idA).includes('A is working'))
    await peerB.waitFor("B's stream text projected", () => textOf(idB).includes('B is working'))
    expect(textOf(idA)).toContain('work in A')
    expect(textOf(idB)).toContain('work in B')
    expect(textOf(idA)).not.toContain('B is working')
    expect(textOf(idB)).not.toContain('A is working')
    // An out-of-band update on A's channel naming the shared id: wait for the projection, and
    // B's bucket stays clean.
    await peerA.update(sharedId, { sessionUpdate: 'agent_message_chunk', messageId: 'msg-A2', content: { type: 'text', text: 'late on A' } })
    await peerA.waitFor("A's late update projected", () => textOf(idA).includes('late on A'))
    expect(textOf(idB)).not.toContain('late on A')

    // Runs: wait for B's terminal state, then for A's running state — same native id, two
    // independent verdicts in one client.
    const runs = () => Object.values(client.getSnapshot().runs)
    await peerB.waitFor('the B run to settle', () => runs().some(r => r.sessionId === idB &&
      ['completed', 'failed', 'cancelled', 'unknown'].includes(r.status)))
    expect(runs().some(r => r.sessionId === idB && r.status === 'completed')).toBe(true)
    await peerA.waitFor('the A run running', () => runs().some(r => r.sessionId === idA && r.status === 'running'))
    const runA = runs().find(r => r.sessionId === idA && r.status === 'running')
    expect(runA).toBeDefined()

    // Approvals: wait for A's ask to surface before reading it; it is filed under A's session.
    await peerA.waitFor('the ask projected', () => client.getSnapshot().interactions.length === 1)
    const asks = client.getSnapshot().interactions.filter(i => i.sessionId === idA)
    expect(client.getSnapshot().interactions).toHaveLength(1)
    expect(asks).toHaveLength(1)
    expect(asks[0].title).toContain('ask on A')
    await client.respond(asks[0].id, { kind: 'choice', choiceId: 'proceed_A' })
    // respond() accepting is not the peer having received it: wait for the wire answer, then
    // for the frontend's own projection of the resolution.
    await peerA.waitFor('the answer reaching A', () => answerA !== undefined)
    expect(answerA).toMatchObject({ outcome: { outcome: 'selected', optionId: 'proceed_A' } })
    await peerA.waitFor('the ask resolving in the projection', () =>
      client.getSnapshot().interactions.find(i => i.id === asks[0].id)?.state === 'resolved')

    // Cancel: stopping A's run sends session/cancel on A's channel ONLY, even though B's session
    // answers to the same native id; B's completed run is untouched.
    await client.stop(idA, runA!.id)
    await peerA.waitFor('the cancel on A', () => peerA.recorded('session/cancel').length === 1)
    expect(peerA.recorded('session/cancel')[0].params).toEqual({ sessionId: sharedId })
    holdAfterAnswer.resolve()
    await peerA.waitFor('A settles cancelled', () => runs().some(r => r.id === runA!.id && r.status === 'cancelled'))
    expect(peerB.recorded('session/cancel')).toHaveLength(0)
    expect(runs().some(r => r.sessionId === idB && r.status === 'completed')).toBe(true)

    // Switch back to A: the original A state is all still there — nothing was overwritten,
    // migrated or answered on A's behalf by the B round.
    await client.openWorkspace!('ws_a')
    expect(textOf(idA)).toContain('A is working')
    expect(textOf(idA)).toContain('late on A')
    expect(textOf(idA)).not.toContain('B is working')
    expect(textOf(idB)).toContain('B is working')
    // And none of this — two live channels, a switch, a settled run — released anything.
    expect(released).toEqual([])
  } finally {
    // Whatever failed, and wherever: the held gate goes away and both peers end.
    holdAfterAnswer.resolve()
    peerA.close(); peerB.close()
  }
})

it('stop attributes by run and session: a mismatched pair, a settled run and a disposed client cancel nothing', async () => {
  // Review round 2: the UI is not relied on to call stop correctly. The wire cancel targets a
  // session, so an unvalidated (sessionId, runId) pair flips one run's status while cancelling a
  // live turn on a different session — every wrong call must change zero state and reach zero wire.
  const { client, peerFor, closeAll } = await connectTargetFor({ projects: { ws_a: '/repo/a', ws_b: '/repo/b' } })
  const peerA = peerFor('ws_a'), peerB = peerFor('ws_b')
  peerA.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm-A', content: { type: 'text', text: 'A working' } })
    await api.cancelled(); return 'cancelled'
  })
  peerB.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm-B', content: { type: 'text', text: 'B working' } })
    await api.cancelled(); return 'cancelled'
  })
  await client.openWorkspace!('ws_a')
  const { sessionId: idA } = await client.createAndSend!('ws_a', 'work in A', 'req_a')
  await client.openWorkspace!('ws_b')
  const { sessionId: idB } = await client.createAndSend!('ws_b', 'work in B', 'req_b')
  try {
    const runs = () => client.getSnapshot().runs
    await peerA.waitFor('both runs open', () =>
      Object.values(runs()).some(r => r.sessionId === idA && r.status === 'running') &&
      Object.values(runs()).some(r => r.sessionId === idB && r.status === 'running'))
    const runA = Object.values(runs()).find(r => r.sessionId === idA)!
    const runB = Object.values(runs()).find(r => r.sessionId === idB)!

    // A's run under B's session and back: refused, both runs untouched, neither wire sees a cancel.
    await expect(client.stop(idB, runA.id)).rejects.toThrow('Agent run unavailable')
    await expect(client.stop(idA, runB.id)).rejects.toThrow('Agent run unavailable')
    expect(peerA.recorded('session/cancel')).toHaveLength(0)
    expect(peerB.recorded('session/cancel')).toHaveLength(0)
    expect(runs()[runA.id]?.status).toBe('running')
    expect(runs()[runB.id]?.status).toBe('running')

    // The matched pair still stops, and only its own session receives the cancel.
    await client.stop(idA, runA.id)
    await peerA.waitFor('the cancel on A', () => peerA.recorded('session/cancel').length === 1)
    expect(peerB.recorded('session/cancel')).toHaveLength(0)
    await peerA.waitFor('A settles', () => runs()[runA.id]?.status === 'cancelled')

    // A settled run cannot be stopped again: no second cancel reaches A's wire.
    await expect(client.stop(idA, runA.id)).rejects.toThrow('Agent run unavailable')
    expect(peerA.recorded('session/cancel')).toHaveLength(1)

    // After dispose the still-open B work is unknown, and stop reaches neither wire nor state.
    client.dispose()
    await expect(client.stop(idB, runB.id)).rejects.toThrow('disposed')
    expect(peerB.recorded('session/cancel')).toHaveLength(0)
  } finally {
    client.dispose(); closeAll()
  }
})
