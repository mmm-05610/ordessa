import { expect, it } from 'vitest'
import { connectTarget } from '../fixtures/target-seam'
import { deferred } from '../fixtures/acp-peer'

/**
 * Streaming, tool cards and event-routing targets R8–R13. The projection rules come from the
 * pinned schema's own discriminators (`agent_message_chunk`, `agent_thought_chunk`, `tool_call`,
 * `tool_call_update`, keyed by `toolCallId`/`messageId`) — not from an invented envelope.
 */

it('R8 streams text deltas into one assistant message and closes it at the stop reason', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  // An explicit turn-local gate, held by this test alone: the mid-flight state is observed while
  // the Harness genuinely has not answered yet — no fixture-wide latency stands in for it.
  const holdEnd = deferred()
  peer.queueTurn(async api => {
    for (const piece of ['Hel', 'lo the', ' reflow']) {
      await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { type: 'text', text: piece } })
    }
    await holdEnd.promise
    return 'end_turn'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('three chunks projected', () =>
    (client.getSnapshot().messages[sessionId] ?? []).some(m => m.text === 'Hello the reflow'))
  const streaming = (client.getSnapshot().messages[sessionId] ?? []).find(m => m.id === 'm1')
  expect(streaming?.status).toBe('running')
  // The single native message id must not split into three cards.
  expect((client.getSnapshot().messages[sessionId] ?? []).filter(m => m.id === 'm1')).toHaveLength(1)
  holdEnd.resolve()
  await prompt
  const settled = (client.getSnapshot().messages[sessionId] ?? []).find(m => m.id === 'm1')
  expect(settled?.status).toBe('completed')
  peer.close()
})

it('R9 thought chunks extend reasoning without leaking into visible text', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_thought_chunk', messageId: 'm1', content: { type: 'text', text: 'thinking…' } })
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { type: 'text', text: 'answer' } })
    return 'end_turn'
  })
  await client.send(sessionId, 'again')
  const message = (client.getSnapshot().messages[sessionId] ?? []).find(m => m.id === 'm1')
  expect(message?.reasoning).toBe('thinking…')
  expect(message?.text).toBe('answer')
  peer.close()
})

/**
 * Real-Pi acceptance (round 9): Pi streams chunks WITHOUT the optional `messageId`, and the
 * projection must accumulate them by (channel, session, current turn, content boundary) instead of
 * minting one card per chunk. The boundaries are the client's OWN typed turn lifecycle
 * (`session/prompt` start and its stopReason — ACP names no turn-start frame and the connector
 * filters nothing by string) plus tool events, which make text before and after a tool call
 * independent content.
 */

it('chunkless consecutive text fills one card while the turn is open (the per-chunk-card regression)', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  const holdEnd = deferred()
  peer.queueTurn(async api => {
    for (const piece of ['Hel', 'lo the', ' reflow']) {
      await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: piece } })
    }
    await holdEnd.promise
    return 'end_turn'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('all three pieces in one card', () =>
    (client.getSnapshot().messages[sessionId] ?? []).some(m => m.text === 'Hello the reflow'))
  const streaming = (client.getSnapshot().messages[sessionId] ?? []).filter(m => m.role === 'assistant')
  // Three wire chunks, ONE assistant card — and it is still open mid-flight.
  expect(streaming).toHaveLength(1)
  expect(streaming[0].status).toBe('running')
  holdEnd.resolve()
  await prompt
  const settled = (client.getSnapshot().messages[sessionId] ?? []).filter(m => m.role === 'assistant')
  expect(settled.map(m => m.status)).toEqual(['completed'])
  peer.close()
})

it('chunkless thought and text accumulate into the same open card, in their own fields', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_thought_chunk', content: { type: 'text', text: 'weighing ' } })
    await api.update({ sessionUpdate: 'agent_thought_chunk', content: { type: 'text', text: 'options' } })
    await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'the answer' } })
    return 'end_turn'
  })
  await client.send(sessionId, 'again')
  const assistants = (client.getSnapshot().messages[sessionId] ?? []).filter(m => m.role === 'assistant')
  expect(assistants).toHaveLength(1)
  expect(assistants[0].reasoning).toBe('weighing options')
  expect(assistants[0].text).toBe('the answer')
  peer.close()
})

it('a chunkless stream never stitches across turns or absorbs an id-bearing neighbour (counterexamples)', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'turn one' } })
    return 'end_turn'
  })
  await client.send(sessionId, 'first')
  peer.queueTurn(async api => {
    // Same turn: an id-bearing chunk opens its native card, and a following CHUNKLESS chunk must
    // not be absorbed into it — the spec says a messageId change starts a new message.
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm9', content: { type: 'text', text: 'id-part' } })
    await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'unclaimed tail' } })
    return 'end_turn'
  })
  await client.send(sessionId, 'second')
  const texts = (client.getSnapshot().messages[sessionId] ?? [])
    .filter(m => m.role === 'assistant' && !m.tools?.length).map(m => m.text)
  // Turn one's card is NOT continued by turn two, and the tail is its own card, not m9's.
  expect(texts).toEqual(['turn one', 'id-part', 'unclaimed tail'])
  expect((client.getSnapshot().messages[sessionId] ?? []).filter(m => m.id === 'm9')).toHaveLength(1)
  peer.close()
})

