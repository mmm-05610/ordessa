import { expect, it } from 'vitest'
import { connectTarget, connectTargetFor } from '../fixtures/target-seam'
import { deferred } from '../fixtures/acp-peer'

/**
 * In-conversation interaction and cancellation targets R14–R18. ACP makes these reverse requests
 * (`session/request_permission`) and a bare cancel notification (`session/cancel`) followed by the
 * prompt's `stopReason` — the tests assert the connector keeps that authority instead of
 * inventing an approval backend. Option ids are deliberately NOT equal to their `kind` values
 * ('allow_once'/'reject_once'), so a connector that answers with the kind instead of the native
 * optionId — or keys an interaction by the option it carries — is caught, not flattered.
 */

const ALLOW = { optionId: 'proceed_once', name: 'Allow for this once', kind: 'allow_once' } as const
const DENY = { optionId: 'refuse_once', name: 'Reject', kind: 'reject_once' } as const

it('R14 a permission request opens a live in-thread interaction carrying the native option ids', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  let answer: any
  peer.queueTurn(async api => {
    answer = await api.permission({ toolCallId: 'c1', title: 'rm -rf cache', status: 'pending' }, [
      { ...ALLOW }, { ...DENY }])
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { type: 'text', text: 'done after approval' } })
    return 'end_turn'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('the permission request to be delivered', () => client.getSnapshot().interactions.length === 1)
  const item = client.getSnapshot().interactions[0]
  expect(item).toMatchObject({ sessionId, kind: 'approval', state: 'pending' })
  // The interaction is keyed by the native request, not by any option it happens to carry.
  expect(item.id).not.toContain('proceed_once')
  // The UI answers with the option ids the Harness itself named — never re-keyed or kind-substituted.
  expect(item.choices?.map(c => c.id)).toEqual(['proceed_once', 'refuse_once'])
  await client.respond(item.id, { kind: 'choice', choiceId: 'proceed_once' })
  await prompt
  expect(answer).toMatchObject({ outcome: { outcome: 'selected', optionId: 'proceed_once' } })
  expect(client.getSnapshot().interactions.find(i => i.id === item.id)?.state).not.toBe('pending')
  peer.close()
})

it('R15 rejecting a permission answers the native request with the native reject id', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  let answer: any
  peer.queueTurn(async api => {
    answer = await api.permission({ toolCallId: 'c1', title: 'danger', status: 'pending' }, [{ ...DENY }])
    return 'end_turn'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('the rejection prompt to arrive', () => client.getSnapshot().interactions.length === 1)
  const item = client.getSnapshot().interactions[0]
  await client.respond(item.id, { kind: 'choice', choiceId: 'refuse_once' })
  await prompt
  // The reject optionId is the native one, never the 'reject_once' kind string.
  expect(answer).toMatchObject({ outcome: { outcome: 'selected', optionId: 'refuse_once' } })
  peer.close()
})

it('R16 cancelling a pending interaction sends outcome cancelled, not a fake option', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  let answer: any
  peer.queueTurn(async api => {
    answer = await api.permission({ toolCallId: 'c1', title: 'ask', status: 'pending' }, [{ ...ALLOW }])
    return 'end_turn'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('the ask to arrive', () => client.getSnapshot().interactions.length === 1)
  const item = client.getSnapshot().interactions[0]
  await client.respond(item.id, { kind: 'cancel' })
  await prompt
  expect(answer).toMatchObject({ outcome: { outcome: 'cancelled' } })
  peer.close()
})

it('R17 a stop is confirmed only by the prompt settling with stopReason cancelled', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  // The turn reports the cancel notification received but holds its response until released:
  // "request sent" and "confirmation received" are then two observable moments, never a race.
  const holdConfirmation = deferred()
  peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { type: 'text', text: 'half a ' } })
    await api.cancelled()
    await holdConfirmation.promise
    return 'cancelled'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('the running turn', () =>
    Object.values(client.getSnapshot().runs).some(r => r.sessionId === sessionId && r.status === 'running'))
  const run = Object.values(client.getSnapshot().runs).find(r => r.sessionId === sessionId)!
  await client.stop(sessionId, run.id)
  // (A) request sent: `session/cancel` is a notification with no response, and the prompt is held
  // unconfirmed — so the only honest state right now is stop-requested, deterministically.
  await peer.waitFor('the cancel notification', () => peer.recorded('session/cancel').length === 1)
  expect(peer.recorded('session/cancel')[0].params).toEqual({ sessionId })
  await peer.waitFor('the stop request to project', () => client.getSnapshot().runs[run.id]?.status === 'stop-requested')
  expect(client.getSnapshot().runs[run.id].status).toBe('stop-requested')
  // (B) confirmation received: only the eventual stopReason decides the verdict.
  holdConfirmation.resolve()
  await prompt
  expect(client.getSnapshot().runs[run.id].status).toBe('cancelled')
  expect(peer.promptResponses.at(-1)?.stopReason).toBe('cancelled')
  peer.close()
})

