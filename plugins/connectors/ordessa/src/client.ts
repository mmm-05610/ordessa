import type {
  AgentCapabilities, AgentClient, AgentInteraction, AgentMessage, AgentSessionInfo, AgentSnapshot,
  AgentToolCall, AgentWorkspaceInfo, Availability, InteractionAnswer, RunStatus,
} from '@extensions/ordessa.agent-contracts/contract.js'
import type { AgentNativeBridge } from '@ordessa/native-bridge'

export const ORDESSA_ADAPTER_ID = 'ordessa.agent-server'
/** The connector id is frozen from the authenticated hello before registration, so the Server instance is part of the identity every layer keys on. */
export const connectorIdFor = (serverInstanceId: string): string => `ordessa:${serverInstanceId}`

type Value = Record<string, unknown>
const object = (value: unknown): Value | undefined => value && typeof value === 'object' && !Array.isArray(value) ? value as Value : undefined
const str = (value: unknown): string | undefined => typeof value === 'string' && value ? value : undefined
const int = (value: unknown): number | undefined => typeof value === 'number' && Number.isInteger(value) ? value : undefined
const errorText = (error: unknown): string => error instanceof Error ? error.message : String(error)
/** Strips only the IPC wrapper Electron adds around a native rejection; the message itself is already secret-free. */
export const unwrapBridgeError = (error: unknown): string =>
  errorText(error).replace(/^Error invoking remote method '[^']+':\s*(?:Error:\s*)?/, '')
/** The native half's prefix for a project the Server will not run in. Spelled rather than imported: the
 * renderer half must never reach the privileged module, which is the only holder of the Server token. */
const PROJECT_INVALID = 'project-invalid'
const isProjectLoss = (error: unknown) => unwrapBridgeError(error).startsWith(`${PROJECT_INVALID}:`)

export interface DeclaredCapability { id: string; supported: boolean; reason?: string }
/** What the authenticated `server.hello` proved before this connector was registered. */
export interface ServerIdentity {
  serverInstanceId: string
  protocolVersion: string
  capabilities: DeclaredCapability[]
  harnesses: { id: string }[]
}

export function parseIdentity(value: unknown): ServerIdentity {
  const raw = object(value)
  const serverInstanceId = str(raw?.serverInstanceId), protocolVersion = str(raw?.protocolVersion)
  if (!serverInstanceId || !protocolVersion) throw new Error('Ordessa Server identity is incomplete')
  return {
    serverInstanceId, protocolVersion,
    capabilities: Array.isArray(raw?.capabilities) ? (raw?.capabilities as DeclaredCapability[]) : [],
    harnesses: Array.isArray(raw?.harnesses) ? (raw?.harnesses as { id: string }[]) : [],
  }
}

/** Only the routes this product really calls count; event kinds belong to the wire/1 projection the hello already gated. */
export function capabilitiesOf(identity: ServerIdentity): AgentCapabilities {
  const at = (method: string): Availability =>
    identity.capabilities.some(item => item.id === method && item.supported) ? 'supported' : 'unsupported'
  const projects = at('workspaces.list') === 'supported' && at('workspaces.open') === 'supported'
  return {
    history: at('history.snapshot'),
    reasoning: 'supported',
    tools: 'supported',
    stop: at('runs.stop'),
    // FC-0041: this one enum covers approvals, so it must not be downgraded because ordinary input kinds have no route.
    interactions: at('approvals.decide'),
    models: 'unsupported',
    modes: 'unsupported',
    workspaces: projects ? 'supported' : 'unsupported',
  }
}

