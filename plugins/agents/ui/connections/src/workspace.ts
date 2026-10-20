import type { ResourceScope } from '@ordessa/extension-api'
import { hasAwaitingInteraction, hasOpenRun, type AgentConnectionWorkspace, type AgentConnections } from '@extensions/ordessa.agent-contracts/contract.js'
import type { AgentClient, AgentReleaseState, AgentSnapshot, AgentWorkspaceSnapshot } from '@extensions/ordessa.agent-contracts/contract.js'

/** The registry-facing surface the workspace needs; satisfied by the connections service facade.
 * `release` is the Agent-side step that hands one connection's LOCAL ownership back through its
 * platform connection handle (the platform calls the endpoint's `closeLocal` at most once per
 * handle). A refused local release rejects, exactly as a throwing `client.dispose()` used to; it
 * still says nothing about the backend, which is what the release states below are for. */
type ConnectorRegistry = Pick<AgentConnections, 'getSnapshot' | 'subscribe' | 'connect'> & {
  release(id: string): Promise<void>
}

/** Connection workspace: client holding, selection, and reconnection — extracted from the
 * former sessions model (P2-1). Round-2 ruling replaces the C-0016 Q2 switch gate: a plain
 * selection change is view-only — it keeps the previous client, its open run and its pending
 * approvals alive and unanswered. Only the destructive operations (reconnect, which disposes
 * and re-hands) still refuse to proceed over an open run or an awaiting answer. */
