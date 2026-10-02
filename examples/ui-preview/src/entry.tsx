import type { PluginContext, ResourceScope } from '@ordessa/extension-api'
import { AgentConnectionsToken, type AgentClient, type AgentConnections, type AgentMessage, type AgentSnapshot } from '@extensions/ordessa.agent-contracts/contract.js'

// Test-only controlled preview fixtures (UI optimization round): anonymous, deterministic data that
// drives the real workbench, sessions and Chat surfaces through the public connector API.
const capabilities = { history: 'supported', reasoning: 'supported', tools: 'supported', stop: 'supported',
  interactions: 'supported', models: 'unsupported', modes: 'unsupported' } as const

const base = (id: string, title: string, initial: Partial<AgentSnapshot>): AgentSnapshot =>
  ({ connection: { id, title, status: 'connected', capabilities }, sessions: [], sessionList: 'ready',
    messages: {}, runs: {}, interactions: [], options: [], ...initial })

const historyMessages: readonly AgentMessage[] = [
  { id: 'h-u1', role: 'user', text: 'Summarize the fixture module and point out the risky spots.' },
  { id: 'h-a1', role: 'assistant', text: 'The fixture module has three entry points. `readEntry` parses a record, `writeEntry` persists it and `triage` classifies failures.\n\nThe risky spot is `triage`: it swallows unknown exit codes and reports them as “retry later”, which hides real failures.',
    reasoning: 'Scanning the module: three exported functions, then checking error paths for silent fallbacks.',
    tools: [{ id: 't-read', name: 'read_file', arguments: { path: 'src/fixture.ts' }, result: '123 lines read: readEntry, writeEntry, triage.', status: 'completed' }] },
  { id: 'h-u2', role: 'user', text: 'Apply the safe rename we discussed?' },
  { id: 'h-a2', role: 'assistant', text: 'Done — renamed the internal helper to `readEntry` across 4 call sites; the public API is unchanged and the suite still passes.',
    tools: [{ id: 't-edit', name: 'edit_file', arguments: { path: 'src/fixture.ts', changes: 4 }, result: 'Edited src/fixture.ts (+6 −6)', status: 'completed' },
      { id: 't-test', name: 'run_command', arguments: { command: 'npm test -- fixture' }, result: '23 passed (23)', status: 'completed' }] },
]

const scenarios: Record<string, { title: string; initial: () => Partial<AgentSnapshot> }> = {
  empty: { title: 'Preview · Empty', initial: () => ({}) },
  history: { title: 'Preview · History', initial: () => ({
    sessions: [
      { id: 'H1', title: 'Fixture module review', workspaceId: 'ws-demo' },
      { id: 'H2', title: 'Weekly status draft' },
      { id: 'H3', title: 'Release checklist triage', workspaceId: 'ws-demo', pinned: true },
    ],
    selectedSessionId: 'H1',
    messages: { H1: historyMessages, H2: [
      { id: 'w-u1', role: 'user', text: 'Draft the status note from the fixture checklist.' },
      { id: 'w-a1', role: 'assistant', text: 'Drafted: two items done, one blocked on the demo environment. Waiting for your edit before sending.' },
    ] },
  }) },
  running: { title: 'Preview · Running', initial: () => ({
    sessions: [{ id: 'R1', title: 'Fixture migration rehearsal' }],
    selectedSessionId: 'R1',
    messages: { R1: [
      { id: 'r-u1', role: 'user', text: 'Rehearse the fixture migration and report each step.' },
      { id: 'r-a1', role: 'assistant', text: 'Step 1: reading the current schema…\nStep 2: building the target table in the sandbox copy.',
        reasoning: 'Planning the rehearsal order: snapshot first, then transform, then verify counts.',
        tools: [{ id: 't-shell', name: 'run_command', arguments: { command: 'npm run migrate:rehearse' }, status: 'running' }],
        status: 'running' },
    ] },
    runs: { RU1: { id: 'RU1', sessionId: 'R1', status: 'running' } },
  }) },
  approval: { title: 'Preview · Approval', initial: () => ({
    sessions: [{ id: 'A1', title: 'Fixture command approval' }],
    selectedSessionId: 'A1',
    messages: { A1: [
      { id: 'a-u1', role: 'user', text: 'Run the fixture verification suite in the sandbox.' },
      { id: 'a-a1', role: 'assistant', text: 'The suite needs to execute one command in the selected project. Waiting for approval.', status: 'running' },
    ] },
    runs: { AU1: { id: 'AU1', sessionId: 'A1', status: 'running' } },
    interactions: [{ id: 'I1', sessionId: 'A1', kind: 'approval',
      title: 'Allow command: npm test -- fixture', detail: 'Runs the fixture verification suite in the selected project.',
      choices: [{ id: 'allow', label: 'Allow once' }, { id: 'always', label: 'Always allow' }, { id: 'deny', label: 'Reject' }],
      state: 'pending' }],
  }) },
}