const RUN_STATES: Record<string, RunStatus> = {
  queued: 'starting', dispatched: 'starting', running: 'running', stopping: 'stop-requested',
  stopped: 'cancelled', completed: 'completed', failed: 'failed', unknown: 'unknown',
}
const TOOL_STATES: Record<string, AgentToolCall['status']> = {
  requested: 'running', running: 'running', awaiting_approval: 'running',
  completed: 'completed', failed: 'failed', denied: 'failed',
}
const APPROVAL_CHOICES = [{ id: 'allow', label: 'Allow' }, { id: 'deny', label: 'Deny' }] as const
/** Kinds wire/1 defines that this UI has no slot for yet — known, so they never read as version drift. */
const UNPROJECTED_KINDS = new Set(['usage.updated', 'plan.updated', 'mode.updated', 'queue.updated', 'config.changed', 'workspace.connection'])

const operationDetail = (detail: unknown): string | undefined => {
  if (typeof detail === 'string') return detail || undefined
  if (!Array.isArray(detail)) return undefined
  const lines = detail.map(object).filter(Boolean)
    .map(item => `${str(item?.label) ?? ''}${item && str(item.label) ? ': ' : ''}${str(item?.value) ?? ''}`)
    .filter(line => line.trim())
  return lines.length ? lines.join('\n') : undefined
}

/** Opens the privileged adapter, performs the authenticated handshake and returns the identity to register under. */
export async function requestServerIdentity(bridge: AgentNativeBridge): Promise<ServerIdentity> {
  const instanceId = await bridge.open(ORDESSA_ADAPTER_ID)
  try {
    return parseIdentity(await bridge.send(instanceId, { method: 'identity' }))
  } finally {
    await bridge.close(instanceId).catch(() => undefined)
  }
}

interface HistoryResult {
  outcome?: string
  frames?: unknown[]
  resumeCursor?: string
  olderCursor?: string
  reason?: string
}

export class OrdessaClient implements AgentClient {
  isDisposed = false
  private instanceId = ''
  private identity: ServerIdentity
  private readonly unsubscribe: () => void
  private listeners = new Set<() => void>()
  private state: AgentSnapshot
  private activeAssistant = new Map<string, string>()
  private tools = new Map<string, Map<string, AgentToolCall>>()
  /** Session -> the execution id the Server reported as open; only that id may be stopped. */
  private openRuns = new Map<string, string>()
  private approvalRoutes = new Map<string, { version: number; used: boolean }>()
  private resumeCursors = new Map<string, string>()
  private streamedSession: string | undefined

  private constructor(private bridge: AgentNativeBridge, connectorId: string, identity: ServerIdentity) {
    this.identity = identity
    this.state = {
      connection: { id: connectorId, title: 'Ordessa Server', status: 'connecting',
        capabilities: capabilitiesOf(identity), serverInstanceId: identity.serverInstanceId },
      sessions: [], sessionList: 'unknown', messages: {}, runs: {}, interactions: [], options: [],
      workspaces: { state: 'unknown', items: [] },
    }
    this.unsubscribe = bridge.subscribe(event => {
      if (event.instanceId !== this.instanceId || this.isDisposed) return
      this.receive(event.error ? { method: 'ordessa/down', params: { reason: event.error } } : event.frame)
    })
  }

  /** The id was already frozen before registration; a different Server behind the same URL must never inherit it. */
  static async connect(bridge: AgentNativeBridge, connectorId: string, serverInstanceId: string): Promise<OrdessaClient> {
    const client = new OrdessaClient(bridge, connectorId, { serverInstanceId, protocolVersion: 'wire/1', capabilities: [], harnesses: [] })
    try {
      client.instanceId = await bridge.open(ORDESSA_ADAPTER_ID)
      const identity = parseIdentity(await client.request('identity'))
      if (identity.serverInstanceId !== serverInstanceId) throw new Error('Ordessa Server identity changed; reconnect the new Server as its own connection')
      client.identity = identity
      client.state = { ...client.state, connection: { ...client.state.connection, status: 'connected', capabilities: capabilitiesOf(identity) } }
      for (const listener of client.listeners) listener()
      return client
    } catch (error) {
      client.dispose()
      throw new Error(unwrapBridgeError(error))
    }
  }