it('R18 a settled interaction refuses a second answer without consuming the next pending request', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  // Two independent asks, each with its own tool call and native option id — a connector that
  // blurs one interaction into the next cannot settle both.
  const first = { toolCall: { toolCallId: 'call_first', title: 'first ask', status: 'pending' as const }, option: { optionId: 'proceed_first', name: 'Allow first', kind: 'allow_once' as const } }
  const second = { toolCall: { toolCallId: 'call_second', title: 'second ask', status: 'pending' as const }, option: { optionId: 'proceed_second', name: 'Allow second', kind: 'allow_once' as const } }
  const answers: any[] = []
  peer.queueTurn(async api => {
    answers.push(await api.permission({ ...first.toolCall }, [{ ...first.option }]))
    answers.push(await api.permission({ ...second.toolCall }, [{ ...second.option }]))
    return 'end_turn'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('the first ask', () => client.getSnapshot().interactions.length >= 1)
  const itemOne = client.getSnapshot().interactions.find(i => i.state === 'pending')!
  await client.respond(itemOne.id, { kind: 'choice', choiceId: 'proceed_first' })
  // A second answer to the settled interaction is refused...
  await expect(client.respond(itemOne.id, { kind: 'choice', choiceId: 'proceed_first' })).rejects.toBeInstanceOf(Error)
  // ...and answering the FIRST must not have consumed the SECOND: it is now on the wire, pending.
  await peer.waitFor('the second ask to surface pending', () =>
    client.getSnapshot().interactions.some(i => i.id !== itemOne.id && i.state === 'pending'))
  const itemTwo = client.getSnapshot().interactions.find(i => i.id !== itemOne.id && i.state === 'pending')!
  // Each interaction carries only its own native options: the first ask's option cannot answer it.
  await expect(client.respond(itemTwo.id, { kind: 'choice', choiceId: 'proceed_first' })).rejects.toBeInstanceOf(Error)
  await client.respond(itemTwo.id, { kind: 'choice', choiceId: 'proceed_second' })
  await prompt
  // Both native requests were honored, exactly once each, with their own option ids.
  expect(answers).toHaveLength(2)
  expect(answers[0]).toMatchObject({ outcome: { outcome: 'selected', optionId: 'proceed_first' } })
  expect(answers[1]).toMatchObject({ outcome: { outcome: 'selected', optionId: 'proceed_second' } })
  peer.close()
})

/**
 * Round 12: the stop/approval race. The real repro is 运行停在工具审批 → 点停止 → 再点同意，Agent
 * 仍继续. A stop must close its own run's approvals AT THE RESPOND ENTRY (a greyed-out button is
 * not a gate), must never pretend a given answer back, must stay visible when the cancel itself
 * fails, and must be scoped by channel/session/run ownership — nothing else loses its answer.
 */

it('R28 a stop blocks its run approval at the respond entry — the late answer reaches the agent zero times', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  const delivered: any[] = []
  const hold = deferred()
  peer.queueTurn(async api => {
    api.permission({ toolCallId: 'c1', title: 'rm -rf cache', status: 'pending' }, [{ ...ALLOW }])
      .then(answer => delivered.push(answer), () => delivered.push('wire-cancelled'))
    await api.cancelled()
    await hold.promise // hold the stop-requested window open: (A) is then observable, not a race
    return 'cancelled'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('the ask to surface', () => client.getSnapshot().interactions.some(i => i.state === 'pending'))
  const item = client.getSnapshot().interactions.find(i => i.state === 'pending')!
  await peer.waitFor('the run to be running', () =>
    Object.values(client.getSnapshot().runs).some(r => r.sessionId === sessionId && r.status === 'running'))
  const run = Object.values(client.getSnapshot().runs).find(r => r.sessionId === sessionId)!
  await client.stop(sessionId, run.id)
  // A stop request is not a cancellation confirmation: the verdict still waits for the stopReason.
  expect(client.getSnapshot().runs[run.id].status).toBe('stop-requested')
  // The approval ENTRY refuses: the run no longer accepts answers, so nothing goes out on the
  // wire and the agent never stands back up.
  await expect(client.respond(item.id, { kind: 'choice', choiceId: 'proceed_once' }))
    .rejects.toBeInstanceOf(Error)
  expect(delivered).toEqual([])
  hold.resolve()
  await prompt
  // (B) after the confirmation, same answer: zero outbound, the run verdicts cancelled.
  await expect(client.respond(item.id, { kind: 'choice', choiceId: 'proceed_once' }))
    .rejects.toBeInstanceOf(Error)
  expect(delivered).toEqual([])
  expect(client.getSnapshot().runs[run.id].status).toBe('cancelled')
  peer.close()
})

it('R29 an approval answered BEFORE the stop is delivered, never pretended back — and the stop still cancels the run', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  let answer: any
  peer.queueTurn(async api => {
    answer = await api.permission({ toolCallId: 'c1', title: 'ask', status: 'pending' }, [{ ...ALLOW }])
    await api.cancelled()
    return 'cancelled'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('the ask', () => client.getSnapshot().interactions.some(i => i.state === 'pending'))
  const item = client.getSnapshot().interactions.find(i => i.state === 'pending')!
  await client.respond(item.id, { kind: 'choice', choiceId: 'proceed_once' })
  await peer.waitFor('the answer reaching the agent', () => answer !== undefined)
  await peer.waitFor('the run to be running', () =>
    Object.values(client.getSnapshot().runs).some(r => r.sessionId === sessionId && r.status === 'running'))
  const run = Object.values(client.getSnapshot().runs).find(r => r.sessionId === sessionId)!
  await client.stop(sessionId, run.id)
  // An answer already given is a wire fact: the stop rewrites nothing and fakes no withdrawal.
  expect(client.getSnapshot().interactions.find(i => i.id === item.id)?.state).toBe('resolved')
  await peer.waitFor('the cancel on the wire', () => peer.recorded('session/cancel').length === 1)
  await prompt
  expect(client.getSnapshot().runs[run.id].status).toBe('cancelled')
  peer.close()
})

it('R30 an old approval cannot be submitted after the cancellation is confirmed', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  const delivered: any[] = []
  peer.queueTurn(async api => {
    api.permission({ toolCallId: 'c1', title: 'ask', status: 'pending' }, [{ ...ALLOW }])
      .then(answer => delivered.push(answer), () => delivered.push('wire-cancelled'))
    await api.cancelled()
    return 'cancelled'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('the ask', () => client.getSnapshot().interactions.some(i => i.state === 'pending'))
  const item = client.getSnapshot().interactions.find(i => i.state === 'pending')!
  await peer.waitFor('the run to be running', () =>
    Object.values(client.getSnapshot().runs).some(r => r.sessionId === sessionId && r.status === 'running'))
  const run = Object.values(client.getSnapshot().runs).find(r => r.sessionId === sessionId)!
  await client.stop(sessionId, run.id)
  await prompt // the stopReason lands fast here: the turn is verifiably over
  expect(client.getSnapshot().runs[run.id].status).toBe('cancelled')
  // A closed turn never leaves a submittable ask behind — not in the projection, not on the wire.
  expect(client.getSnapshot().interactions.find(i => i.id === item.id)?.state).not.toBe('pending')
  await expect(client.respond(item.id, { kind: 'choice', choiceId: 'proceed_once' })).rejects.toBeInstanceOf(Error)
  expect(delivered).toEqual([])
  peer.close()
})

it('R31 one stop closes only its own run: sibling sessions and the same-named other channel stay fully submittable', async () => {
  const { client, peerFor, closeAll } = await connectTargetFor({ projects: { ws_app: '/repo/app', ws_docs: '/repo/docs' } })
  const app = peerFor('ws_app'), docs = peerFor('ws_docs')
  const deliveredSibling: any[] = [], deliveredOtherChannel: any[] = []
  app.queueTurn(async api => {
    api.permission({ toolCallId: 'stop-me', title: 'ask on the stopped run', status: 'pending' }, [{ ...ALLOW }])
      .then(() => undefined, () => undefined) // never answered: it dies with the run
    await api.cancelled()
    return 'cancelled'
  })
  app.queueTurn(async api => {
    deliveredSibling.push(await api.permission({ toolCallId: 'sib', title: 'ask on a sibling run', status: 'pending' },
      [{ optionId: 'proceed_sibling', name: 'Allow sibling', kind: 'allow_once' }]))
    return 'end_turn'
  })
  docs.queueTurn(async api => {
    deliveredOtherChannel.push(await api.permission({ toolCallId: 'other', title: 'ask on the other channel', status: 'pending' },
      [{ optionId: 'proceed_other', name: 'Allow other', kind: 'allow_once' }]))
    return 'end_turn'
  })
  const { sessionId: stoppedId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  const siblingId = await client.newSession() // same channel, second session
  const siblingPrompt = client.send(siblingId, 'go')
  const { sessionId: otherId } = await client.createAndSend!('ws_docs', 'go', 'req_2') // same NATIVE id as stoppedId
  const askOf = (sessionKey: string) =>
    client.getSnapshot().interactions.find(i => i.sessionId === sessionKey && i.state === 'pending')
  try {
    await app.waitFor('three asks on their own sessions', () =>
      Boolean(askOf(stoppedId)) && Boolean(askOf(siblingId)) && Boolean(askOf(otherId)))
    await app.waitFor('the stopped run to be running', () =>
      Object.values(client.getSnapshot().runs).some(r => r.sessionId === stoppedId && r.status === 'running'))
    const stoppedRun = Object.values(client.getSnapshot().runs).find(r => r.sessionId === stoppedId)!
    await client.stop(stoppedId, stoppedRun.id)
    // The other two runs keep their full answer path, each with its own native option id.
    await client.respond(askOf(siblingId)!.id, { kind: 'choice', choiceId: 'proceed_sibling' })
    await client.respond(askOf(otherId)!.id, { kind: 'choice', choiceId: 'proceed_other' })
    await siblingPrompt
    await docs.waitFor('the other channel answer landing', () => deliveredOtherChannel.length === 1)
    expect(deliveredSibling[0]).toMatchObject({ outcome: { outcome: 'selected', optionId: 'proceed_sibling' } })
    expect(deliveredOtherChannel[0]).toMatchObject({ outcome: { outcome: 'selected', optionId: 'proceed_other' } })
    await app.waitFor('the stopped run settling', () => client.getSnapshot().runs[stoppedRun.id]?.status === 'cancelled')
    // Only the stopped session's channel saw a cancel, and only for the stopped session's native id.
    expect(app.recorded('session/cancel').map(c => c.params.sessionId)).toEqual(['acp-session-1'])
    expect(docs.recorded('session/cancel')).toHaveLength(0)
  } finally {
    client.dispose()
    await closeAll()
  }
})

it('R32 a stop whose wire cannot carry it fails visibly and never reopens the approval it was meant to close', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  const delivered: any[] = []
  const wireEnded: any[] = []
  peer.queueTurn(async api => {
    api.permission({ toolCallId: 'c1', title: 'ask', status: 'pending' }, [{ ...ALLOW }])
      .then(answer => delivered.push(answer), () => wireEnded.push('the request died with the link'))
    await api.cancelled()
    return 'cancelled'
  })
  const prompt = client.send(sessionId, 'again').catch(error => error)
  await peer.waitFor('the ask', () => client.getSnapshot().interactions.some(i => i.state === 'pending'))
  const item = client.getSnapshot().interactions.find(i => i.state === 'pending')!
  await peer.waitFor('the run to be running', () =>
    Object.values(client.getSnapshot().runs).some(r => r.sessionId === sessionId && r.status === 'running'))
  const run = Object.values(client.getSnapshot().runs).find(r => r.sessionId === sessionId)!
  peer.drop(new Error('link reset mid-stop'))
  // The link death verdicts the run honestly — unknown, never a fake cancelled confirmation.
  expect(await prompt).toBeInstanceOf(Error)
  await peer.waitFor('the unknown verdict', () => client.getSnapshot().runs[run.id].status === 'unknown')
  // A stop that can no longer reach the wire is a visible refusal, and it reopens nothing.
  await expect(client.stop(sessionId, run.id)).rejects.toBeInstanceOf(Error)
  await expect(client.respond(item.id, { kind: 'choice', choiceId: 'proceed_once' })).rejects.toBeInstanceOf(Error)
  // No answer ever went out: the ask only ever died with the link, never got an answer.
  expect(delivered).toEqual([])
  peer.close()
})

/**
 * Round 13: approval ownership is per RUN, not per session. `respond` must check the run that
 * RECEIVED the request — "whatever this session runs now" is a different run's answer channel.
 * An ask landing with no accepting run (its turn already settled, or a stop already requested)
 * must never open in submittable form at all.
 */

it('R36 an ask that lands after the stop never opens in answerable form', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1')
  const delivered: any[] = []
  const hold = deferred()
  peer.queueTurn(async api => {
    await api.cancelled()
    // The agent is winding down; its ask reaches the client only inside the stop-requested window.
    api.permission({ toolCallId: 'late', title: 'ask after stop', status: 'pending' }, [{ ...ALLOW }])
      .then(answer => delivered.push(answer), () => undefined)
    await hold.promise
    return 'cancelled'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor('the run to be running', () =>
    Object.values(client.getSnapshot().runs).some(r => r.sessionId === sessionId && r.status === 'running'))
  const run = Object.values(client.getSnapshot().runs).find(r => r.sessionId === sessionId)!
  await client.stop(sessionId, run.id)
  await peer.waitFor('the late ask to surface', () =>
    client.getSnapshot().interactions.some(i => i.title === 'ask after stop'))
  const item = client.getSnapshot().interactions.find(i => i.title === 'ask after stop')!
  // No run can accept this one: it is projected already-stranded, not pending.
  expect(item.state).toBe('unknown')
  await expect(client.respond(item.id, { kind: 'choice', choiceId: 'proceed_once' })).rejects.toBeInstanceOf(Error)
  hold.resolve()
  await prompt
  expect(delivered).toEqual([])
  peer.close()
})

it('R37 a late ask from turn one is never adopted by the sessions next turn', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'go', 'req_1') // turn one ends without any ask
  const deliveredLate: any[] = []
  // Turn one's agent asks late: the reverse request lands only after that prompt settled.
  peer.permission(sessionId, { toolCallId: 'stale-a', title: 'ask from turn one', status: 'pending' }, [{ ...ALLOW }])
    .then(answer => deliveredLate.push(answer), () => undefined)
  await peer.waitFor('the late ask to surface', () => client.getSnapshot().interactions.length === 1)
  const stale = client.getSnapshot().interactions[0]
  // It arrived for a settled run: never submittable, from the moment it exists.
  expect(stale.state).toBe('unknown')
  // The same session now starts turn two, with its own live, legitimately answerable ask.
  let answerB: any
  peer.queueTurn(async api => {
    answerB = await api.permission({ toolCallId: 'b', title: 'ask from turn two', status: 'pending' },
      [{ optionId: 'proceed_two', name: 'Allow two', kind: 'allow_once' }])
    return 'end_turn'
  })
  const prompt = client.send(sessionId, 'again')
  await peer.waitFor("turn two's own ask to be pending", () =>
    client.getSnapshot().interactions.some(i => i.state === 'pending'))
  // Turn two running hot does not resurrect turn one's ask: the entry checks the OWNING run.
  await expect(client.respond(stale.id, { kind: 'choice', choiceId: 'proceed_once' })).rejects.toBeInstanceOf(Error)
  expect(deliveredLate).toEqual([])
  // And the binding is not a sledgehammer: the new run's own ask answers normally.
  const live = client.getSnapshot().interactions.find(i => i.state === 'pending')!
  await client.respond(live.id, { kind: 'choice', choiceId: 'proceed_two' })
  await prompt
  expect(answerB).toMatchObject({ outcome: { outcome: 'selected', optionId: 'proceed_two' } })
  peer.close()
})