it('the sandwich order no-id → id → no-id within one turn yields three cards, not C appended to A', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  peer.queueTurn(async api => {
    // R10: an id-bearing chunk must also END the open chunkless stream, or the trailing chunkless
    // C would rejoin A's slot and the visible order would lose B between two parts of A.
    await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'A' } })
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'mB', content: { type: 'text', text: 'B' } })
    await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'C' } })
    return 'end_turn'
  })
  await client.send(sessionId, 'sandwich')
  const texts = (client.getSnapshot().messages[sessionId] ?? [])
    .filter(m => m.role === 'assistant' && !m.tools?.length).map(m => m.text)
  expect(texts).toEqual(['A', 'B', 'C'])
  peer.close()
})

it('a tool event closes the chunkless stream: text before and after a tool call stays independent', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'before the tool' } })
    await api.update({ sessionUpdate: 'tool_call', toolCallId: 'c1', title: 'grep', status: 'pending' })
    await api.update({ sessionUpdate: 'tool_call_update', toolCallId: 'c1', status: 'completed' })
    await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'after the tool' } })
    return 'end_turn'
  })
  await client.send(sessionId, 'again')
  const bucket = client.getSnapshot().messages[sessionId] ?? []
  const prose = bucket.filter(m => m.role === 'assistant' && !m.tools?.length).map(m => m.text)
  // Never one merged 'before the toolafter the tool' card across the tool boundary.
  expect(prose).toEqual(['before the tool', 'after the tool'])
  expect(bucket.flatMap(m => m.tools ?? []).map(t => t.id)).toEqual(['c1'])
  peer.close()
})

it('R10 tool_call and tool_call_update with one toolCallId drive one card', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'tool_call', toolCallId: 'c1', title: 'Run tests', status: 'pending' })
    await api.update({ sessionUpdate: 'tool_call_update', toolCallId: 'c1', status: 'in_progress' })
    await api.update({ sessionUpdate: 'tool_call_update', toolCallId: 'c1', status: 'completed',
      content: [{ type: 'content', content: { type: 'text', text: '3 passed' } }] })
    return 'end_turn'
  })
  await client.send(sessionId, 'again')
  const cards = (client.getSnapshot().messages[sessionId] ?? []).flatMap(m => m.tools ?? [])
  // One toolCallId, one card — three wire events, never three cards.
  const mine = cards.filter(t => t.id === 'c1')
  expect(mine).toHaveLength(1)
  expect(mine[0]).toMatchObject({ name: 'Run tests', status: 'completed' })
  expect(String(mine[0].result)).toContain('3 passed')
  peer.close()
})

it('R11 a different toolCallId opens a different card (counterexample)', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'tool_call', toolCallId: 'c1', title: 'read', status: 'pending' })
    await api.update({ sessionUpdate: 'tool_call', toolCallId: 'c2', title: 'write', status: 'pending' })
    await api.update({ sessionUpdate: 'tool_call_update', toolCallId: 'c2', status: 'failed' })
    return 'end_turn'
  })
  await client.send(sessionId, 'again')
  const cards = (client.getSnapshot().messages[sessionId] ?? []).flatMap(m => m.tools ?? [])
  expect(cards.map(t => t.id)).toEqual(['c1', 'c2'])
  expect(cards.map(t => t.status)).toEqual(['running', 'failed'])
  peer.close()
})

it('R12 a late update for another session cannot bleed into the selected one', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'text', 'req_1')
  // The Harness names an unknown session — routing must go by native sessionId, never recency.
  await peer.update('acp-session-ghost', { sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'ghost' } })
  const mine = client.getSnapshot().messages[sessionId] ?? []
  expect(mine.flatMap(m => m.text).join('')).not.toContain('ghost')
  // The ghost keeps its own bucket, which is the only place its text may appear.
  expect((client.getSnapshot().messages['acp-session-ghost'] ?? []).flatMap(m => m.text).join('')).toContain('ghost')
  peer.close()
})

it('R13 events that stop arriving never verdict a run: unknown, not cancelled, and no backend release', async () => {
  const { peer, client, released } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  peer.queueTurn(async api => { await api.cancelled(); return 'cancelled' })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('the second prompt', () => peer.recorded('session/prompt').length === 2)
  peer.drop(new Error('link reset mid-run'))
  await expect(prompt).rejects.toBeInstanceOf(Error)
  const runs = Object.values(client.getSnapshot().runs).filter(r => r.sessionId === sessionId)
  expect(runs.some(r => r.status === 'unknown')).toBe(true)
  // The distinction is the requirement: a dropped channel is not a confirmed cancel.
  expect(runs.every(r => r.status !== 'cancelled')).toBe(true)
  // And a dropped transport is not a backend release either: the connector must not pretend to
  // stand down a channel it no longer reaches — release() is an explicit lifecycle act (R24).
  expect(released).toEqual([])
  peer.close()
})