  getSnapshot = () => this.state
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private publish(patch: Partial<AgentSnapshot>) {
    if (this.isDisposed) return
    this.state = { ...this.state, ...patch }
    for (const listener of this.listeners) listener()
  }
  private request<T>(method: string, params: Value = {}): Promise<T> {
    if (this.isDisposed || !this.instanceId) return Promise.reject(new Error('Ordessa connection unavailable'))
    let timer: ReturnType<typeof setTimeout>
    return Promise.race([this.bridge.send(this.instanceId, { method, params }) as Promise<T>,
      // A timeout never proves the request failed, so callers must keep the request id instead of re-issuing.
      new Promise<T>((_, reject) => { timer = setTimeout(() => reject(new Error(`Ordessa operation timed out: ${method}`)), 30_000) }),
    ]).finally(() => clearTimeout(timer))
  }

  private upsert(sessionId: string, message: AgentMessage) {
    const current = this.state.messages[sessionId] ?? []
    const index = current.findIndex(item => item.id === message.id), next = [...current]
    if (index < 0) next.push(message); else next[index] = message
    this.publish({ messages: { ...this.state.messages, [sessionId]: next } })
  }
  private drop(sessionId: string, id: string) {
    const current = this.state.messages[sessionId]
    if (!current?.some(item => item.id === id)) return
    this.publish({ messages: { ...this.state.messages, [sessionId]: current.filter(item => item.id !== id) } })
  }
  private patch(sessionId: string, id: string, change: (previous: AgentMessage) => AgentMessage) {
    const previous = this.state.messages[sessionId]?.find(item => item.id === id) ?? { id, role: 'assistant' as const, text: '' }
    this.upsert(sessionId, change(previous))
  }
  private mergeTool(sessionId: string, update: { id: string; name?: string; result?: string; status?: AgentToolCall['status'] }): AgentMessage {
    const cards = this.tools.get(sessionId) ?? new Map<string, AgentToolCall>()
    this.tools.set(sessionId, cards)
    const previous = cards.get(update.id)
    // A late running update must not regress a card the Server already settled.
    const sticky = previous && (previous.status === 'completed' || previous.status === 'failed') && update.status === 'running'
    const next: AgentToolCall = { id: update.id, name: update.name ?? previous?.name ?? 'Tool',
      arguments: previous?.arguments, result: sticky ? previous.result : update.result ?? previous?.result,
      status: sticky ? previous.status : update.status ?? previous?.status ?? 'running' }
    cards.set(update.id, next)
    return { id: `ordessa-tool-${update.id}`, role: 'assistant', text: '', tools: [next] }
  }
  private updateRun(id: string, sessionId: string, status: RunStatus, reason?: string) {
    const previous = this.state.runs[id]
    if (previous && !['starting', 'running', 'stop-requested'].includes(previous.status)) return
    const stoppable = this.state.connection.capabilities.stop === 'supported' && (status === 'starting' || status === 'running')
    this.publish({ runs: { ...this.state.runs, [id]: { id, sessionId, status, stoppable } } })
    if (status === 'completed' || status === 'failed' || status === 'cancelled' || status === 'unknown') {
      if (this.openRuns.get(sessionId) === id) this.openRuns.delete(sessionId)
      // The execution's own terminal state is the only verdict the wire offers, and no assistant
      // card may keep streaming after it; `stopReason` is absent from wire/1 by design.
      const messages = this.state.messages[sessionId]
      if (messages?.some(message => message.status === 'running' || message.status === 'starting')) {
        this.publish({ messages: { ...this.state.messages, [sessionId]: messages.map(message =>
          message.status === 'running' || message.status === 'starting' ? { ...message, status } : message) } })
      }
      if (status === 'failed' && reason) this.publish({ diagnostic: `Ordessa run failed (${reason})` })
    }
  }
  private setInteraction(interactionId: string, state: AgentInteraction['state']) {
    this.publish({ interactions: this.state.interactions.map(item => item.id === interactionId ? { ...item, state } : item) })
  }

