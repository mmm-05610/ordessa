import { expect, it } from 'vitest'
import type { AgentClient } from '@extensions/ordessa.agent-contracts/contract.js'
import { loadAcpTarget } from '../fixtures/target-seam'
import type { AcpChannelHandle, AcpChannelSpec } from '../fixtures/target-seam'
import { HarnessPeer, deferred } from '../fixtures/acp-peer'

/**
 * Who is the authority for what the wire actually carries, and what a failed release is.
 *  - The reviewed seam doc names `handle.binding.normalizedPath` as the `session/new` cwd: when the
 *    project-query path and the channel-handle binding path DIVERGE, the handle wins, on new and on
 *    load alike. A handle bound to a different project is refused and stood down before any frame.
 *  - A release is three states, not one: CONFIRMED (never re-attempted), IN-FLIGHT (a concurrent
 *    caller joins the same request), and FAILED (the handle stays retryable and `releaseFailures`
 *    carries the reason — an attempt is never booked as a success). The host's half of FAILED is
 *    contractual, not incidental: `releaseFailures` and the explicit `retryReleases()` entry are
 *    typed on `AgentClient`, so the ordinary path (established channel → dispose → refused release
 *    → host observes → host retries) needs no private method and no second dispose.
 *  - Forgetting is a fourth thing, not an inference from the three: `releasesSettled` attests that
 *    the client is disposed, no acquire/initialize is still in flight, and nothing stands
 *    unconfirmed. Until it settles, an empty live view proves nothing — a late handle can still
 *    fail its release after every earlier answer has landed.
 */

const diagnostics = (client: AgentClient): { connectionId: string; reason: string }[] =>
  (client.releaseFailures ?? []).map(failure => ({ ...failure }))

/** Read the host's entry point the way the host reads it: the contract member, or the connector
 * has no retry story and the test says so. */
async function retryReleases(client: AgentClient): Promise<void> {
  if (!client.retryReleases) throw new Error('host retry entry point missing')
  await client.retryReleases()
}

