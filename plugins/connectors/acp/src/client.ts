import * as acp from '@agentclientprotocol/sdk'
import type {
  AgentCapabilities, AgentClient, AgentInteraction, AgentMessage, AgentReleaseState, AgentReleaseStatus,
  AgentSessionInfo, AgentSnapshot, AgentToolCall, AgentWorkspaceInfo, InteractionAnswer, RunStatus,
} from '@extensions/ordessa.agent-contracts/contract.js'
import type { AcpChannelHandle, AcpChannelSpec } from './channel'
import { parseNativeCommands, type NativeCommandCatalog } from './commands'
import { type AcpControlledSubmission, validateControlledSubmission } from './submission'
import { referenceScheme, samePreparedReference, validPreparedReference, type AcpAttachmentCapabilities, type AcpAttachmentTarget,
  type AcpPreparedAttachment } from './attachments'

/**
 * The single ACP wire→`AgentSnapshot` mapping for this product (no other module speaks protocol).
 *
 * Channel model (reviewed seam, tests/integration/acp-connector/fixtures/target-seam.ts): selecting the
 * Server/Harness reads projects only — no channel. `openWorkspace` binds one project, acquires its
 * managed channel and runs exactly one `initialize` on it. A draft stays frontend-only until
 * `createAndSend`, which lazily runs `session/new` + `session/prompt` and resolves once the Harness
 * has ACCEPTED the first send (any inbound event referencing the native session: a `session/update`,
 * a reverse request, or the prompt response) — never waiting for the whole turn, and rejecting (not
 * re-issuing) when the link dies before that acceptance.
 *
 * Every native fact is namespaced by its channel: two project channels that mint the same native
 * session id keep separate keys inside this one client (raw id while unconflicted, channel-scoped
 * once another channel claims it). A transport drop is never a cancel and never a release; a view
 * switch is neither; only `dispose()` calls the handle's explicit release.
 */

const STOP_REASON: Record<acp.StopReason, RunStatus> = {
  end_turn: 'completed', cancelled: 'cancelled', max_turn_requests: 'failed', refusal: 'failed', max_tokens: 'unknown',
}
const TOOL_STATUS: Record<acp.ToolCallStatus, AgentToolCall['status']> = {
  pending: 'running', in_progress: 'running', completed: 'completed', failed: 'failed',
}
const OPEN_RUN = (status: RunStatus) => status === 'starting' || status === 'running' || status === 'stop-requested'
const KNOWN_SESSION_UPDATES = new Set([
  'user_message_chunk', 'agent_message_chunk', 'agent_thought_chunk', 'tool_call',
  'tool_call_update', 'plan', 'plan_update', 'plan_removed', 'available_commands_update',
  'current_mode_update', 'config_option_update', 'session_info_update', 'usage_update',
  'notice', 'compaction_update', 'compaction_summary_chunk',
])

interface Channel {
  readonly projectId: string
  readonly binding: AgentWorkspaceInfo
  readonly handle: AcpChannelHandle
  conn: acp.ClientSideConnection
  capabilities: acp.AgentCapabilities
  /** Native session id → this client's key, scoped to the channel that owns it. */
  readonly nativeToKey: Map<string, string>
  commandsDown: boolean
  unsubscribeDown?: () => void
  creatingSessions: number
  readonly pendingCommands: Map<string, readonly import('./commands').NativeCommand[] | null>
}
interface Route { channel: Channel; nativeId: string; key: string }
/** `runId` is the run that was live when the native request arrived ('' when none was): the
 * answer belongs to THAT run, never to whatever the session happens to run later. */
interface InteractionRecord { item: AgentInteraction; settle: (response: acp.RequestPermissionResponse) => void; runId: string }
interface FirstSend { settle: () => void; fail: (error: unknown) => void }

export class AcpClient implements AgentClient {
  isDisposed = false
  private readonly spec: AcpChannelSpec
  private state: AgentSnapshot
  private readonly listeners = new Set<() => void>()
  private readonly channels = new Map<string, Channel>()
  private readonly opening = new Map<string, Promise<Channel>>()
  /** Handles acquired but not yet registered as channels: between `acquireChannel` returning and
   * the channel landing in `channels`, this set — not `channels` — is what makes dispose() able to
   * reach the handle, so a late arrival can never be orphaned unreleased. */
  private readonly unownedHandles = new Set<AcpChannelHandle>()
  /** Confirmed releases only — an attempt that failed never joins this set (see `releaseHandle`). */
  private readonly releasedHandles = new WeakSet<AcpChannelHandle>()
  private readonly releasing = new WeakMap<AcpChannelHandle, Promise<void>>()
  /** The release lifecycle ledger: an entry exists from the moment its attempt is IN-FLIGHT (an
   * unanswered release is a STATE, never an absence of evidence) through a FAILED refusal; the
   * backend's confirmation removes it — and the removal is itself announced. Failed entries stay
   * here retryable until a later attempt confirms them. */
  private readonly releaseLedger = new Map<string, { handle: AcpChannelHandle; status: 'in-flight' | 'failed'; reason?: string }>()
  private readonly releaseWatchers = new Set<(state: AgentReleaseState) => void>()
  /** The host-visible diagnostic half of the release lifecycle: contract `AgentClient.releaseFailures`,
   * read together with `releaseStates()`/`subscribeReleaseStates()` and the `retryReleases()` entry point. */
  get releaseFailures(): { connectionId: string; reason: string }[] {
    return [...this.releaseLedger].filter(([, record]) => record.status === 'failed')
      .map(([connectionId, record]) => ({ connectionId, reason: record.reason ?? '' }))
  }
  releaseStates = (): AgentReleaseState[] =>
    [...this.releaseLedger].map(([connectionId, record]) =>
      ({ connectionId, status: record.status, ...(record.reason === undefined ? {} : { reason: record.reason }) }))
  /** Announcements are delivered even after dispose(): an evicted client's asynchronous answers
   * are exactly what the host must keep receiving, and this notification — not polling — is how a
   * release-state change reaches the host's published surface. */
  subscribeReleaseStates = (listener: (state: AgentReleaseState) => void) => {
    this.releaseWatchers.add(listener)
    return () => { this.releaseWatchers.delete(listener) }
  }
  private announceRelease(handle: AcpChannelHandle, status: AgentReleaseStatus, reason?: string) {
    if (status === 'confirmed') this.releaseLedger.delete(handle.connectionId)
    else this.releaseLedger.set(handle.connectionId, { handle, status, ...(reason === undefined ? {} : { reason }) })
    const state: AgentReleaseState = { connectionId: handle.connectionId, status, ...(reason === undefined ? {} : { reason }) }
    for (const watcher of [...this.releaseWatchers]) watcher(state)
    this.maybeDrainReleases()
  }
  /** The host's forget-signal: this promise settles only when the client provably can never
   * announce another release state — disposed, no acquire/initialize attempt still in flight to
   * stand a handle down, and the backend has confirmed every stand-down ever started. An empty
   * ledger alone is NOT the condition: a late handle has not entered it yet. Checked after every
   * event that could complete the drain; one-way, and never rejects. */
  private settleReleases!: () => void
  private releasesDrained = false
  readonly releasesSettled: Promise<void> = new Promise(resolve => { this.settleReleases = resolve })
  private maybeDrainReleases() {
    if (this.releasesDrained || !this.isDisposed || this.releaseLedger.size > 0
      || this.unownedHandles.size > 0 || this.opening.size > 0) return
    this.releasesDrained = true
    this.settleReleases()
  }
  private readonly routes = new Map<string, Route>()
  private readonly nativeCommands = new Map<string, NativeCommandCatalog>()
  private readonly activeCommandSession = new Map<string, string>()
  private readonly buckets = new Map<string, AgentMessage[]>()
  /** The one message each session's chunkless stream is currently filling. `ContentChunk.messageId`
   * is optional in the pinned protocol, and a real Harness (Pi) omits it — consecutive chunks then
   * belong to the SAME message, so they accumulate into this slot instead of minting a card each.
   * The slot is a per-session projection state (the session key already carries its channel), and
   * it closes at every boundary that proves a new message started: the client's own turn lifecycle
   * (`startTurn`/`finishTurn` — the authoritative turn signal, since ACP allows one in-flight
   * prompt per session and the protocol names no turn-start event) and any tool event (content
   * before and after a tool call is independent). A chunk that DOES carry a messageId groups by
   * that native id (R8) and never joins or takes the slot. */
  private readonly openStreams = new Map<string, { id: string; role: 'user' | 'assistant' }>()
  private readonly sessionList: { items: AgentSessionInfo[]; state: 'unknown' | 'loading' | 'ready' | 'partial' | 'error' } =
    { items: [], state: 'unknown' }
  private readonly runs = new Map<string, { id: string; sessionId: string; status: RunStatus }>()
  private readonly interactions = new Map<string, InteractionRecord>()
  private readonly firstSends = new Map<string, FirstSend>()
  /** A renderer identity crosses the backend only once per client lifetime, including uncertain
   * authorization calls. Reusing it after an error could consume the same permit twice. */
  private readonly usedControlledSubmissionIds = new Set<string>()
  private readonly pendingControlledSessions = new Set<string>()
  private readonly projects: AgentWorkspaceInfo[] = []
  private selectedWorkspaceId: string | undefined
  private sequence = 0
  /** `AgentClient.addWorkspace`, present exactly when the host orchestration supplies the
   * registration op (see AcpChannelSpec.addProject): absent means the UI must disable the entry,
   * never fake an add. The flow matches the CP connector — register, re-read the Server's list, and
   * select the authoritative project id. */
  readonly addWorkspace?: (path: string) => Promise<AgentWorkspaceInfo>