  private receive(frame: unknown) {
    const wrapper = object(frame)
    if (!wrapper || !str(wrapper.method)) { this.publish({ diagnostic: 'Unknown Ordessa native event' }); return }
    if (wrapper.method === 'ordessa/down') { this.channelDown(str(object(wrapper.params)?.reason) ?? 'closed'); return }
    if (wrapper.method !== 'ordessa/event') { this.publish({ diagnostic: 'Unknown Ordessa native event' }); return }
    const params = object(wrapper.params), envelope = object(params?.frame), body = object(envelope?.event)
    const sessionId = str(params?.sessionId)
    if (!sessionId || !body || !str(body.kind)) { this.publish({ diagnostic: 'Unroutable Ordessa event' }); return }
    const cursor = str(envelope?.cursor)
    // Only the live `w1:` cursor may resume; an older-history cursor is deliberately never stored here.
    if (cursor) this.resumeCursors.set(sessionId, cursor)
    this.project(sessionId, body)
  }

  private channelDown(reason: string) {
    this.streamedSession = undefined
    // Every booked run loses its only settlement channel at once, so none may keep claiming a verdict.
    for (const [sessionId, runId] of [...this.openRuns]) this.updateRun(runId, sessionId, 'unknown')
    this.openRuns.clear()
    // With no settlement channel, a pending approval can no longer be shown as answerable or re-answered safely.
    const pending = this.state.interactions.filter(item => item.state === 'pending' || item.state === 'responding')
    for (const item of pending) this.approvalRoutes.delete(item.id)
    this.publish({ interactions: this.state.interactions.map(item =>
      item.state === 'pending' || item.state === 'responding' ? { ...item, state: 'unknown' } : item) })
    this.publish({ diagnostic: `Ordessa event stream stopped (${reason}); an unconfirmed run outcome stays unknown` })
  }

  private project(sessionId: string, body: Value) {
    const kind = str(body.kind) ?? ''
    if (kind === 'message.delta') {
      const messageId = str(body.messageId)
      if (!messageId) return
      this.activeAssistant.set(sessionId, messageId)
      this.patch(sessionId, messageId, previous => ({ ...previous, role: 'assistant', text: previous.text + (str(body.text) ?? ''), status: 'running' }))
      return
    }
    if (kind === 'message.final') {
      const messageId = str(body.messageId)
      if (!messageId) return
      if (str(body.displayKind) === 'hidden') { this.drop(sessionId, messageId); return }
      const role = str(body.role)
      // The contract has no slot for a system message, so one is not silently relabelled as an assistant turn.
      if (role !== 'user' && role !== 'assistant') return
      this.activeAssistant.delete(sessionId)
      this.upsert(sessionId, { id: messageId, role, text: str(body.text) ?? '',
        status: role === 'assistant' ? this.state.runs[messageId]?.status : undefined })
      return
    }
    if (kind === 'thought.delta') {
      const id = this.activeAssistant.get(sessionId)
      if (id) this.patch(sessionId, id, previous => ({ ...previous, reasoning: (previous.reasoning ?? '') + (str(body.text) ?? '') }))
      return
    }
    if (kind === 'tool.update') {
      const toolCallId = str(body.toolCallId)
      if (!toolCallId) return
      this.upsert(sessionId, this.mergeTool(sessionId, { id: toolCallId,
        name: typeof body.tool === 'string' ? body.tool : str(object(body.tool)?.name),
        result: str(body.resultExcerpt) ?? str(body.summary), status: TOOL_STATES[str(body.state) ?? ''] ?? 'unknown' }))
      return
    }
    if (kind === 'approval.requested') { this.approvalRequested(sessionId, body); return }
    if (kind === 'approval.settled') {
      const approvalId = str(body.approvalId)
      if (!approvalId) return
      const outcome = str(body.outcome)
      const state: AgentInteraction['state'] = outcome === 'allowed' || outcome === 'denied' ? 'resolved' : outcome === 'expired' ? 'expired' : 'unknown'
      this.approvalRoutes.delete(approvalId)
      this.publish({ interactions: this.state.interactions.map(item =>
        item.id === approvalId && item.state !== 'resolved' ? { ...item, state } : item) })
      return
    }
    if (kind === 'execution.state') {
      const executionId = str(body.executionId)
      const state = str(body.state)
      if (!executionId || !state) return
      const status = RUN_STATES[state] ?? 'unknown'
      if (['running', 'queued', 'dispatched'].includes(state)) this.openRuns.set(sessionId, executionId)
      this.updateRun(executionId, sessionId, status, str(body.reason))
      return
    }
    if (!UNPROJECTED_KINDS.has(kind)) this.publish({ diagnostic: `Unknown Ordessa event kind: ${kind}` })
  }

