import type { ResourceScope } from '@ordessa/extension-api'
import type {
  AgentAttachmentPreparation, AgentClient, AgentCommandCatalog, AgentConnections, AgentPreparedAttachment,
  AgentSessions, AgentSnapshot, AgentSubmissionOutcome, AgentWorkspaceSnapshot,
} from '@extensions/ordessa.agent-contracts/contract.js'

/** Thin delegate facade: client holding, selection, and reconnection live in the connections
 * service workspace (P2-1 extraction); session operations project through its selected client.
 * CP-SESSION-001 (FC-0021): the draft and the per-Server project gate are owned here —
 * New session never reaches a client, and first send goes through createAndSend with one
 * requestId held until accepted. */
export function createAgentSessions(lifetime: ResourceScope, connections: AgentConnections): AgentSessions {
  void lifetime // workspace ownership moved to the connections service scope (P2-1)
  const workspace = connections.workspace
  interface ConnState { draftActive: boolean; draftEndedBy?: 'discarded' | 'opened'; requestId?: string; restoreFailed: boolean }
  const states = new Map<string, ConnState>()
  const stateFor = (id: string) => { let s = states.get(id); if (!s) states.set(id, s = { draftActive: false, restoreFailed: false }); return s }
  // Non-secret UI selection: last valid project per authenticated Server instance (origin+serverId),
  // mirrored to renderer localStorage so the choice survives a desktop restart (FC-0030). Never keyed
  // by plugin id or bare origin; without identity there is no restore path at all.
  const lastProject = new Map<string, string>()
  // Prepared attachments owned through the selected connection (R-Z2-2 plugin
  // half): the registry maps the opaque token Chat carries to the full
  // prepared reference plus the session it was prepared against, and an entry
  // exists only while the port still owns the content. Keys are
  // connection-scoped — a reference prepared on one connection is never
  // resolvable on another.
  const preparedAttachments = new Map<string, { reference: AgentPreparedAttachment; sessionId: string }>()
  const preparedKey = (connectionId: string, preparedId: string) => `${connectionId}|${preparedId}`
  const linkDownOf = (client: AgentClient) => {
    const status = client.getSnapshot().connection.status
    return status === 'disconnected' || status === 'error'
  }
  const storageKey = (identity: string) => `ordessa.agent.project.${identity}`
  const rememberProject = (identity: string, id: string) => {
    lastProject.set(identity, id)
    try { globalThis.localStorage?.setItem(storageKey(identity), id) } catch { /* the gate revalidates on open regardless */ }
  }
  const forgetProject = (identity: string) => {
    lastProject.delete(identity)
    try { globalThis.localStorage?.removeItem(storageKey(identity)) } catch { /* best effort */ }
  }
  const recallProject = (identity: string) => {
    const remembered = lastProject.get(identity)
    if (remembered) return remembered
    try {
      const stored = globalThis.localStorage?.getItem(storageKey(identity))
      if (stored) { lastProject.set(identity, stored); return stored }
    } catch { /* storage unavailable: manual selection only */ }
    return undefined
  }
  const identityOf = (client: AgentClient) => client.getSnapshot().connection.serverInstanceId
  const supported = (agent: AgentSnapshot | undefined) => agent?.connection.capabilities.workspaces === 'supported'

  async function revalidate(connectionId: string) {
    const state = stateFor(connectionId)
    state.restoreFailed = false
    let client: AgentClient
    try { client = workspace.selected() } catch { return }
    if (!client.openWorkspace || !supported(client.getSnapshot())) return
    const identity = identityOf(client)
    if (!identity) return // no authenticated instance identity: require a manual selection, never a stale unlock
    const snapshot = client.getSnapshot()
    const saved = recallProject(identity)
    if (!saved) {
      const current = snapshot.workspaces?.selectedWorkspaceId
      if (current) rememberProject(identity, current)
      return
    }
    // The stored id must still be listed unarchived by this Server before it may be opened (FC-0030).
    if (snapshot.workspaces?.state === 'ready' && !snapshot.workspaces.items.some(item => item.id === saved)) {
      state.restoreFailed = true; forgetProject(identity)
      return
    }
    try { await client.openWorkspace(saved) }
    catch { state.restoreFailed = true; forgetProject(identity) } // invalid: clear the record and block sends
  }

  const listeners = new Set<() => void>()
  workspace.subscribe(notify)
  function notify() { cached = null; for (const listener of [...listeners]) listener() }

  let cached: { base: AgentWorkspaceSnapshot; signature: string; derived: AgentWorkspaceSnapshot } | null = null
  const signature = (base: AgentWorkspaceSnapshot) => {
    const state = base.selectedConnectionId ? stateFor(base.selectedConnectionId) : undefined
    return `${base.selectedConnectionId ?? '-'}|${state?.draftActive}|${state?.draftEndedBy}|${state?.restoreFailed}|${base.agent?.connection.capabilities.workspaces}|${base.agent?.workspaces?.selectedWorkspaceId}|${observedGeneration() ?? '-'}`
  }
  /** PC-5: the selected client's backend-confirmed runtime generation, when it
   * can observe one. An absent client member or no selection is itself the
   * evidence answer: no generation is invented from UI counters. */
  const observedGeneration = (): number | undefined => {
    try { return workspace.selected().admissionEvidence?.()?.runtimeGeneration } catch { return undefined }
  }
  function derive(base: AgentWorkspaceSnapshot): AgentWorkspaceSnapshot {
    if (!base.selectedConnectionId) return base
    const state = stateFor(base.selectedConnectionId)
    const block = !supported(base.agent) ? 'unsupported' as const
      : state.restoreFailed ? 'project-invalid' as const
      : !base.agent?.workspaces?.selectedWorkspaceId ? 'no-project' as const : undefined
    const generation = observedGeneration()
    return { ...base, ...(generation === undefined ? {} : { runtimeGeneration: generation }), draft: {
      active: state.draftActive,
      workspaceId: base.agent?.workspaces?.selectedWorkspaceId,
      canSend: block === undefined,
      ...(block ? { blockReason: block } : {}),
      ...(state.draftEndedBy ? { endedBy: state.draftEndedBy } : {}),
    } }
  }
  const gate = () => {
    const snapshot = derive(workspace.getSnapshot())
    if (!snapshot.draft?.canSend) throw Error(`Agent project gate: ${snapshot.draft?.blockReason ?? 'closed'}`)
    return snapshot
  }

  return {
    getSnapshot: () => {
      const base = workspace.getSnapshot()
      const next = signature(base)
      if (cached && cached.base === base && cached.signature === next) return cached.derived
      cached = { base, signature: next, derived: derive(base) }
      return cached.derived
    },
    subscribe: listener => { listeners.add(listener); return () => { listeners.delete(listener) } },
    selectConnection: async id => { await workspace.selectConnection(id); await revalidate(id) },
    reconnect: async id => { await workspace.reconnect(id); await revalidate(id) },
    refreshSessions: () => workspace.selected().refreshSessions(),
    // Legacy passthrough kept type-compatible for the direct prototypes; the CP UI never calls it (FC-0021).
    newSession: () => workspace.selected().newSession().then(() => undefined),
    openSession: id => {
      const connId = workspace.getSnapshot().selectedConnectionId
      const state = connId ? stateFor(connId) : undefined
      // Opening a session ends an active draft as a step-away (C-0030): the draft may be
      // resumed by a later startDraft with its own semantics; nothing is sent on this path.
      if (state?.draftActive) { state.draftActive = false; state.draftEndedBy = 'opened' }
      return workspace.selected().openSession(id)
    },
    send: async (text, attachments?) => {
      const client = workspace.selected()
      const connectionId = workspace.getSnapshot().selectedConnectionId ?? '-'
      const state = stateFor(connectionId)
      // C-0030: while a draft is active its send is exactly one createAndSend — a previously
      // selected session must never capture the draft's first text. Continuation only applies
      // outside a draft, and keeps that session's own bound project.
      if (!state.draftActive) {
        const sessionId = client.getSnapshot().selectedSessionId
        if (!sessionId) throw Error('No Agent session selected')
        // Fail-closed admission precheck (014 P-C PC-4): a client that can
        // observe the backend admission facts and reports them not-ready
        // refuses BEFORE any wire traffic — the same discipline as the
        // Server's controlled next-submit coordinator. A client with no
        // observable admission evidence cannot fail closed here; its outcome
        // is the legacy send mapping below (registered limitation, S-05).
        const evidence = client.admissionEvidence?.()
        if (evidence) {
          if (!evidence.admissionSupported || !evidence.q5Ready || !evidence.chatApiReady)
            return { kind: 'refused', code: 'CAPABILITY_UNSUPPORTED', reason: 'ACP backend admission dependencies are unavailable' }
          if (evidence.outputInProgress)
            return { kind: 'refused', code: 'BUSY', reason: 'ACP output is still in progress' }
        }
        if (attachments?.length) {
          if (!client.submitWithAttachments)
            return { kind: 'refused', code: 'CAPABILITY_UNSUPPORTED', reason: 'attachment carry path is unavailable on this connection' }
          const refs: AgentPreparedAttachment[] = []
          for (const token of attachments) {
            const entry = preparedAttachments.get(preparedKey(connectionId, token))
            if (!entry) return { kind: 'refused', code: 'INVALID_REQUEST', reason: 'unknown prepared attachment reference' }
            refs.push(entry.reference)
          }
          try {
            return await client.submitWithAttachments(sessionId, text, refs)
          } catch (cause) {
            if (linkDownOf(client)) return { kind: 'unknown', operationId: globalThis.crypto.randomUUID(),
              reason: cause instanceof Error ? cause.message : String(cause) }
            return { kind: 'refused', code: 'SUBMISSION_REFUSED', reason: cause instanceof Error ? cause.message : String(cause) }
          }
        }
        const outcome = await client.send(sessionId, text).catch((cause: unknown) => {
          // Typed mapping of the legacy path (contracts 0.2.0): evidenced
          // channel loss is unknown — never a fake acceptance; anything else
          // the client refuses arrives as a typed refusal with its reason.
          if (linkDownOf(client)) return { kind: 'unknown' as const, operationId: globalThis.crypto.randomUUID(),
            reason: cause instanceof Error ? cause.message : String(cause) }
          return { kind: 'refused' as const, code: 'SUBMISSION_REFUSED',
            reason: cause instanceof Error ? cause.message : String(cause) }
        })
        // Compatibility rule (contracts 0.2.0): a legacy connector resolves with
        // void — exactly the old send-path acceptance, never execution success.
        return outcome ?? { kind: 'accepted' }
      }
      if (attachments?.length)
        return { kind: 'refused', code: 'CAPABILITY_UNSUPPORTED', reason: 'a draft first send cannot carry prepared attachments' }
      gate() // first send is blocked without a revalidated project — never falls back
      if (!client.createAndSend) throw Error('Agent project gate: unsupported')
      const workspaceId = client.getSnapshot().workspaces?.selectedWorkspaceId!
      state.requestId ??= globalThis.crypto.randomUUID() // one requestId held across unknown outcomes; no blind second create
      const requestId = state.requestId
      try {
        const accepted = await client.createAndSend(workspaceId, text, requestId)
        // The draft ends only when the accepted real session id is in the snapshot, selected, and bound
        // to the chosen project (FC-0031); otherwise input and requestId stay held for an idempotent retry.
        const after = client.getSnapshot()
        const session = after.sessions.find(item => item.id === accepted?.sessionId)
        const project = after.workspaces?.items.find(item => item.id === workspaceId)
        const bound = !!session?.workspaceId
          && (session.workspaceId === workspaceId || session.workspaceId === project?.normalizedPath)
        if (!accepted?.sessionId || !bound || after.selectedSessionId !== accepted.sessionId)
          throw Error('Agent first-send session mismatch')
        state.requestId = undefined
        state.draftActive = false
        state.draftEndedBy = undefined // an accepted send ends the draft by selecting the new real session
        notify()
        return { kind: 'accepted' }
      } catch (cause) {
        notify()
        // The requestId stays held on anything but acceptance: an unknown
        // outcome keeps it for reconciliation, a refusal keeps it so the user's
        // explicit retry re-uses the same idempotency identity (C-0030/R-Z2-1).
        if (linkDownOf(client)) return { kind: 'unknown', operationId: requestId,
          reason: cause instanceof Error ? cause.message : String(cause) }
        return { kind: 'refused', code: 'SUBMISSION_REFUSED', reason: cause instanceof Error ? cause.message : String(cause) }
      }
    },
    commandCatalog: sessionKey => {
      let client: AgentClient
      try { client = workspace.selected() } catch { return { kind: 'absent' } }
      const catalog = client.getNativeCommands?.(sessionKey)
      if (!catalog) return { kind: 'absent' } // the connector projects no native catalog
      switch (catalog.kind) {
        case 'available': return catalog
        case 'absent': return { kind: 'absent' }
        case 'unknown': return { kind: 'error', reason: catalog.reason }
      }
    },
    attachments: (() => {
      const capability = (sessionId?: string) => {
        let client: AgentClient
        try { client = workspace.selected() } catch
          { return { kind: 'absent' as const, reason: '没有已连接的代理，附件不可用。' } }
        // All-or-nothing: preparation without the carry path would strand
        // content that can never be sent, so partial surfaces stay absent.
        if (!client.prepareAttachment || !client.attachmentCapabilities
          || !client.releasePreparedAttachment || !client.submitWithAttachments)
          return { kind: 'absent' as const, reason: '当前连接未提供附件传输通道（生产 prepare owner 缺席，S-05）。' }
        if (!sessionId)
          return { kind: 'absent' as const, reason: '新会话还没有原生活动会话，附件在第一条消息发出后可用。' }
        return { kind: 'available' as const }
      }
      return {
        capability,
        prepare: async ({ sessionId, sourceId, idempotencyKey }) => {
          const cap = capability(sessionId)
          if (cap.kind !== 'available') return { kind: 'refused', reason: cap.reason }
          if (sessionId === undefined) return { kind: 'refused', reason: '新会话还没有原生活动会话，附件在第一条消息发出后可用。' }
          const client = workspace.selected()
          const connectionId = workspace.getSnapshot().selectedConnectionId ?? '-'
          try {
            const reference = await client.prepareAttachment!(sessionId, sourceId, idempotencyKey)
            preparedAttachments.set(preparedKey(connectionId, reference.preparedId), { reference, sessionId })
            return { kind: 'prepared', reference }
          } catch (cause) {
            const reason = cause instanceof Error ? cause.message : String(cause)
            if (linkDownOf(client)) return { kind: 'unknown', operationId: idempotencyKey }
            return { kind: 'refused', reason }
          }
        },
        release: async (preparedId, reason) => {
          void reason
          const client = workspace.selected()
          const connectionId = workspace.getSnapshot().selectedConnectionId ?? '-'
          const key = preparedKey(connectionId, preparedId)
          const entry = preparedAttachments.get(key)
          if (!entry) return // nothing this facade still owns: release is idempotent
          // The registry entry survives a failed release: the port still owns
          // the content, so the caller sees the refusal and the reference stays
          // reconcilable instead of silently leaking.
          await client.releasePreparedAttachment?.(entry.sessionId, preparedId)
          preparedAttachments.delete(key)
        },
      }
    })(),
    stop: runId => {
      const client = workspace.selected(), run = client.getSnapshot().runs[runId]
      if (!run) throw Error('Agent run unavailable')
      return client.stop(run.sessionId, runId)
    },
    respond: (id, answer) => workspace.selected().respond(id, answer),
    setOption: (id, value) => workspace.selected().setOption(id, value),
    // startDraft deliberately leaves the client-side selection untouched: discarding must
    // restore the previously selected session (C-0030), and safety comes from send() never
    // routing to a selection while a draft is active.
    startDraft: () => { const id = workspace.getSnapshot().selectedConnectionId; if (id) { const state = stateFor(id); state.draftActive = true; state.draftEndedBy = undefined; notify() } },
    discardDraft: () => { const id = workspace.getSnapshot().selectedConnectionId; if (id) { const state = stateFor(id); const wasActive = state.draftActive; state.draftActive = false; state.requestId = undefined; if (wasActive) state.draftEndedBy = 'discarded'; notify() } },
    selectWorkspace: async id => {
      const client = workspace.selected()
      if (!client.openWorkspace) throw Error('Agent project gate: unsupported')
      const info = await client.openWorkspace(id)
      const identity = identityOf(client)
      if (identity) rememberProject(identity, info.id) // a selection without identity is live but never persisted
      const connectionId = workspace.getSnapshot().selectedConnectionId
      if (connectionId) stateFor(connectionId).restoreFailed = false
    },
    addWorkspace: async path => {
      const client = workspace.selected()
      if (!client.addWorkspace) throw Error('Agent project registration: unsupported')
      const info = await client.addWorkspace(path)
      const identity = identityOf(client)
      if (identity) rememberProject(identity, info.id)
      const connectionId = workspace.getSnapshot().selectedConnectionId
      if (connectionId) stateFor(connectionId).restoreFailed = false
    },
    refreshWorkspaces: async () => { await workspace.selected().refreshWorkspaces?.() },
  }
}