  private constructor(spec: AcpChannelSpec, connectorId: string, projects: readonly AgentWorkspaceInfo[]) {
    this.spec = spec
    if (spec.addProject) {
      const addProject = spec.addProject.bind(spec)
      this.addWorkspace = async (path: string) => {
        this.assertLive()
        const added = await addProject(path)
        await this.refreshWorkspaces()
        return this.openWorkspace(added.id)
      }
    }
    this.projects.push(...projects)
    this.state = {
      connection: {
        id: connectorId, title: `ACP · ${spec.harness.title}`, status: 'connected',
        capabilities: { history: 'unsupported', reasoning: 'supported', tools: 'supported', stop: 'supported',
          interactions: 'supported', models: 'unsupported', modes: 'unsupported', workspaces: 'supported' },
        serverInstanceId: spec.serverInstanceId,
      },
      sessions: [], sessionList: 'unknown', messages: {}, runs: {}, interactions: [], options: [],
      workspaces: { state: 'ready', items: [...projects] },
    }
  }

  /** Reading the project list is orchestration work, not an ACP channel: nothing is acquired here. */
  static async connect(spec: AcpChannelSpec, connectorId: string): Promise<AcpClient> {
    const projects = await spec.listProjects()
    return new AcpClient(spec, connectorId, projects)
  }

