// In-memory AgentSessions fixture for Chat UI tests. It reproduces exactly the
// facade surface Chat consumes (snapshot subscription, draft gate, send
// semantics incl. deferred resolvable promises) — no real server, no ACP.
// Scripted failures drive refused/unknown/stale-response counterexamples (X06:
// fixture data only ever carries fields the real service provides — no
// invented command/diff metadata).
import type {
  AgentInteraction, AgentMessage, AgentSessionInfo, AgentSessions, AgentSnapshot, AgentWorkspaceInfo, AgentWorkspaceSnapshot,
  InteractionAnswer, RunStatus,
} from '@extensions/ordessa.agent-contracts/contract.js'

export interface FacadeOptions {
  connectionStatus?: 'disconnected' | 'connecting' | 'connected' | 'error'
  workspaces?: readonly AgentWorkspaceInfo[]
  selectedWorkspaceId?: string
  workspaceSupport?: 'supported' | 'unsupported' | 'unknown' | 'unavailable'
  sessions?: readonly AgentSessionInfo[]
  selectedSessionId?: string
  messages?: Readonly<Record<string, readonly AgentMessage[]>>
  interactions?: readonly AgentInteraction[]
  run?: { id: string; sessionId: string; status: RunStatus }
  canSendSupported?: boolean
  blockReason?: 'unsupported' | 'no-project' | 'project-invalid'
}

export class FacadeFixture implements AgentSessions {
  private listeners = new Set<() => void>()
  private base: AgentWorkspaceSnapshot
  draftActive = false
  draftEndedBy: 'discarded' | 'opened' | undefined
  sendBehavior: (send: { text: string }) => Promise<void> = async () => {}
  stopped: string[] = []
  respondError: Error | undefined
  responded: { id: string; answer: InteractionAnswer }[] = []
  startDraftCalls = 0
  discardDraftCalls = 0
  selectedWorkspaces: string[] = []

  constructor(options: FacadeOptions = {}) {
    const workspaces = options.workspaces ?? []
    this.base = {
      available: [{ id: 'conn-1', title: '本地服务' }],
      selectedConnectionId: 'conn-1',
      agent: {
        connection: { id: 'conn-1', title: '本地服务', status: options.connectionStatus ?? 'connected',
          capabilities: { history: 'supported', reasoning: 'supported', tools: 'supported', stop: 'supported',
            interactions: 'supported', models: 'unsupported', modes: 'unsupported',
            ...(options.workspaceSupport ? { workspaces: options.workspaceSupport } : {}) } },
        sessions: options.sessions ?? [],
        sessionList: 'ready',
        selectedSessionId: options.selectedSessionId,
        messages: options.messages ?? {},
        runs: options.run ? { [options.run.id]: { ...options.run } } : {},
        interactions: options.interactions ?? [],
        options: [],
        workspaces: { state: 'ready', items: workspaces, selectedWorkspaceId: options.selectedWorkspaceId },
      },
      draft: undefined,
    }
  }

  selectSession(id: string): void {
    this.base = { ...this.base, agent: this.base.agent && { ...this.base.agent, selectedSessionId: id } }
    this.emit()
  }

  private version = 0
  private cached: { version: number; derived: AgentWorkspaceSnapshot } | null = null
  private touch(): void { this.version++ }

  private derive(): AgentWorkspaceSnapshot {
    if (this.cached && this.cached.version === this.version) return this.cached.derived
    const supported = this.base.agent?.connection.capabilities.workspaces === 'supported'
    const block = !supported ? 'unsupported' as const
      : !this.base.agent?.workspaces?.selectedWorkspaceId ? 'no-project' as const : undefined
    const derived: AgentWorkspaceSnapshot = { ...this.base, draft: {
      active: this.draftActive,
      workspaceId: this.base.agent?.workspaces?.selectedWorkspaceId,
      canSend: block === undefined,
      ...(this.draftActive && block ? { blockReason: block } : {}),
      ...(!this.draftActive && this.draftEndedBy ? { endedBy: this.draftEndedBy } : {}),
    } }
    this.cached = { version: this.version, derived }
    return derived
  }

  emit(): void { this.touch(); for (const listener of [...this.listeners]) listener() }
  setWorkspaceSelected(id: string | undefined): void {
    this.base = { ...this.base, agent: this.base.agent && { ...this.base.agent, workspaces: { state: 'ready', items: this.base.agent.workspaces?.items ?? [], selectedWorkspaceId: id } } }
    this.emit()
  }
  setConnectionStatus(status: 'disconnected' | 'connecting' | 'connected' | 'error'): void {
    this.base = { ...this.base, agent: this.base.agent && { ...this.base.agent, connection: { ...this.base.agent.connection, status } } }
    this.emit()
  }

  getSnapshot = (): AgentWorkspaceSnapshot => this.derive()
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  async selectConnection(): Promise<void> {}
  async reconnect(): Promise<void> {}
  async refreshSessions(): Promise<void> {}
  async newSession(): Promise<void> {}
  async openSession(): Promise<void> {}
  sends: string[] = []
  async send(text: string): Promise<void> {
    // Deferred control lives in the test: assign sendBehavior with a pending
    // promise to hold a send open, or reject it to script refusals.
    this.sends.push(text)
    return this.sendBehavior({ text })
  }
  stop(runId: string): Promise<void> { this.stopped.push(runId); return Promise.resolve() }
  async respond(id: string, answer: InteractionAnswer): Promise<void> {
    if (this.respondError) throw this.respondError
    this.responded.push({ id, answer })
  }
  async setOption(): Promise<void> {}
  startDraft(): void { this.startDraftCalls++; this.draftActive = true; this.draftEndedBy = undefined; this.emit() }
  discardDraft(): void { this.discardDraftCalls++; this.draftActive = false; this.draftEndedBy = 'discarded'; this.emit() }
  setDraftActiveSilently(active: boolean): void { this.draftActive = active; this.touch() }
  async selectWorkspace(id: string): Promise<void> { this.selectedWorkspaces.push(id); this.setWorkspaceSelected(id) }
  async addWorkspace(): Promise<void> {}
  async refreshWorkspaces(): Promise<void> {}
}