  private approvalRequested(sessionId: string, body: Value) {
    const approval = object(body.approval)
    const approvalId = str(approval?.approvalId), version = int(approval?.version)
    if (!approvalId) { this.publish({ diagnostic: 'An Ordessa approval arrived without an identity' }); return }
    const operation = object(approval?.operation)
    const answerable = this.state.connection.capabilities.interactions === 'supported' && version !== undefined
    const item: AgentInteraction = { id: approvalId, sessionId, turnId: str(approval?.executionId), kind: 'approval',
      title: str(operation?.title) ?? 'Approval required', detail: operationDetail(operation?.detail),
      ...(answerable ? { choices: APPROVAL_CHOICES.map(choice => ({ ...choice })), state: 'pending' as const } : { state: 'unknown' as const }) }
    if (answerable) this.approvalRoutes.set(approvalId, { version: version as number, used: false })
    else this.publish({ diagnostic: 'An approval arrived but this Server cannot record a decision; it is not answerable' })
    this.publish({ interactions: [...this.state.interactions.filter(previous => previous.id !== approvalId), item] })
  }

  async refreshSessions() {
    this.publish({ sessionList: 'loading' })
    try {
      const sessions = await this.request<AgentSessionInfo[]>('sessions')
      this.publish({ sessions, sessionList: 'ready' })
    } catch (error) { this.publish({ sessionList: 'error', diagnostic: errorText(error) }); throw error }
  }

  /** A session exists only once the Server has accepted a first send, so there is nothing to create here. */
  async newSession(): Promise<string> {
    throw new Error('An Ordessa session is created by the first send into a project')
  }

  async openSession(id: string) {
    this.publish({ selectedSessionId: id })
    // Rebuilding from the Server's own log, so a reopen cannot inherit a half-projected live run.
    this.tools.delete(id)
    this.activeAssistant.delete(id)
    await this.loadHistory(id)
    await this.subscribeStream(id)
  }

  private async loadHistory(sessionId: string) {
    let snapshot = await this.request<HistoryResult>('history', { sessionId })
    if (snapshot.outcome !== 'snapshot') {
      this.publish({ diagnostic: `Ordessa history asked for a resync (${snapshot.reason ?? 'no reason'}); reading from the newest event` })
      this.resumeCursors.delete(sessionId)
      snapshot = await this.request<HistoryResult>('history', { sessionId })
      if (snapshot.outcome !== 'snapshot') throw new Error('Ordessa history could not be read; the session stays unopened')
    }
    this.publish({ messages: { ...this.state.messages, [sessionId]: [] } })
    for (const item of snapshot.frames ?? []) this.receive({ method: 'ordessa/event', params: { sessionId, frame: item } })
    // The snapshot's join point is the newest cursor of the read; replayed frames must not pull it backwards,
    // or the subscription would re-deliver what was just projected.
    this.resumeCursors.set(sessionId, snapshot.resumeCursor ?? '')
  }

  private async subscribeStream(sessionId: string) {
    if (this.streamedSession && this.streamedSession !== sessionId) {
      await this.request('closeStream', { sessionId: this.streamedSession }).catch(() => undefined)
      this.streamedSession = undefined
    }
    const cursor = this.resumeCursors.get(sessionId)
    await this.request('stream', { sessionId, ...(cursor ? { cursor } : {}) })
    this.streamedSession = sessionId
  }