  getSnapshot = () => this.state
  /** The ACP event's own connection and native session scope, never a synthesized brand menu. */
  getNativeCommands = (sessionKey: string): NativeCommandCatalog => {
    const route = this.routes.get(sessionKey)
    if (!route) return Object.freeze({ kind: 'absent' })
    const channel = route.channel
    if (this.isDisposed || channel.commandsDown || this.channels.get(channel.projectId) !== channel)
      return Object.freeze({ kind: 'unknown', reason: 'channel-down' })
    if (!channel.handle.subscribeDown)
      return Object.freeze({ kind: 'unknown', reason: 'unobservable' })
    if (this.activeCommandSession.get(channel.handle.connectionId) !== sessionKey)
      return Object.freeze({ kind: 'unknown', reason: 'stale-session' })
    return this.nativeCommands.get(sessionKey) ?? Object.freeze({ kind: 'absent' })
  }
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }

  private publish(patch: Partial<AgentSnapshot> = {}) {
    if (this.isDisposed) return
    this.state = {
      ...this.state,
      sessions: [...this.sessionList.items],
      sessionList: this.sessionList.state,
      messages: Object.fromEntries(this.buckets),
      runs: Object.fromEntries(this.runs),
      interactions: [...this.interactions.values()].map(record => record.item),
      workspaces: {
        state: 'ready', items: [...this.projects],
        ...(this.selectedWorkspaceId ? { selectedWorkspaceId: this.selectedWorkspaceId } : {}),
      },
      ...patch,
    }
    for (const listener of [...this.listeners]) listener()
  }
  private assertLive() { if (this.isDisposed) throw new Error('ACP connection disposed') }
  private nextId(prefix: string) { return `${prefix}_${++this.sequence}` }

  // ——— channel lifecycle ————————————————————————————————————————————————

  private async ensureChannel(projectId: string): Promise<Channel> {
    this.assertLive()
    const live = this.channels.get(projectId)
    if (live) return live
    const pending = this.opening.get(projectId)
    if (pending) return await pending
    // The opening entry is cleared on success AND failure: a failed task left in the map would pin
    // the project to the old error forever, so a retry could never recover a dropped handshake.
    const task = this.acquireAndInitialize(projectId)
      // The entry stays until the task itself settles — after dispose() it is the drain
      // attestation's witness that this attempt can still stand a late handle down.
      .finally(() => {
        if (this.opening.get(projectId) === task) this.opening.delete(projectId)
        this.maybeDrainReleases()
      })
    this.opening.set(projectId, task)
    return task
  }

  /** Release distinguishes three announced states, not one: CONFIRMED (never re-attempted — dispose()
   * and a failing open race on the same channel, and the backend counts every release call),
   * IN-FLIGHT (announced the instant the attempt starts; concurrent callers join the one request,
   * they do not issue a second), and FAILED — the handle stays retryable, the reason is recorded in
   * `releaseFailures`, and the rejection reaches every awaited caller instead of being swallowed.
   * No silent auto-retry: a failed handle is retried only by an explicit release — dispose()'s own
   * attempt, or the host's `retryReleases()`. */
  private releaseHandle(handle: AcpChannelHandle): Promise<void> {
    if (this.releasedHandles.has(handle)) return Promise.resolve()
    const pending = this.releasing.get(handle)
    if (pending) return pending
    // IN-FLIGHT is announced synchronously, before the first await: from this instant until the
    // backend answers, "no failure recorded" never means "nothing outstanding".
    this.announceRelease(handle, 'in-flight')
    const attempt = (async () => {
      try {
        await handle.release()
        this.releasedHandles.add(handle)
        this.announceRelease(handle, 'confirmed')
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error)
        this.announceRelease(handle, 'failed', reason)
        throw error
      } finally {
        this.releasing.delete(handle)
      }
    })()
    this.releasing.set(handle, attempt)
    return attempt
  }
  /** A release whose outcome this site cannot surface (it has its own error to throw, or dispose is
   * sync): the failure is recorded and the handle kept retryable — here it must not become an
   * unhandled rejection, which is not the same thing as swallowing it. */
  private standDownObserved(handle: AcpChannelHandle): Promise<void> {
    return this.releaseHandle(handle).catch(() => undefined)
  }

  /** The host's explicit retry entry point (the optional `AgentClient.retryReleases` member): one
   * pass over every OUTSTANDING release — an in-flight attempt is joined and awaited, a failed one
   * gets exactly one further attempt, a confirmed one is no longer in the ledger at all — and a
   * refusal propagates to the caller instead of looping or swallowing. Nothing is booked as
   * confirmed except the backend's own answer, announced via `subscribeReleaseStates`. It is
   * deliberately reachable after dispose(): the outstanding handles live in the ledger, not in
   * the cleared channel maps, and the bridge that stands them down is owned by the plugin's
   * scope, not by this client. */
  async retryReleases(): Promise<void> {
    let refusal: unknown
    for (const record of [...this.releaseLedger.values()]) {
      try { await this.releaseHandle(record.handle) }
      catch (error) { refusal ??= error }
    }
    if (refusal !== undefined) throw refusal
  }

  /** The project query locates the acquire; the CHANNEL handle's binding is the authority for
   * every cwd this client sends (reviewed seam: `handle.binding.normalizedPath` is the
   * `session/new` cwd). `openProject` runs first (an unoffered project throws `project-invalid`
   * before any channel or wire traffic), then exactly one `initialize`. */
  private async acquireAndInitialize(projectId: string): Promise<Channel> {
    const opened = await this.spec.openProject(projectId)
    if (!this.projects.some(item => item.id === opened.id)) this.projects.push(opened)
    const handle = await this.spec.acquireChannel(opened.id)
    // From here on, this attempt owns the handle: dispose() mid-handshake reaches it through
    // unownedHandles (it is not in `channels` yet), and whoever gets there first releases it once.
    this.unownedHandles.add(handle)
    // A handle bound to another project is stood down, never trusted for its path.
    if (handle.binding.id !== projectId) {
      this.unownedHandles.delete(handle)
      await this.standDownObserved(handle)
      throw new Error(`ACP channel moved the bound project: asked ${projectId}, bound ${handle.binding.id}`)
    }
    const binding = handle.binding
    if (this.isDisposed) {
      this.unownedHandles.delete(handle)
      await this.standDownObserved(handle)
      throw new Error('ACP connection disposed')
    }
    const channel: Channel = {
      projectId: binding.id, binding, handle,
      conn: undefined as unknown as acp.ClientSideConnection,
      capabilities: {}, nativeToKey: new Map(), commandsDown: false,
      creatingSessions: 0, pendingCommands: new Map(),
    }
    if (handle.subscribeDown) channel.unsubscribeDown = handle.subscribeDown(() => {
      channel.commandsDown = true
      this.invalidateChannelCommands(channel, 'channel-down')
    })
    const observedStream: acp.Stream = {
      ...handle.stream,
      readable: handle.stream.readable.pipeThrough(new TransformStream<acp.AnyMessage, acp.AnyMessage>({
        transform: (frame, controller) => {
          this.observeCommandFrame(channel, frame)
          controller.enqueue(frame)
        },
      })),
    }
    channel.conn = new acp.ClientSideConnection(() => ({
      sessionUpdate: async params => { this.onSessionUpdate(channel, params) },
      requestPermission: async params => this.onRequestPermission(channel, params),
    }), observedStream)
    try {
      const init = await channel.conn.initialize({ protocolVersion: acp.PROTOCOL_VERSION, clientCapabilities: {} })
      // Registration after a mid-initialize dispose would leave a live channel nobody owns.
      if (this.isDisposed) throw new Error('ACP connection disposed')
      channel.capabilities = init.agentCapabilities ?? {}
    } catch (error) {
      channel.unsubscribeDown?.()
      // The handshake error is the caller's; a failed release behind it stays recorded and retryable.
      await this.standDownObserved(handle)
      throw error
    } finally {
      this.unownedHandles.delete(handle)
    }
    this.channels.set(binding.id, channel)
    this.publishHistory()
    return channel
  }

  private publishHistory() {
    const supported = [...this.channels.values()].some(channel =>
      channel.capabilities.loadSession === true || channel.capabilities.sessionCapabilities?.list != null)
    const capabilities: AgentCapabilities = { ...this.state.connection.capabilities, history: supported ? 'supported' : 'unsupported' }
    this.publish({ connection: { ...this.state.connection, capabilities } })
  }

  // ——— per-channel session keying ————————————————————————————————————————

  /** Raw native id while it is unclaimed inside this client; channel-scoped once a second channel
   * mints the same id. Routing of every inbound event and outbound op goes through this map, so
   * two channels' same-named sessions never share messages, runs, approvals or cancels. */
  private keyFor(channel: Channel, nativeId: string): string {
    const known = channel.nativeToKey.get(nativeId)
    if (known) return known
    let key = nativeId
    if (this.routes.has(key)) key = `${channel.handle.connectionId}:${nativeId}`
    while (this.routes.has(key)) key = `${channel.handle.connectionId}:${nativeId}#${++this.sequence}`
    channel.nativeToKey.set(nativeId, key)
    this.routes.set(key, { channel, nativeId, key })
    return key
  }
  private routeOf(sessionKey: string): Route {
    const route = this.routes.get(sessionKey)
    if (!route) throw new Error(`ACP session unavailable: ${sessionKey}`)
    return route
  }

  private activateCommandSession(channel: Channel, key: string) {
    const connectionId = channel.handle.connectionId
    for (const [sessionKey, route] of this.routes) {
      if (route.channel === channel && sessionKey !== key)
        this.nativeCommands.set(sessionKey, Object.freeze({ kind: 'unknown', reason: 'stale-session' }))
    }
    this.activeCommandSession.set(connectionId, key)
    this.nativeCommands.delete(key)
    const nativeId = this.routes.get(key)?.nativeId
    const pending = nativeId === undefined ? undefined : channel.pendingCommands.get(nativeId)
    if (nativeId !== undefined && channel.pendingCommands.has(nativeId)) {
      channel.pendingCommands.delete(nativeId)
      this.nativeCommands.set(key, pending === null
        ? Object.freeze({ kind: 'unknown', reason: 'malformed' })
        : Object.freeze({ kind: 'available', connectionId, nativeSessionId: nativeId,
          commands: pending! }))
    }
  }

  private invalidateChannelCommands(channel: Channel, reason: 'channel-down' | 'malformed') {
    channel.pendingCommands.clear()
    for (const [key, route] of this.routes) if (route.channel === channel)
      this.nativeCommands.set(key, Object.freeze({ kind: 'unknown', reason }))
    this.publish()
  }

  /** Inspect the raw same-channel frame before the SDK's skip-invalid-items deserializer. */
  private observeCommandFrame(channel: Channel, frame: acp.AnyMessage) {
    const raw = frame && typeof frame === 'object' ? frame as unknown as Record<string, unknown> : null
    if (!raw) { this.invalidateChannelCommands(channel, 'malformed'); return }
    if (raw.method !== 'session/update') return
    const params = raw.params && typeof raw.params === 'object' && !Array.isArray(raw.params)
      ? raw.params as Record<string, unknown> : null
    const update = params?.update && typeof params.update === 'object' && !Array.isArray(params.update)
      ? params.update as Record<string, unknown> : null
    if (!update || typeof update.sessionUpdate !== 'string'
        || !KNOWN_SESSION_UPDATES.has(update.sessionUpdate)) {
      this.invalidateChannelCommands(channel, 'malformed')
      return
    }
    if (update.sessionUpdate !== 'available_commands_update') return
    const nativeId = params?.sessionId
    if (typeof nativeId !== 'string' || !nativeId) {
      this.invalidateChannelCommands(channel, 'malformed')
      return
    }
    const key = channel.nativeToKey.get(nativeId)
    const commands = parseNativeCommands(update)
    if (!key) {
      if (channel.creatingSessions > 0 && !channel.commandsDown) {
        // A native Agent may publish its catalog before session/new replies. Keep only a bounded
        // same-channel candidate; it is promoted solely for the native id returned by that reply.
        if (!channel.pendingCommands.has(nativeId) && channel.pendingCommands.size >= 8)
          channel.pendingCommands.delete(channel.pendingCommands.keys().next().value!)
        channel.pendingCommands.set(nativeId, commands)
      }
      return
    }
    if (this.activeCommandSession.get(channel.handle.connectionId) !== key) return
    this.nativeCommands.set(key, commands === null
      ? Object.freeze({ kind: 'unknown', reason: 'malformed' })
      : Object.freeze({ kind: 'available', connectionId: channel.handle.connectionId,
        nativeSessionId: nativeId, commands }))
    this.publish()
  }

  // ——— AgentClient surface ————————————————————————————————————————————————

  async openWorkspace(id: string): Promise<AgentWorkspaceInfo> {
    const channel = await this.ensureChannel(id)
    this.selectedWorkspaceId = id
    this.publish()
    return channel.binding
  }

  async refreshWorkspaces(): Promise<void> {
    const projects = await this.spec.listProjects()
    this.projects.splice(0, this.projects.length, ...projects)
    this.publish()
  }

  private selectedChannelId(): string {
    const id = this.selectedWorkspaceId
    if (!id) throw new Error('ACP project gate: no project is bound')
    return id
  }

  private async createNativeSession(channel: Channel) {
    channel.creatingSessions += 1
    let returnedId: string | undefined
    try {
      const created = await channel.conn.newSession({ cwd: channel.binding.normalizedPath, mcpServers: [] })
      returnedId = created.sessionId
      return created
    } finally {
      channel.creatingSessions -= 1
      if (channel.creatingSessions === 0) {
        for (const nativeId of channel.pendingCommands.keys())
          if (nativeId !== returnedId) channel.pendingCommands.delete(nativeId)
      }
    }
  }

  /** First send of a draft: lazily create the native session under the channel's authoritative cwd,
   * prompt once, and resolve on acceptance — session created + first send accepted by the Harness,
   * NOT the whole turn (R27). An unknown outcome rejects; the caller keeps its requestId. */
  async createAndSend(workspaceId: string, text: string, requestId: string): Promise<{ sessionId: string }> {
    this.assertLive()
    void requestId // the ACP wire carries no client request id; idempotence is held by the caller until acceptance
    const channel = await this.ensureChannel(workspaceId)
    const created = await this.createNativeSession(channel)
    const nativeId = created.sessionId
    const key = this.keyFor(channel, nativeId)
    this.activateCommandSession(channel, key)
    this.upsertSession({ id: key, title: 'New session', workspaceId: channel.binding.id })
    this.selectedWorkspaceId = workspaceId
    this.appendMessage(key, { id: this.nextId('user'), role: 'user', text })
    const acceptance = this.holdAcceptance(channel, nativeId)
    const turn = this.startTurn(channel, key, nativeId, text)
    try { await acceptance.promise }
    catch (error) { void turn.catch(() => undefined); throw error }
    return { sessionId: key }
  }

  async newSession(): Promise<string> {
    const projectId = this.selectedChannelId()
    const channel = await this.ensureChannel(projectId)
    const created = await this.createNativeSession(channel)
    const key = this.keyFor(channel, created.sessionId)
    this.activateCommandSession(channel, key)
    this.upsertSession({ id: key, title: 'New session', workspaceId: projectId })
    this.publish({ selectedSessionId: key })
    return key
  }

  async refreshSessions(): Promise<void> {
    this.assertLive()
    const listable = [...this.channels.values()].filter(channel => channel.capabilities.sessionCapabilities?.list != null)
    if (!listable.length) {
      // Two different facts share this branch. NO channel bound is not a history failure — there is
      // simply no Harness to ask yet (the project gate blocks sends meanwhile), so the honest answer
      // is the state unchanged, not an error banner. A bound Harness that does not list IS the real
      // capability refusal, and stays an error.
      if (!this.channels.size) return
      this.sessionList.state = 'error'
      this.publish()
      throw new Error('ACP history: this Harness does not list sessions')
    }
    // The name version is claimed when the request is ISSUED, exactly like the background pull:
    // any name write issued after this refresh retires its answer, however late it lands.
    const seq = ++this.nameWrites
    this.sessionList.state = 'loading'
    this.publish()
    try {
      const listed = await Promise.all(listable.map(async channel => ({
        channel, sessions: (await channel.conn.listSessions({})).sessions,
      })))
      const mapped: AgentSessionInfo[] = listed.flatMap(({ channel, sessions }) => sessions.map(session => {
        const key = this.keyFor(channel, session.sessionId)
        const project = this.projects.find(item => item.normalizedPath === session.cwd)
        return {
          id: key, title: session.title ?? 'Session',
          ...(session.updatedAt ? { updatedAt: session.updatedAt } : {}),
          workspaceId: project?.id,
        }
      }))
      // A merge, never a wholesale overwrite: each entry lands only while no newer name write has
      // claimed its session. Locally known sessions the list does not carry yet stay visible.
      for (const entry of mapped) {
        if ((this.nameApplied.get(entry.id) ?? 0) >= seq) continue
        this.nameApplied.set(entry.id, seq)
        this.upsertSession(entry)
      }
      this.sessionList.state = 'ready'
    } catch (error) {
      this.sessionList.state = 'error'
      this.publish()
      throw error
    }
    this.publish()
  }

  /** List and load are different capabilities: an id never seen in a list is still loadable when the
   * wire allows it (R26); a refusal comes back as the wire's own error, never a fabricated success. */
  async openSession(id: string): Promise<void> {
    const known = this.routes.get(id)
    const channel = known?.channel ?? await this.ensureChannel(this.selectedChannelId())
    const nativeId = known?.nativeId ?? id
    const key = this.keyFor(channel, nativeId)
    await channel.conn.loadSession({ sessionId: nativeId, cwd: channel.binding.normalizedPath, mcpServers: [] })
    this.activateCommandSession(channel, key)
    this.upsertSession({ id: key, title: this.sessionTitle(key) ?? 'Session', workspaceId: channel.binding.id })
    this.publish({ selectedSessionId: key })
  }

  async send(sessionId: string, text: string): Promise<void> {
    const route = this.routeOf(sessionId)
    this.appendMessage(sessionId, { id: this.nextId('user'), role: 'user', text })
    await this.startTurn(route.channel, route.key, route.nativeId, text)
  }

  private attachmentTarget(route: Route): AcpAttachmentTarget {
    return { serverInstanceId: this.spec.serverInstanceId, connectionId: route.channel.handle.connectionId,
      projectId: route.channel.projectId, nativeSessionId: route.nativeId }
  }

  private attachmentRouteLive(route: Route, sessionId: string): boolean {
    return !this.isDisposed && !route.channel.commandsDown
      && this.channels.get(route.channel.projectId) === route.channel
      && this.routes.get(sessionId) === route
      && this.state.selectedSessionId === sessionId
      && this.activeCommandSession.get(route.channel.handle.connectionId) === sessionId
  }

  private validAttachmentCapabilities(caps: AcpAttachmentCapabilities): boolean {
    if (caps?.kind === 'available') return Number.isSafeInteger(caps.maxBytes) && caps.maxBytes > 0
      && Number.isSafeInteger(caps.maxCount) && caps.maxCount > 0
      && Array.isArray(caps.mimeTypes) && caps.mimeTypes.length > 0
      && caps.mimeTypes.every(item => typeof item === 'string' && !!item)
      && Array.isArray(caps.uriSchemes) && caps.uriSchemes.length > 0
      && caps.uriSchemes.every(item => typeof item === 'string' && /^[a-z][a-z0-9+.-]*:$/.test(item) && item !== 'file:')
    return (caps?.kind === 'absent' || caps?.kind === 'unknown') && typeof caps.reason === 'string' && !!caps.reason
  }

  async attachmentCapabilities(sessionId: string): Promise<AcpAttachmentCapabilities> {
    const route = this.routeOf(sessionId)
    const port = route.channel.handle.attachmentPrepare
    if (!port || route.channel.commandsDown) return { kind: 'absent', reason: 'attachment preparation owner unavailable' }
    try {
      const caps = await port.capabilities(this.attachmentTarget(route))
      if (!this.attachmentRouteLive(route, sessionId) || !this.validAttachmentCapabilities(caps))
        return { kind: 'unknown', reason: 'attachment capability owner changed or malformed' }
      return caps
    }
    catch { return { kind: 'unknown', reason: 'attachment capability outcome unknown' } }
  }

  async prepareAttachment(sessionId: string, sourceId: string, idempotencyKey: string): Promise<AcpPreparedAttachment> {
    const route = this.routeOf(sessionId)
    const port = route.channel.handle.attachmentPrepare
    if (!port || route.channel.commandsDown || !sourceId || !idempotencyKey)
      throw new Error('ACP attachment preparation unavailable')
    const target = this.attachmentTarget(route)
    const caps = await this.attachmentCapabilities(sessionId)
    if (caps.kind !== 'available') throw new Error(`ACP attachment capability ${caps.kind}`)
    const result = await port.prepare(target, sourceId, idempotencyKey)
    if (!this.attachmentRouteLive(route, sessionId)) {
      if (result.kind === 'prepared' && validPreparedReference(result.reference)) {
        try { await port.release(target, result.reference.preparedId) }
        catch { throw new Error('ACP attachment preparation cleanup unknown') }
      }
      throw new Error('ACP attachment preparation owner changed')
    }
    if (result.kind === 'unknown') throw new Error(`ACP attachment preparation unknown: ${result.operationId}`)
    if (result.kind !== 'prepared' || !validPreparedReference(result.reference)
      || result.reference.byteLength > caps.maxBytes || !caps.mimeTypes.includes(result.reference.mimeType)
      || !caps.uriSchemes.includes(referenceScheme(result.reference.uri) ?? ''))
      throw new Error('ACP attachment preparation refused or malformed')
    return Object.freeze({ ...result.reference })
  }

  async releasePreparedAttachment(sessionId: string, preparedId: string): Promise<void> {
    const route = this.routeOf(sessionId)
    const port = route.channel.handle.attachmentPrepare
    if (!port || !preparedId) throw new Error('ACP attachment release unavailable')
    await port.release(this.attachmentTarget(route), preparedId)
  }

  /** Next-submit attachment/command path through this channel's existing ACP client.
   * A backend admission refusal or uncertain result sends zero prompt frames. This is an
   * explicit controlled surface while legacy AgentClient.send remains available; Server
   * relay enforcement is required before it can be called a production C5 gate.
   */
  async sendControlled(sessionId: string, submission: AcpControlledSubmission): Promise<void> {
    this.assertLive()
    const route = this.routeOf(sessionId)
    validateControlledSubmission(submission)
    // Caller-owned DTOs are mutable at runtime despite readonly TypeScript fields. Freeze the
    // values before the first await so authorization and ACP bytes describe one submission.
    const frozen: AcpControlledSubmission = { ...submission,
      attachments: submission.attachments.map(item => ({ ...item })) }
    if (frozen.nativeSessionId !== route.nativeId) throw new Error('ACP submission session changed')
    if (this.usedControlledSubmissionIds.has(frozen.submissionId))
      throw new Error('ACP submission identity already used')
    if (this.pendingControlledSessions.has(route.key))
      throw new Error('ACP session already pending controlled admission')
    if (this.openRunOf(route.key)) throw new Error('ACP session is already outputting')
    const authorize = route.channel.handle.authorizeSubmission
    if (!authorize) throw new Error('ACP backend submission admission unavailable')
    if (!route.channel.handle.subscribeDown) throw new Error('ACP channel liveness unobservable')
    if (route.channel.commandsDown || this.channels.get(route.channel.projectId) !== route.channel)
      throw new Error('ACP channel owner gone or down')
    if (this.state.selectedSessionId !== sessionId
        || this.activeCommandSession.get(route.channel.handle.connectionId) !== sessionId)
      throw new Error('ACP submission session changed')
    this.usedControlledSubmissionIds.add(frozen.submissionId)
    this.pendingControlledSessions.add(route.key)
    try {
      if (frozen.attachments.length) {
        const port = route.channel.handle.attachmentPrepare
        if (!port) throw new Error('ACP attachment preparation owner unavailable')
        const target = this.attachmentTarget(route)
        const caps = await this.attachmentCapabilities(sessionId)
        if (caps.kind !== 'available' || frozen.attachments.length > caps.maxCount
          || !Number.isSafeInteger(caps.maxBytes) || caps.maxBytes <= 0)
          throw new Error('ACP attachment capability unavailable or exceeded')
        const ids = new Set<string>()
        for (const item of frozen.attachments) {
          if (!validPreparedReference(item) || ids.has(item.preparedId)
            || item.byteLength > caps.maxBytes || !caps.mimeTypes.includes(item.mimeType)
            || !caps.uriSchemes.includes(referenceScheme(item.uri) ?? ''))
            throw new Error('ACP attachment reference invalid or unsupported')
          ids.add(item.preparedId)
          const verification = await port.verify(target, item)
          if (verification.kind === 'unknown') throw new Error(`ACP attachment verification unknown: ${verification.operationId}`)
          if (verification.kind !== 'verified' || !validPreparedReference(verification.reference)
            || !samePreparedReference(item, verification.reference))
            throw new Error('ACP attachment ownership or content changed')
          if (!this.attachmentRouteLive(route, sessionId)) throw new Error('ACP attachment owner changed')
        }
      }
      if (!this.attachmentRouteLive(route, sessionId)) throw new Error('ACP attachment owner changed')
      const admission = await authorize({ ...frozen, attachments: frozen.attachments.map(item => ({ ...item })) })
      if (admission.kind === 'refused') throw new Error(`ACP submission refused: ${admission.code}: ${admission.reason}`)
      if (admission.kind === 'unknown') throw new Error(`ACP submission outcome unknown: ${admission.operationId}`)
      if (admission.kind !== 'accepted' || admission.submissionId !== frozen.submissionId) {
        throw new Error('ACP submission admission identity changed')
      }
      // An accepted backend decision authorizes only the owner state observed at admission.
      // Session selection, another run, release and transport death can all change while awaited.
      if (this.isDisposed || route.channel.commandsDown
          || this.channels.get(route.channel.projectId) !== route.channel
          || this.routes.get(sessionId) !== route)
        throw new Error('ACP channel owner gone or down')
      if (this.state.selectedSessionId !== sessionId
          || this.activeCommandSession.get(route.channel.handle.connectionId) !== sessionId)
        throw new Error('ACP submission session changed')
      if (this.openRunOf(route.key)) throw new Error('ACP session is already outputting')
      const blocks: acp.ContentBlock[] = [
        { type: 'text', text: frozen.text },
        ...frozen.attachments.map(item => ({ type: 'resource_link' as const, name: item.name,
          uri: item.uri, ...(item.mimeType ? { mimeType: item.mimeType } : {}) })),
      ]
      this.appendMessage(sessionId, { id: this.nextId('user'), role: 'user', text: frozen.text })
      await this.startTurn(route.channel, route.key, route.nativeId, frozen.text, blocks)
    } finally {
      this.pendingControlledSessions.delete(route.key)
    }
  }

  async stop(sessionId: string, runId: string): Promise<void> {
    this.assertLive()
    const run = this.runs.get(runId)
    const route = this.routeOf(sessionId)
    // The cancel targets a session, not a run: a foreign runId under this sessionId, or a run
    // that already settled, would flip the wrong status and silently cancel a live turn on the
    // named session. Everything is validated before any mutation, so a wrong call cancels zero.
    if (!run || run.sessionId !== route.key || !OPEN_RUN(run.status)) throw new Error('Agent run unavailable')
    // `session/cancel` is a bare notification: the request is only requested, never confirmed here.
    run.status = 'stop-requested'
    // From this synchronous instant the run's open asks are un-submittable at the entry — and a
    // cancel send that fails below must NOT quietly re-open them: an answer already 'resolved'
    // stays a delivered wire fact (never pretended back), a 'pending' one strands as unknown.
    this.strandPendingInteractions(route.key)
    this.publish()
    await route.channel.conn.cancel({ sessionId: route.nativeId })
  }

  async respond(interactionId: string, answer: InteractionAnswer): Promise<void> {
    const record = this.interactions.get(interactionId)
    if (!record || record.item.state !== 'pending') throw new Error(`ACP interaction unavailable: ${interactionId}`)
    // The button is not the gate: an answer belongs to the very run that received this request,
    // not to "whatever this session runs now" — a late ask from a settled or stopped run is
    // refused even while a newer turn is live, and nothing goes out on the wire.
    const run = record.runId === '' ? undefined : this.runs.get(record.runId)
    if (!run || run.status !== 'running') throw new Error(`ACP interaction unavailable: the agent run is no longer answering: ${interactionId}`)
    let outcome: acp.RequestPermissionOutcome
    if (answer.kind === 'cancel') outcome = { outcome: 'cancelled' }
    else if (answer.kind === 'choice') {
      const choice = record.item.choices?.find(item => item.id === answer.choiceId)
      // The native optionId answers the wire; a foreign option never does, and the request stays pending.
      if (!choice) throw new Error(`ACP answer option is not part of this request: ${answer.choiceId}`)
      outcome = { outcome: 'selected', optionId: choice.id }
    } else throw new Error('ACP permission requests are answered with a native option or a cancel')
    record.item.state = 'responding'
    this.publish()
    record.settle({ outcome })
    record.item.state = 'resolved'
    this.publish()
  }

  /** Opt-in execution-time answer path. The native ACP option is sent only after the backend
   * accepts this exact channel/session/run/interaction/option; missing authority fails closed.
   * Legacy `respond` remains until the Server relay enforces the same decision for every path.
   */
  async respondControlled(interactionId: string, answer: InteractionAnswer): Promise<void> {
    this.assertLive()
    const record = this.interactions.get(interactionId)
    if (!record || record.item.state !== 'pending' || answer.kind !== 'choice') {
      throw new Error('ACP controlled permission needs a pending native choice')
    }
    if (!record.item.choices?.some(choice => choice.id === answer.choiceId)) {
      throw new Error('ACP answer option is not part of this request')
    }
    const route = this.routeOf(record.item.sessionId)
    const choiceId = answer.choiceId
    const authorize = route.channel.handle.authorizePermission
    if (!authorize) throw new Error('ACP backend permission admission unavailable')
    const admission = await authorize({ nativeSessionId: route.nativeId, interactionId,
      runId: record.runId, optionId: choiceId })
    if (admission.kind === 'refused') throw new Error(`ACP permission refused: ${admission.code}: ${admission.reason}`)
    if (admission.kind === 'unknown') throw new Error(`ACP permission outcome unknown: ${admission.operationId}`)
    if (admission.kind !== 'accepted' || admission.submissionId !== interactionId) {
      throw new Error('ACP permission admission identity changed')
    }
    await this.respond(interactionId, { kind: 'choice', choiceId }) // rechecks current run
  }

  async setOption(id: string, value: string): Promise<void> {
    void id; void value
    throw new Error('ACP options are managed by the Harness session state, not this client')
  }

  /** Explicit lifecycle release: view switches and transport drops never reach here (R23/R13). */
  dispose(): void {
    if (this.isDisposed) return
    this.isDisposed = true
    for (const acceptance of this.firstSends.values()) acceptance.fail(new Error('ACP connection disposed'))
    this.firstSends.clear()
    for (const run of this.runs.values()) if (OPEN_RUN(run.status)) run.status = 'unknown'
    for (const record of this.interactions.values()) if (record.item.state === 'pending') record.item.state = 'unknown'
    // dispose() is sync: a failed release stays recorded in `releaseFailures` and stays retryable
    // through `retryReleases()` — this is the one caller that cannot await the outcome, and a
    // second dispose() is blocked by isDisposed, so the host entry point is not incidental.
    for (const channel of this.channels.values()) void this.standDownObserved(channel.handle)
    // Handles whose acquire/initialize is still in flight: dispose owns them too, or the late
    // arrival would be a backend channel nobody can ever release.
    for (const handle of this.unownedHandles) void this.standDownObserved(handle)
    this.unownedHandles.clear()
    for (const channel of this.channels.values()) channel.unsubscribeDown?.()
    this.channels.clear()
    // `opening` is deliberately NOT cleared: an in-flight acquire may still land a handle after
    // this returns, and its stand-down must count as outstanding until the task itself finishes
    // (ensureChannel's finally) — that is what `releasesSettled` attests.
    this.maybeDrainReleases()
    this.state = {
      ...this.state,
      connection: { ...this.state.connection, status: 'disconnected' },
      runs: Object.fromEntries(this.runs),
      interactions: [...this.interactions.values()].map(record => record.item),
    }
    for (const listener of [...this.listeners]) listener()
  }

  // ——— turn execution —————————————————————————————————————————————————————

  /** Registers the run before the request leaves (R27: accepted mid-flight runs are observable as
   * 'running'), settles it only from the prompt's own stopReason, and verdicts 'unknown' — never a
   * fake 'cancelled' — when the link dies (R13/U5). A session's projection carries its current
   * run: a new turn supersedes that session's settled verdict, never two live runs per session
   * (ACP allows one in-flight prompt per session), so R17's read of "the session's run" is the
   * turn it just sent, not the previous turn's history. */
  private startTurn(channel: Channel, key: string, nativeId: string, text: string,
                    blocks: acp.ContentBlock[] = [{ type: 'text', text }]): Promise<acp.PromptResponse> {
    const runId = this.nextId('run')
    this.closeStream(key) // a new turn's stream never continues the previous turn's last card
    for (const [id, run] of this.runs) if (run.sessionId === key && !OPEN_RUN(run.status)) this.runs.delete(id)
    this.runs.set(runId, { id: runId, sessionId: key, status: 'running' })
    this.publish({ selectedSessionId: key })
    const turn = channel.conn.prompt({ sessionId: nativeId, prompt: blocks }).then(
      response => {
        this.accept(channel, nativeId)
        this.finishTurn(runId, key, STOP_REASON[response.stopReason] ?? 'unknown')
        return response
      },
      error => {
        this.accept(channel, nativeId, error)
        this.finishTurn(runId, key, 'unknown')
        throw error
      },
    )
    void turn.catch(() => undefined) // the caller's copy carries the rejection; the internal one must not go unhandled
    return turn
  }

  private finishTurn(runId: string, key: string, status: RunStatus) {
    this.closeStream(key) // the turn's verdict closes its stream: no chunk may append after the stop
    const run = this.runs.get(runId)
    if (run) run.status = status
    for (const message of this.buckets.get(key) ?? []) {
      if (message.status && OPEN_RUN(message.status)) this.mutateMessage(key, message.id, m => { m.status = status })
    }
    // A closed turn strands every ask it was holding — on ANY verdict, not just a dead link:
    // cancelled or completed leaves no submittable approval behind.
    this.strandPendingInteractions(key)
    // `session/new` carries no title; the native name lives in `session/list`. Pull it once the
    // turn settled (that is when the Harness has one) — the only name authority this client uses.
    const route = this.routes.get(key)
    if (route) this.pullNativeTitle(route)
    this.publish()
  }

  /** The run of this session key that is still open (ACP allows at most one in-flight prompt per
   * session, so at most one exists); approvals are answerable only while it is 'running'. */
  private openRunOf(sessionKey: string) {
    for (const run of this.runs.values()) {
      if (run.sessionId === sessionKey && OPEN_RUN(run.status)) return run
    }
    return undefined
  }
  private strandPendingInteractions(sessionKey: string) {
    for (const record of this.interactions.values()) {
      if (record.item.sessionId === sessionKey && record.item.state === 'pending') record.item.state = 'unknown'
    }
  }
  /** A background name pull through the channel's EXISTING list capability. It never blocks or
   * fails a turn: an absent name or an unanswered list leaves the current title exactly as it is
   * — no model naming, no summary substitution, nothing invented. */
  private pullNativeTitle(route: Route) {
    if (route.channel.capabilities.sessionCapabilities?.list == null) return
    // Issued NOW: whatever claims this session's name after this point outranks this answer,
    // no matter which of the two comes back first.
    const seq = ++this.nameWrites
    void (async () => {
      try {
        const listed = await route.channel.conn.listSessions({})
        const match = listed.sessions.find(session => session.sessionId === route.nativeId)
        if (!match?.title) return
        // Title-only merge: the local entry owns workspaceId and history; the list only names it.
        const existing = this.sessionList.items.find(item => item.id === route.key)
        if (!existing) return
        if ((this.nameApplied.get(route.key) ?? 0) >= seq) return // a newer write already landed
        this.nameApplied.set(route.key, seq)
        this.upsertSession({
          id: route.key, title: match.title,
          ...(match.updatedAt ? { updatedAt: match.updatedAt } : {}),
        })
        this.publish()
      } catch {
        // A failed pull is an absence of evidence, not evidence of absence: the title stands.
      }
    })()
  }

  // ——— first-send acceptance ———————————————————————————————————————————————

  private holdAcceptance(channel: Channel, nativeId: string): FirstSend & { promise: Promise<void> } {
    const slot = `${channel.projectId}|${nativeId}`
    let settle!: () => void
    let fail!: (error: unknown) => void
    const promise = new Promise<void>((resolve, reject) => { settle = resolve; fail = reject })
    const acceptance: FirstSend & { promise: Promise<void> } = {
      promise,
      settle: () => { this.firstSends.delete(slot); settle() },
      fail: error => { this.firstSends.delete(slot); fail(error) },
    }
    this.firstSends.set(slot, acceptance)
    return acceptance
  }
  /** Any inbound event naming the native session — an update, a reverse request, or the response —
   * is the proof the Harness accepted the first send. */
  private accept(channel: Channel, nativeId: string, failure?: unknown) {
    const acceptance = this.firstSends.get(`${channel.projectId}|${nativeId}`)
    if (!acceptance) return
    if (failure === undefined) acceptance.settle()
    else acceptance.fail(failure)
  }

  // ——— session/message projection —————————————————————————————————————————

  /** Name-write ordering: every title write claims a fresh sequence at ISSUE time; a background
   * list result commits only while its issue still outranks the last applied claim for that key.
   * Whichever write was issued LAST wins — arrival order can never roll a newer name back. */
  private nameWrites = 0
  private readonly nameApplied = new Map<string, number>()
  private claimSessionName(key: string) { this.nameApplied.set(key, ++this.nameWrites) }
  private sessionTitle(key: string): string | undefined {
    return this.sessionList.items.find(item => item.id === key)?.title
  }
  private upsertSession(session: AgentSessionInfo) {
    const at = this.sessionList.items.findIndex(item => item.id === session.id)
    if (at >= 0) this.sessionList.items[at] = { ...this.sessionList.items[at], ...session }
    else this.sessionList.items.push(session)
  }
  private appendMessage(key: string, message: AgentMessage) {
    const bucket = this.buckets.get(key) ?? []
    this.buckets.set(key, [...bucket, message])
    this.publish({ selectedSessionId: key })
  }
  private mutateMessage(key: string, messageId: string, edit: (message: AgentMessage) => void) {
    const bucket = this.buckets.get(key) ?? []
    this.buckets.set(key, bucket.map(message => {
      if (message.id !== messageId) return message
      const copy = { ...message }
      edit(copy)
      return copy
    }))
  }
  /** The message a chunk belongs to: by native messageId when the Harness names one (never split,
   * R8), else the session's open chunkless stream — created once and accumulated into until a
   * turn or tool boundary closes it. */
  private chunkMessage(key: string, messageId: string | undefined, role: 'user' | 'assistant'): AgentMessage {
    const bucket = this.buckets.get(key) ?? []
    if (messageId) {
      // An id-bearing chunk is always a different message than the open chunkless stream, so the
      // slot closes here: without it, no-id A → id B → no-id C would append C to A.
      this.closeStream(key)
      const existing = bucket.find(message => message.id === messageId)
      if (existing) return existing
      const created: AgentMessage = {
        id: messageId, role, text: '',
        ...(role === 'assistant' ? { status: 'running' as RunStatus } : {}),
      }
      this.buckets.set(key, [...bucket, created])
      return created
    }
    const open = this.openStreams.get(key)
    if (open && open.role === role) {
      const found = bucket.find(message => message.id === open.id)
      if (found) return found
    }
    const created: AgentMessage = {
      id: this.nextId('message'), role, text: '',
      ...(role === 'assistant' ? { status: 'running' as RunStatus } : {}),
    }
    this.buckets.set(key, [...bucket, created])
    this.openStreams.set(key, { id: created.id, role })
    return created
  }
  /** A turn or tool event proves the open chunkless stream ended; the next chunk opens its own card. */
  private closeStream(key: string) { this.openStreams.delete(key) }
  private textOf(content: acp.ContentBlock): string {
    return content.type === 'text' ? content.text : ''
  }

  private onSessionUpdate(channel: Channel, params: acp.SessionNotification) {
    if (this.isDisposed) return
    if (params.update.sessionUpdate === 'available_commands_update') {
      if (channel.nativeToKey.has(params.sessionId)) this.accept(channel, params.sessionId)
      return // The raw frame tap validates the entire list before SDK filtering.
    }
    const key = this.keyFor(channel, params.sessionId)
    this.accept(channel, params.sessionId)
    const update = params.update
    switch (update.sessionUpdate) {
      case 'agent_message_chunk': {
        const message = this.chunkMessage(key, update.messageId ?? undefined, 'assistant')
        this.mutateMessage(key, message.id, m => { m.text += this.textOf(update.content) })
        break
      }
      case 'agent_thought_chunk': {
        const message = this.chunkMessage(key, update.messageId ?? undefined, 'assistant')
        this.mutateMessage(key, message.id, m => { m.reasoning = (m.reasoning ?? '') + this.textOf(update.content) })
        break
      }
      case 'user_message_chunk': {
        const message = this.chunkMessage(key, update.messageId ?? undefined, 'user')
        this.mutateMessage(key, message.id, m => { m.text += this.textOf(update.content) })
        break
      }
      case 'tool_call':
      case 'tool_call_update':
        this.upsertTool(key, update)
        break
      case 'session_info_update':
        if (update.title) {
          // A live rename arrives with the newest knowledge: it claims the name immediately,
          // retiring any name pull still in flight.
          this.claimSessionName(key)
          this.upsertSession({ id: key, title: update.title })
        }
        break
      default:
        return // plan/usage/mode/commands updates have no slot in this product's snapshot yet
    }
    this.publish()
  }

  /** One `toolCallId`, one card (R10/R11): updates find the card by id wherever it lives in the
   * bucket; a never-seen id opens its own assistant message carrying the card. Any tool event also
   * ends the open chunkless stream — text before and after a tool call is independent content. */
  private upsertTool(key: string, update: acp.ToolCall | acp.ToolCallUpdate) {
    this.closeStream(key)
    const bucket = this.buckets.get(key) ?? []
    const cardAt = bucket.findIndex(message => message.tools?.some(tool => tool.id === update.toolCallId))
    if (cardAt >= 0) {
      const message = bucket[cardAt]
      const tools = (message.tools ?? []).map(tool => tool.id === update.toolCallId ? this.mergeTool(tool, update) : tool)
      this.buckets.set(key, bucket.map((item, index) => index === cardAt ? { ...item, tools } : item))
      return
    }
    const card = this.mergeTool({ id: update.toolCallId, name: 'title' in update && update.title ? update.title : 'Tool call', status: 'running' }, update)
    this.buckets.set(key, [...bucket, {
      id: update.toolCallId, role: 'assistant' as const, text: '', status: 'running' as RunStatus, tools: [card],
    }])
  }
  private mergeTool(tool: AgentToolCall, update: acp.ToolCall | acp.ToolCallUpdate): AgentToolCall {
    const title = 'title' in update ? update.title : undefined
    const result = this.toolResult(update)
    const rawInput = 'rawInput' in update ? update.rawInput : undefined
    return {
      ...tool,
      ...(title ? { name: title } : {}),
      ...(update.status ? { status: TOOL_STATUS[update.status] ?? 'unknown' } : {}),
      ...(result !== undefined ? { result } : {}),
      ...(rawInput !== undefined ? { arguments: rawInput } : {}),
    }
  }
  /** Tool content arrives as blocks; the UI shows `String(result)`, so flatten text out of them
   * (R10: '3 passed' must be readable, not '[object Object]'). */
  private toolResult(update: acp.ToolCall | acp.ToolCallUpdate): string | undefined {
    const items = update.content
    if (!items?.length) return undefined
    return items.map(item => {
      if (item.type === 'content') return this.textOf(item.content)
      if (item.type === 'diff') return `${item.path}\n${item.oldText ?? ''} → ${item.newText}`
      return JSON.stringify(item)
    }).join('\n')
  }

  // ——— reverse requests (approvals) ————————————————————————————————————————

  /** Interactions are keyed by the native request, never by an option it carries (R14); the answer
   * goes back as the wire's own optionId. */
  private onRequestPermission(channel: Channel, params: acp.RequestPermissionRequest): Promise<acp.RequestPermissionResponse> {
    if (this.isDisposed) return Promise.reject(new Error('ACP connection disposed'))
    const key = this.keyFor(channel, params.sessionId)
    const id = this.nextId('perm')
    // Ownership binds at arrival: the run live RIGHT NOW is the only one that may ever accept the
    // answer. An ask that lands while its turn has already settled or already been stopped has no
    // accepting run — it is projected already-stranded, never as a submittable pending.
    const run = this.openRunOf(key)
    const item: AgentInteraction = {
      id, sessionId: key, kind: 'approval',
      title: params.toolCall.title ?? 'Permission request',
      choices: params.options.map(option => ({ id: option.optionId, label: option.name })),
      state: run?.status === 'running' ? 'pending' : 'unknown',
    }
    return new Promise<acp.RequestPermissionResponse>(resolve => {
      this.interactions.set(id, { item, settle: resolve, runId: run?.id ?? '' })
      this.accept(channel, params.sessionId)
      this.publish({ selectedSessionId: this.state.selectedSessionId ?? key })
    })
  }
}