async function until(what: string, predicate: () => boolean, timeoutMs = 2_000) {
  const deadline = Date.now() + timeoutMs
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`)
    await new Promise(resolve => setTimeout(resolve, 5))
  }
}

const alwaysSettled = <T>(promise: Promise<T>) =>
  promise.then(value => ({ ok: value as T | undefined, error: undefined as unknown }),
    error => ({ ok: undefined as unknown, error: error as unknown }))

function harness(target: Awaited<ReturnType<typeof loadAcpTarget>>, handle: (projectQuery: { id: string; normalizedPath: string }) => AcpChannelHandle, query: { id: string; normalizedPath: string }) {
  const spec: AcpChannelSpec = {
    serverInstanceId: 'https://harness.test|server_1',
    harness: { id: 'pi', title: 'PI Harness' },
    listProjects: async () => [query],
    openProject: async id => {
      if (id !== query.id) throw new Error(`project-invalid: ${id}`)
      return query
    },
    acquireChannel: async id => {
      if (id !== query.id) throw new Error(`project-invalid: ${id}`)
      return handle(query)
    },
  }
  return spec
}

it('the channel handle binding, not the project query, carries every cwd onto the wire (session/new and session/load)', async () => {
  const target = await loadAcpTarget()
  const peer = new HarnessPeer({ capabilities: { loadSession: true } })
  const query = { id: 'ws_app', normalizedPath: '/queried/app' }
  const bound = { id: 'ws_app', normalizedPath: '/bound/app' }
  const client = await target.createConnector(harness(target,
    () => ({ connectionId: 'chan_1', binding: bound, stream: peer.stream, release: async () => {} }), query)).connect()
  expect(await client.openWorkspace!('ws_app')).toEqual(bound)
  const { sessionId } = await client.createAndSend!('ws_app', 'ping', 'req_1')
  expect(peer.recorded('session/new')[0].params).toMatchObject({ cwd: '/bound/app' })
  await client.openSession!(sessionId)
  expect(peer.recorded('session/load')[0].params).toMatchObject({ cwd: '/bound/app' })
  client.dispose()
  peer.close()
})

it('a handle bound to a different project is stood down before any frame, and its confirmed release is never re-attempted', async () => {
  const target = await loadAcpTarget()
  const peer = new HarnessPeer()
  const released: string[] = []
  const query = { id: 'ws_app', normalizedPath: '/queried/app' }
  const client = await target.createConnector(harness(target,
    () => ({ connectionId: 'chan_x', binding: { id: 'ws_other', normalizedPath: '/other' }, stream: peer.stream,
      release: async () => { released.push('chan_x') } }), query)).connect()
  const opening = await alwaysSettled(client.openWorkspace!('ws_app'))
  expect(String(opening.error)).toMatch(/asked ws_app, bound ws_other/)
  expect(released).toEqual(['chan_x'])
  // Refused at the binding check: not one ACP frame ever crossed this stream.
  expect(peer.requests).toEqual([])
  // dispose meets the same handle again — confirmed means confirmed, no second backend call.
  client.dispose()
  expect(released).toEqual(['chan_x'])
  peer.close()
})

it('a failed release is visible and retryable: the dispose attempt fails, the handshake-path retry confirms and clears the diagnostic', async () => {
  const target = await loadAcpTarget()
  const gate = deferred()
  const peer = new HarnessPeer({ initializeGate: gate.promise })
  const releaseCalls: string[] = []
  const query = { id: 'ws_app', normalizedPath: '/repo/app' }
  const client = await target.createConnector(harness(target,
    () => ({ connectionId: 'chan_r', binding: query, stream: peer.stream,
      release: async () => { releaseCalls.push('one'); if (releaseCalls.length === 1) throw new Error('backend unreachable') } }), query)).connect()
  const opening = alwaysSettled(client.openWorkspace!('ws_app'))
  await until('initialize to reach the gate', () => peer.recorded('initialize').length === 1)
  client.dispose()
  // The in-handshake handle is dispose's to stand down; that attempt FAILS — recorded, not swallowed,
  // and the handle is not marked released.
  await until('the failed release to surface as a diagnostic', () => diagnostics(client).length === 1)
  expect(diagnostics(client)[0]).toEqual({ connectionId: 'chan_r', reason: 'backend unreachable' })
  gate.resolve()
  const opened = await opening
  expect(String(opened.error)).toMatch(/ACP connection disposed/)
  // The initialize path owns the same handle next and retries explicitly: attempt two confirms,
  // the diagnostic clears, and exactly two backend calls were ever made — no silent third.
  await until('the retry to land', () => releaseCalls.length === 2)
  expect(diagnostics(client)).toEqual([])
  expect(releaseCalls).toEqual(['one', 'one'])
  peer.close()
})

it('the ordinary established-channel path is host-visible and host-retryable: dispose-release fails, the host reads the diagnostic and the explicit entry point completes the stand-down', async () => {
  const target = await loadAcpTarget()
  const peer = new HarnessPeer()
  const releaseCalls: string[] = []
  const query = { id: 'ws_app', normalizedPath: '/repo/app' }
  const client = await target.createConnector(harness(target,
    () => ({ connectionId: 'chan_n', binding: query, stream: peer.stream,
      release: async () => { releaseCalls.push('one'); if (releaseCalls.length <= 2) throw new Error('backend unreachable') } }), query)).connect()
  // No handshake halfway through anything here: the channel is fully established, then disposed.
  await client.openWorkspace!('ws_app')
  expect(peer.recorded('initialize')).toHaveLength(1)
  client.dispose()
  await until('the failed release to surface as a diagnostic', () => diagnostics(client).length === 1)
  expect(diagnostics(client)[0]).toEqual({ connectionId: 'chan_n', reason: 'backend unreachable' })
  // The ordinary paths offer no retry: a second dispose is blocked by isDisposed, and releaseHandle
  // is private. If the host could not see and act, this whole lifecycle would be dead state.
  client.dispose()
  expect(releaseCalls).toEqual(['one'])
  // The host retries through the typed entry point; while the backend still refuses, the retry
  // REJECTS to the caller and the diagnostic stays exactly as observed.
  const refusal = await alwaysSettled(retryReleases(client))
  expect(String(refusal.error)).toMatch(/backend unreachable/)
  expect(diagnostics(client)).toEqual([{ connectionId: 'chan_n', reason: 'backend unreachable' }])
  expect(releaseCalls).toEqual(['one', 'one'])
  // Attempt three confirms: the diagnostic clears, and retrying confirmed work books no fourth call.
  await retryReleases(client)
  expect(diagnostics(client)).toEqual([])
  await retryReleases(client)
  expect(releaseCalls).toEqual(['one', 'one', 'one'])
  peer.close()
})

it('the release lifecycle is announced, not inferred: subscribeReleaseStates carries in-flight → failed → confirmed as each happens', async () => {
  const target = await loadAcpTarget()
  const peer = new HarnessPeer()
  const releaseGate = deferred()
  const events: { status: string; reason?: string }[] = []
  let releaseCalls = 0
  const query = { id: 'ws_app', normalizedPath: '/repo/app' }
  const client = await target.createConnector(harness(target,
    () => ({ connectionId: 'chan_a', binding: query, stream: peer.stream,
      release: async () => { releaseCalls++; await releaseGate.promise; if (releaseCalls === 1) throw new Error('backend unreachable') } }), query)).connect()
  if (!client.subscribeReleaseStates || !client.releaseStates) throw new Error('announced release lifecycle missing')
  const unsubscribe = client.subscribeReleaseStates(state =>
    events.push({ status: state.status, ...(state.reason === undefined ? {} : { reason: state.reason }) }))
  await client.openWorkspace!('ws_app')
  client.dispose()
  // In-flight is visible synchronously — before any answer, without reading anything: an
  // unanswered release is a STATE, so "nothing recorded" can never be mistaken for confirmed.
  expect(events).toEqual([{ status: 'in-flight' }])
  expect(client.releaseStates!()).toEqual([{ connectionId: 'chan_a', status: 'in-flight' }])
  releaseGate.resolve()
  await until('the failed announcement to land', () => events.some(event => event.status === 'failed'))
  expect(events.at(-1)).toEqual({ status: 'failed', reason: 'backend unreachable' })
  // The host's explicit retry announces its own attempt, and the confirming answer is announced
  // last — the live view is empty only because the CONFIRMED event removed the entry.
  await retryReleases(client)
  expect(events.map(event => event.status)).toEqual(['in-flight', 'failed', 'in-flight', 'confirmed'])
  expect(client.releaseStates!()).toEqual([])
  expect(releaseCalls).toBe(2)
  unsubscribe()
  peer.close()
})

it('the client attests silence only after dispose AND every stand-down is confirmed: releasesSettled stays pending across in-flight and failed releases', async () => {
  const target = await loadAcpTarget()
  const peer = new HarnessPeer()
  const releaseCalls: string[] = []
  const query = { id: 'ws_app', normalizedPath: '/repo/app' }
  const client = await target.createConnector(harness(target,
    () => ({ connectionId: 'chan_s', binding: query, stream: peer.stream,
      release: async () => { releaseCalls.push('one'); if (releaseCalls.length === 1) throw new Error('backend unreachable') } }), query)).connect()
  if (!client.releasesSettled) throw new Error('release-drain attestation missing')
  let settled = false
  void client.releasesSettled.then(() => { settled = true })
  await client.openWorkspace!('ws_app')
  client.dispose()
  await until('the failed release to surface as a diagnostic', () => diagnostics(client).length === 1)
  await new Promise(resolve => setTimeout(resolve, 20))
  // IN-FLIGHT and FAILED both keep the attestation unmade: the failed handle is a pending
  // stand-down, so "the host could forget this client" is not yet a statement the client can
  // honestly make — even though the dispose itself finished long ago.
  expect(settled).toBe(false)
  await retryReleases(client)
  await until('the drain attestation to land', () => settled)
  expect(releaseCalls).toEqual(['one', 'one'])
  peer.close()
})

it('a release already in flight is joined, not doubled: dispose and the landing handshake share one backend call', async () => {
  const target = await loadAcpTarget()
  const gate = deferred()
  const releaseGate = deferred()
  const peer = new HarnessPeer({ initializeGate: gate.promise })
  let releaseCalls = 0
  const query = { id: 'ws_app', normalizedPath: '/repo/app' }
  const client = await target.createConnector(harness(target,
    () => ({ connectionId: 'chan_c', binding: query, stream: peer.stream,
      release: async () => { releaseCalls++; await releaseGate.promise } }), query)).connect()
  let opened: unknown = 'pending'
  void alwaysSettled(client.openWorkspace!('ws_app')).then(value => { opened = value })
  await until('initialize to reach the gate', () => peer.recorded('initialize').length === 1)
  client.dispose()
  await until('the first release call to leave', () => releaseCalls === 1)
  gate.resolve()
  // The handshake lands onto the SAME handle while attempt one is still in flight: joining it is
  // the only legal move — a second backend call or a resolved open would both be a lie.
  await new Promise(resolve => setTimeout(resolve, 50))
  expect(releaseCalls).toBe(1)
  expect(opened).toBe('pending')
  releaseGate.resolve()
  await until('the joined release to settle both waiters', () => opened !== 'pending')
  expect(String((opened as { error?: unknown }).error)).toMatch(/ACP connection disposed/)
  expect(releaseCalls).toBe(1)
  expect(diagnostics(client)).toEqual([])
  peer.close()
})

/**
 * Project registration (real-Pi acceptance round 9, "ACP add project missing"): adding a
 * user-picked directory rides the Server's EXISTING workspaces.open upsert, so the connector
 * exposes `addWorkspace` exactly when orchestration supplies the op — register, re-read the
 * Server's authoritative list, and select the accepted project id (whose `normalizedPath` then
 * carries every `session/new` cwd, same handle rule as above). Where no op is supplied, the
 * member must be ABSENT so the UI can honestly disable the entry — never a faked add.
 */

function registrar(target: Awaited<ReturnType<typeof loadAcpTarget>>, withAdd: boolean) {
  const peer = new HarnessPeer()
  const projects: { id: string; normalizedPath: string }[] = [{ id: 'ws_app', normalizedPath: '/repo/app' }]
  const added: { path: string }[] = []
  const find = (id: string) => {
    const found = projects.find(item => item.id === id)
    if (!found) throw new Error(`project-invalid: ${id}`)
    return found
  }
  const spec: AcpChannelSpec = {
    serverInstanceId: 'https://harness.test|server_1',
    harness: { id: 'pi', title: 'PI Harness' },
    listProjects: async () => [...projects],
    openProject: async id => find(id),
    ...(withAdd ? {
      addProject: async (path: string) => {
        added.push({ path })
        projects.push({ id: 'ws_new', normalizedPath: path })
        return { id: 'ws_new', normalizedPath: path }
      },
    } : {}),
    acquireChannel: async id => {
      const binding = find(id)
      return { connectionId: `chan_${id}`, binding, stream: peer.stream, release: async () => {} }
    },
  }
  return { peer, spec, added }
}

it('add-workspace is offered when orchestration supplies it, and it selects the Server-accepted project', async () => {
  const target = await loadAcpTarget()
  const { peer, spec, added } = registrar(target, true)
  const client = await target.createConnector(spec).connect()
  if (!client.addWorkspace) throw new Error('addWorkspace missing while orchestration offers the op')
  const binding = await client.addWorkspace('/picked/new')
  expect(added).toEqual([{ path: '/picked/new' }])
  // The Server's answer, not the picked string, is what gets selected and listed.
  expect(binding).toEqual({ id: 'ws_new', normalizedPath: '/picked/new' })
  const snapshot = client.getSnapshot()
  expect(snapshot.workspaces?.selectedWorkspaceId).toBe('ws_new')
  expect(snapshot.workspaces?.items.map(item => item.id)).toContain('ws_new')
  // The add selects the project (a bound channel initializes once); no native session is invented.
  await until('the added project to get its bound initialize', () => peer.recorded('initialize').length === 1)
  expect(peer.recorded('session/new')).toHaveLength(0)
  client.dispose()
  peer.close()
})

it('add-workspace is absent, not faked, when orchestration offers no registration op', async () => {
  const target = await loadAcpTarget()
  const { peer, spec } = registrar(target, false)
  const client = await target.createConnector(spec).connect()
  expect(client.addWorkspace).toBeUndefined()
  // Listing and binding still work — only the ADD half is honestly missing.
  expect(await client.openWorkspace!('ws_app')).toEqual({ id: 'ws_app', normalizedPath: '/repo/app' })
  client.dispose()
  peer.close()
})