function makeClient(key: string): AgentClient {
  const id = `ui-preview.${key}`
  const { title, initial } = scenarios[key]
  let snapshot = base(id, title, initial())
  const listeners = new Set<() => void>()
  const write = (patch: Partial<AgentSnapshot>) => {
    snapshot = { ...snapshot, ...patch }
    for (const listener of [...listeners]) listener()
  }
  const forSession = (sessionId: string) => (snapshot.messages[sessionId] ?? [])
  let responseCount = 0
  return {
    get isDisposed() { return false },
    dispose() { listeners.clear() },
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    refreshSessions: () => Promise.resolve(),
    newSession: () => Promise.resolve('new-session'),
    async openSession(sessionId) { write({ selectedSessionId: sessionId }) },
    async send(sessionId, text) {
      write({ messages: { ...snapshot.messages, [sessionId]: [...forSession(sessionId), { id: `echo-u-${Date.now()}`, role: 'user', text }] } })
      setTimeout(() => write({ messages: { ...snapshot.messages, [sessionId]: [...forSession(sessionId),
        { id: `echo-a-${Date.now()}`, role: 'assistant', text: 'Echo (fixture): ' + text, status: 'completed' }] } }), 150)
    },
    async stop(sessionId, runId) {
      write({ runs: { ...snapshot.runs, [runId]: { ...snapshot.runs[runId], sessionId, status: 'stop-requested' } } })
      setTimeout(() => write({
        // The cancelled run stays in the snapshot: the chip must show 'cancelled', not fall back to 'idle'.
        runs: { ...snapshot.runs, [runId]: { id: runId, sessionId, status: 'cancelled' as const } },
        messages: { ...snapshot.messages, [sessionId]: forSession(sessionId).map(message =>
          message.status === 'running' ? { ...message, status: 'cancelled' as const } : message) },
      }), 600)
    },
    async respond(interactionId, answer) {
      document.documentElement.dataset.previewResponse = JSON.stringify({ interactionId, answer })
      document.documentElement.dataset.previewResponseCount = String(++responseCount)
      write({ interactions: snapshot.interactions.map(item => item.id === interactionId ? { ...item, state: 'resolved' as const } : item) })
      document.documentElement.dataset.previewInteractionState = snapshot.interactions.find(item => item.id === interactionId)?.state ?? ''
      // The approved command finishes right away so the switch gate releases for the next scenario.
      setTimeout(() => write({
        runs: {},
        messages: { ...snapshot.messages, A1: forSession('A1').map(message => message.status === 'running'
          ? { ...message, status: 'completed' as const, text: message.text + '\n23 passed (23).' } : message) },
      }), 200)
    },
    setOption: () => Promise.resolve(),
  }
}

export default function createPlugin() {
  return { id: 'example.ui-preview', autoStart: true, requires: [AgentConnectionsToken],
    activate: (context: PluginContext, connections: AgentConnections) => {
      for (const [key, { title }] of Object.entries(scenarios))
        connections.forScope(context.resources as ResourceScope).add({ id: `ui-preview.${key}`, title, connect: async () => makeClient(key) })
    } }
}