  async refreshWorkspaces() {
    const previous = this.state.workspaces
    this.publish({ workspaces: { state: 'loading', items: previous?.items ?? [] } })
    try {
      const items = await this.request<AgentWorkspaceInfo[]>('projects')
      const selected = previous?.selectedWorkspaceId
      const kept = selected !== undefined && items.some(item => item.id === selected)
      this.publish({ workspaces: { state: 'ready', items, ...(kept ? { selectedWorkspaceId: selected } : {}) } })
      if (selected !== undefined && !kept) this.publish({ diagnostic: 'The selected project is no longer offered by this Server; choose a project again' })
    } catch (error) {
      this.publish({ workspaces: { state: 'error', items: [] }, diagnostic: errorText(error) })
      throw error
    }
  }

  /** The native half re-validates identity and archived state, so a stale selection can never read as openable. */
  async openWorkspace(id: string): Promise<AgentWorkspaceInfo> {
    const previous = this.state.workspaces
    const base = { state: 'ready' as const, items: previous?.items ?? [] }
    try {
      const opened = await this.request<AgentWorkspaceInfo>('openProject', { id })
      this.publish({ workspaces: { ...base, selectedWorkspaceId: opened.id } })
      return opened
    } catch (error) {
      // FC-0032: a refused revalidation clears the selection instead of leaving a pick that could still unlock Send.
      this.publish({ workspaces: base, diagnostic: errorText(error) })
      throw error
    }
  }

  async addWorkspace(path: string): Promise<AgentWorkspaceInfo> {
    const added = await this.request<AgentWorkspaceInfo>('addProject', { path })
    await this.refreshWorkspaces()
    return this.openWorkspace(added.id)
  }

  async createAndSend(workspaceId: string, text: string, requestId: string): Promise<{ sessionId: string }> {
    // The native half resolves only after an accepted turn with a real session id, so nothing below runs on a guess.
    let sent: Value
    try {
      sent = await this.request<Value>('createAndSend', { workspaceId, text, requestId })
    } catch (error) {
      // FC-0057: a project the Server had already dropped cannot take this turn, and leaving it selected keeps
      // the composer advertising a sendable draft. The text and request id belong to the upper layer, which
      // holds both; only the stale pick is this half's to clear.
      if (isProjectLoss(error)) {
        const previous = this.state.workspaces
        // A pick the user changed while this send was in flight is not the stale one this refusal names.
        if (previous?.selectedWorkspaceId === workspaceId) {
          this.publish({ workspaces: { state: 'ready', items: previous.items }, diagnostic: unwrapBridgeError(error) })
        }
      }
      throw error
    }
    const sessionId = str(sent.sessionId)
    if (!sessionId) throw new Error('Ordessa first send returned no session identity')
    const listed = await this.request<AgentSessionInfo[]>('sessions').catch(() => undefined)
    const confirmed = listed?.find(item => item.id === sessionId)
    // The Server's own record owns the binding, and it names the project by id or by its path (the same
    // pair the F2 facade accepts). A session under any other project is not this draft's success.
    const project = this.state.workspaces?.items.find(item => item.id === workspaceId)
    if (confirmed?.workspaceId && confirmed.workspaceId !== workspaceId && confirmed.workspaceId !== project?.normalizedPath)
      throw new Error('Ordessa first send returned a session bound to a different project')
    // A list read that has not caught up yet must not erase the session the Server just confirmed.
    const sessions = listed?.some(item => item.id === sessionId) ? listed
      : [{ id: sessionId, title: sessionId, workspaceId }, ...(listed ?? [])]
    this.publish({ sessions, ...(listed ? { sessionList: 'ready' as const } : {}) })
    await this.openSession(sessionId)
    this.publish({ workspaces: { ...(this.state.workspaces ?? { state: 'ready', items: [] }), state: 'ready', selectedWorkspaceId: workspaceId } })
    return { sessionId }
  }