export function createConnectionWorkspace(lifetime: ResourceScope, connections: ConnectorRegistry): AgentConnectionWorkspace {
  const clients = new Map<string, AgentClient>()
  const clientSnapshots = new Map<string, AgentSnapshot>()
  const subscriptions = new Map<string, () => void>()
  const inFlight = new Map<string, Promise<void>>()
  /** Evicted clients whose backend stand-down is not yet confirmed clean, each with the live
   * release states announced by that client and its subscription. `dispose()` is sync but the
   * release it triggers answers asynchronously, so the reference must outlive the eviction —
   * and the states are pushed to the host through `subscribeReleaseStates`, never inferred: an
   * empty record means "nothing announced yet", not "confirmed". A reference is dropped only on
   * the client's own `releasesSettled` attestation that it can never announce again — not on an
   * empty live view, which a late-acquired handle can still refill. */
  const retired = new Map<AgentClient, { states: Map<string, AgentReleaseState>; unsubscribe: () => void }>()
  const releaseCleanup = (): AgentReleaseState[] =>
    [...retired.values()].flatMap(entry => [...entry.states.values()].map(state => ({ ...state })))
  const listeners = new Set<() => void>()
  let state: AgentWorkspaceSnapshot = { available: connections.getSnapshot() }
  const publish = (patch: Partial<AgentWorkspaceSnapshot> = {}) => {
    if (lifetime.isDisposed) return
    state = { ...state, ...patch, available: connections.getSnapshot(),
      pendingReleases: releaseCleanup(),
      agent: clients.get(patch.selectedConnectionId ?? state.selectedConnectionId ?? '')?.getSnapshot() }
    for (const listener of listeners) listener()
  }
  const unsubscribeRegistry = connections.subscribe(() => publish())
  lifetime.add({ isDisposed: false, dispose() {
    unsubscribeRegistry()
    for (const unsubscribe of subscriptions.values()) unsubscribe()
    for (const entry of retired.values()) entry.unsubscribe()
    subscriptions.clear(); clientSnapshots.clear(); listeners.clear(); retired.clear()
  } })
  const connect = (id: string): Promise<void> => {
    if (!connections.getSnapshot().some(item => item.id === id)) return Promise.reject(Error(`Agent connection unavailable: ${id}`))
    if (clients.has(id)) return Promise.resolve()
    const pending = inFlight.get(id)
    if (pending) return pending
    publish({ connectingId: id, error: undefined })
    const task = connections.connect(id).then(client => {
      // No `lifetime.add(client)` here: the platform handle the facade opened owns this client's
      // LOCAL release exactly once (contract §4 — one owner for the underlying close), and that
      // handle is already bound to the service scope. Adding a second disposer would risk a second
      // `dispose()` on the same connection.
      clients.set(id, client)
      clientSnapshots.set(id, client.getSnapshot())
      subscriptions.set(id, client.subscribe(() => {
        clientSnapshots.set(id, client.getSnapshot())
        if (state.selectedConnectionId === id) publish()
      }))
      // A concurrent handshake for another id owns the indicator until it settles; clearing
      // it here would show the other connection as idle while it is still connecting.
      if (state.connectingId === id) publish({ connectingId: undefined })
      else publish()
    }).catch(error => {
      if (state.connectingId === id) publish({ connectingId: undefined, error: String(error) })
      else publish({ error: String(error) })
      throw error
    }).finally(() => { inFlight.delete(id) })
    inFlight.set(id, task)
    return task
  }
  const selected = (): AgentClient => {
    const client = clients.get(state.selectedConnectionId ?? '')
    if (!client || client.isDisposed) throw Error('No connected Agent selected')
    return client
  }
  return {
    getSnapshot: () => state,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    async selectConnection(id) {
      if (!connections.getSnapshot().some(item => item.id === id)) throw Error(`Agent connection unavailable: ${id}`)
      // Selection is view-only (round-2 ruling): no gate, no teardown of what the old client holds.
      publish({ selectedConnectionId: id, error: undefined })
      await connect(id)
      publish()
    },
    async reconnect(id) {
      if (!connections.getSnapshot().some(item => item.id === id)) throw Error(`Agent connection unavailable: ${id}`)
      // Await any pending handshake before gating: the gate must read the state the
      // teardown is about to destroy, not the state as of before that await.
      if (inFlight.has(id)) await inFlight.get(id)
      // Reconnect disposes the live client and moves the selection, so it needs the same
      // authority as selectConnection; otherwise a reconnection silently cancels an open run.
      const live = clients.get(id)
      const gated = id !== state.selectedConnectionId ? [...clientSnapshots.values()]
        : live ? [live.getSnapshot()] : []
      if (hasOpenRun(gated) || hasAwaitingInteraction(gated))
        throw Error('Agent reconnect is blocked while a run is open or an approval awaits an answer')
      subscriptions.get(id)?.(); subscriptions.delete(id)
      const evicted = clients.get(id)
      clients.delete(id); clientSnapshots.delete(id)
      // The evicted client is gone from every current-connection surface, but if it owns a managed
      // release lifecycle its stand-down may have started long before this moment. Subscribe
      // BEFORE disposing (an in-flight release is announced synchronously inside dispose()) — and
      // seed from the client's live view first: a release that already answered while the client
      // was still current is outstanding HERE, and a listener added later never rewinds.
      if (evicted?.retryReleases && evicted.subscribeReleaseStates) {
        const entry = {
          states: new Map((evicted.releaseStates?.() ?? [])
            .map(state => [state.connectionId, { ...state }] as [string, AgentReleaseState])),
          unsubscribe: () => {},
        }
        retired.set(evicted, entry)
        entry.unsubscribe = evicted.subscribeReleaseStates(state => {
          if (!retired.has(evicted)) return
          if (state.status === 'confirmed') entry.states.delete(state.connectionId)
          else entry.states.set(state.connectionId, { ...state })
          // Every announced transition re-publishes: the host's subscribers and the status bar
          // see the failure the moment it lands, without a user action forcing a refresh.
          // An EMPTY view here is not the end — a handle still being acquired by this client
          // can fail its release later — so emptiness never drops the reference.
          publish()
        })
        // Forgetting requires the client's own attestation that it can never announce again:
        // disposed, every in-flight acquire/initialize finished, every stand-down confirmed.
        // No attestation offered means nothing is provable, and the reference is kept.
        void evicted.releasesSettled?.then(() => {
          if (!retired.delete(evicted)) return
          entry.unsubscribe()
          publish()
        })
      }
      // The local release goes through the platform handle (handle.close → endpoint.closeLocal →
      // client.dispose), never a direct `dispose()` here: the platform is the single owner of the
      // underlying close and guarantees `closeLocal` runs at most once per handle. Synchronous up
      // to `dispose()`, so the in-flight announcements above are produced by this very call.
      if (evicted) await connections.release(id)
      publish({ selectedConnectionId: id })
      await connect(id)
      publish()
    },
    selected,
    clientSnapshots: () => [...clientSnapshots.values()],
    releaseCleanup,
    async retryReleaseCleanup() {
      let refusal: unknown
      // This pass only gives each retained client one further attempt; whether the reference is
      // still outstanding is answered by the client's own state notifications — an in-flight
      // attempt is joined (never doubled), a failure re-attempted, a confirmation removes the
      // entry through the subscription above. The host never infers confirmation from an
      // empty record: while a release is in flight the record is legitimately non-terminal.
      for (const client of [...retired.keys()]) {
        try { await client.retryReleases?.() }
        catch (error) { refusal ??= error }
      }
      publish()
      if (refusal !== undefined) throw refusal
    },
  }
}