  async send(sessionId: string, text: string) {
    if (!text.trim()) return
    const sent = await this.request<Value>('send', { sessionId, text })
    const outcome = str(sent.outcome), executionId = str(sent.executionId)
    if (outcome !== 'accepted') { this.publish({ diagnostic: `Ordessa send outcome was ${outcome ?? 'missing'}` }); return }
    // A queued turn has no execution yet, so no run is booked for it here.
    if (executionId) { this.openRuns.set(sessionId, executionId); this.updateRun(executionId, sessionId, 'starting') }
  }

  async stop(sessionId: string, runId: string) {
    const run = this.state.runs[runId]
    if (!run || run.sessionId !== sessionId || !run.stoppable) throw new Error('Ordessa run is not available to stop')
    this.updateRun(runId, sessionId, 'stop-requested')
    try {
      const stopped = await this.request<Value>('stop', { sessionId, executionId: runId })
      const outcome = str(stopped.outcome)
      // `stop_requested` never verdicts; only a later execution.state can.
      if (outcome !== 'stop_requested') {
        this.updateRun(runId, sessionId, 'unknown')
        this.publish({ diagnostic: `Ordessa stop was not confirmed (${outcome ?? 'no outcome'})` })
      }
    } catch (error) {
      this.updateRun(runId, sessionId, 'unknown')
      throw error
    }
  }

  async respond(interactionId: string, answer: InteractionAnswer) {
    const route = this.approvalRoutes.get(interactionId)
    const item = this.state.interactions.find(value => value.id === interactionId)
    // Only a real approval with a real route is answerable; ordinary input kinds never get one (FC-0041).
    if (!route || !item || item.kind !== 'approval' || item.state !== 'pending' || route.used) {
      throw new Error('Ordessa interaction is not an answerable approval')
    }
    const decision = answer.kind === 'choice' ? answer.choiceId : undefined
    if ((decision !== 'allow' && decision !== 'deny') || !item.choices?.some(choice => choice.id === decision)) {
      throw new Error('An Ordessa approval is answered with allow or deny only')
    }
    route.used = true
    this.setInteraction(interactionId, 'responding')
    try {
      const result = await this.request<Value>('decide', { approvalId: interactionId, expectedVersion: route.version, decision, scope: { kind: 'once' } })
      const outcome = str(result.outcome)
      this.approvalRoutes.delete(interactionId)
      if (outcome === 'recorded' || outcome === 'already_recorded') this.setInteraction(interactionId, 'resolved')
      else if (outcome === 'invalid') {
        this.setInteraction(interactionId, 'expired')
        this.publish({ diagnostic: `Ordessa rejected the approval decision (${str(result.reason) ?? 'invalid'})` })
      } else {
        this.setInteraction(interactionId, 'unknown')
        this.publish({ diagnostic: 'Ordessa approval decision outcome is unknown' })
      }
    } catch (error) {
      // A version conflict proves the record moved elsewhere; only its settled event can say where.
      this.approvalRoutes.delete(interactionId)
      this.setInteraction(interactionId, 'unknown')
      this.publish({ diagnostic: errorText(error) })
      throw error
    }
  }

  /** Provider and model selection is design-only in this product, so no option is offered or faked. */
  async setOption(id: string, value: string): Promise<void> {
    throw new Error(`Ordessa does not offer the ${id} option`)
  }

  dispose() {
    if (this.isDisposed) return
    const sessionId = this.streamedSession
    this.isDisposed = true
    this.unsubscribe()
    this.listeners.clear()
    this.approvalRoutes.clear(); this.tools.clear(); this.openRuns.clear()
    this.activeAssistant.clear(); this.resumeCursors.clear()
    this.streamedSession = undefined
    // Released before the disposed flag, because a disposed client refuses its own requests.
    if (this.instanceId) {
      if (sessionId) void this.bridge.send(this.instanceId, { method: 'closeStream', params: { sessionId } }).catch(() => undefined)
      void this.bridge.close(this.instanceId).catch(() => undefined)
    }
  }
}
