import type * as acp from '@agentclientprotocol/sdk'
import type { AgentClient, AgentWorkspaceInfo } from '@extensions/ordessa.agent-contracts/contract.js'
import { HarnessPeer } from './acp-peer'

/**
 * The seam these target tests are written against. NOTHING here is a new public protocol:
 * the ACP half is defined entirely by the pinned SDK (fixtures/acp-peer.ts), and the snapshot
 * half is the existing `AgentClient` contract the chat UI already consumes. What is NOT frozen
 * is the backend-orchestration signature (how a Server/Harness is picked, how a project is
 * listed/bound, and how the project-bound bidirectional channel arrives). Until it is, target
 * tests inject the facts the connector is allowed to need — see docs/acp-connector-test-review.md.
 *
 * Channel model (reviewed): selecting a Server/Harness lets the connector read the project list,
 * but it must NOT open a project-less ACP channel eagerly. Before the first send the connector
 * acquires the channel for the bound project (`acquireChannel(projectId)`), performs exactly one
 * `initialize` on it, then `session/new`/`session/prompt`; a draft creates no native session, and
 * later turns reuse that session and its channel. `acquireChannel`'s exact function name is a
 * proposed injection surface pending backend alignment — it is NOT a second public protocol.
 *
 * Second review round: acquisition hands back a MANAGED HANDLE (identity + authoritative binding
 * + stream + explicit release), because closing a transport and standing a backend channel down
 * are different events and must not be inferred from each other.
 */

/**
 * One project-bound ACP channel as the orchestration hands it over. Three distinct events:
 * dropping the transport, switching the UI view, and releasing the backend channel. Only
 * `release()` tells the backend to stand the channel down; a stream close is NOT an implicit
 * release, and a view switch is neither.
 */
export interface AcpChannelHandle {
  /** Orchestration-issued identity for this channel instance. */
  readonly connectionId: string
  /** The authoritative project binding this channel serves; `binding.normalizedPath` is the
   * `session/new` cwd. Tests read it back to prove the connector binds by handle, not by guess. */
  readonly binding: AgentWorkspaceInfo
  readonly stream: acp.Stream
  /** Explicit backend release. Idempotence is the implementation's problem; the fixture counts calls. */
  release(): Promise<void>
}

export interface AcpChannelSpec {
  /** Real Server instance identity behind the connection (never a plugin id). */
  serverInstanceId: string
  /** The one Harness selected through orchestration; the connector never picks or spawns one. */
  harness: { id: string; title: string }
  /** Server-authoritative project records; readable on selection, without any ACP channel. */
  listProjects: () => Promise<readonly AgentWorkspaceInfo[]>
  /** The authoritative binding for one project — its `normalizedPath` is the `session/new` cwd;
   * the connector never guesses or reuses a path. */
  openProject: (id: string) => Promise<AgentWorkspaceInfo>
  /** Optional project registration over the Server's existing `workspaces.open` upsert (mirrors
   * `plugins/connectors/acp/src/channel.ts`); absent means the client exposes no `addWorkspace`. */
  addProject?: (path: string) => Promise<AgentWorkspaceInfo>
  /** Acquire the managed channel for the selected project (name pending backend alignment).
   * No channel exists until a project is bound; `initialize` runs on the handle's stream. */
  acquireChannel: (projectId: string) => Promise<AcpChannelHandle>
}

export interface AcpConnectorTarget {
  /** Must register under the orchestration's own id (`acp:${serverInstanceId}` proposed). `connect`
   * exposes `serverInstanceId`/`harness` and a project list but opens no channel; the project-bound
   * `initialize` happens on first use. */
  createConnector: (spec: AcpChannelSpec) => { id: string; title: string; connect: () => Promise<AgentClient> }
}

export const TARGET_MODULE = 'plugins/connectors/acp/src/entry'
/** Absolute file URL: the target lives in the product tree, above this suite's vitest root. */
const TARGET_URL = new URL('../../../../plugins/connectors/acp/src/entry.ts', import.meta.url).href

const TARGET_MISSING = (detail: string) => new Error(
  `TARGET_MISSING: ${detail} — the ACP connector seam is not implemented yet. ` +
  'This is the expected red state of a target test (docs/acp-connector-test-review.md); ' +
  'it must not be skipped, xfailed, or replaced by fixture-only passes.')

/** Loads the production ACP connector, or reports the missing target explicitly. */
export async function loadAcpTarget(): Promise<AcpConnectorTarget> {
  const moduleId = `${TARGET_MODULE}.ts`
  let loaded: Record<string, unknown>
  try {
    // Computed specifier: resolution happens at runtime, so the absence is a reported target
    // gap rather than a build-time failure of the whole suite.
    loaded = await import(/* @vite-ignore */ TARGET_URL) as Record<string, unknown>
  } catch (error) {
    throw TARGET_MISSING(`module ${moduleId} does not resolve (${String(error).slice(0, 120)})`)
  }
  const createConnector = loaded.createConnector
  if (typeof createConnector !== 'function') throw TARGET_MISSING(`${moduleId} must export createConnector(spec)`)
  return { createConnector } as AcpConnectorTarget
}

/**
 * Peer + spec bound together: every target test drives one controllable Harness through it.
 * Each offered project gets its OWN peer and its own managed handle — a connector that leaked
 * a channel across projects would talk to the wrong peer.
 */
export async function connectTargetFor(options: {
  capabilities?: acp.AgentCapabilities
  projects: Record<string, string>          // projectId -> authoritative normalizedPath
} = { projects: { ws_app: '/repo/app' } }) {
  const target = await loadAcpTarget()
  const projectIds = Object.keys(options.projects)
  const peers = new Map<string, HarnessPeer>()
  for (const id of projectIds) peers.set(id, new HarnessPeer({ capabilities: options.capabilities }))
  const projects: AgentWorkspaceInfo[] = projectIds.map(id => ({ id, normalizedPath: options.projects[id] }))
  // Records every project a channel was acquired for, and every explicit backend release.
  // A connector that opens a project-less or unoffered-project channel is caught by `acquired`
  // staying empty; one that treats a transport close or a view switch as a release is caught
  // by `released`.
  const acquired: string[] = []
  const released: string[] = []
  const handles = new Map<string, AcpChannelHandle>()
  const spec: AcpChannelSpec = {
    serverInstanceId: 'https://harness.test|server_1',
    harness: { id: 'pi', title: 'PI Harness' },
    listProjects: async () => projects,
    openProject: async id => {
      const found = projects.find(item => item.id === id)
      if (!found) throw new Error(`project-invalid: ${id} is not offered by this Server`)
      return found
    },
    acquireChannel: async projectId => {
      const binding = projects.find(item => item.id === projectId)
      const peer = peers.get(projectId)
      if (!binding || !peer) throw new Error(`project-invalid: ${projectId} is not offered by this Server`)
      acquired.push(projectId)
      const handle: AcpChannelHandle = {
        connectionId: `chan_${projectId}`,
        binding,
        stream: peer.stream,
        release: async () => { released.push(projectId); peer.close() },
      }
      handles.set(projectId, handle)
      return handle
    },
  }
  const connector = target.createConnector(spec)
  const client = await connector.connect()
  const peerFor = (projectId: string) => {
    const peer = peers.get(projectId)
    if (!peer) throw new Error(`no fixture peer for project ${projectId}`)
    return peer
  }
  const closeAll = async () => { for (const peer of peers.values()) peer.close() }
  // The single-project convenience is lazy: only tests that bind ws_app ever touch it
  // (R27 offers ws_a/ws_b and reads its peers through `peerFor`; an eager `peerFor('ws_app')`
  // in this return object crashed the fixture before the connector was even constructed).
  return { target, spec, connector, client, projects, acquired, released, handles, peerFor, closeAll,
    get peer(): HarnessPeer {
      const appPeer = peers.get('ws_app')
      if (!appPeer) throw new Error('no fixture peer for project ws_app')
      return appPeer
    } }
}

/** The one-project default: ws_app at /repo/app (plus a second listed-but-unbound project). */
export async function connectTarget(options: { capabilities?: acp.AgentCapabilities } = {}) {
  return connectTargetFor({ capabilities: options.capabilities, projects: { ws_app: '/repo/app', ws_docs: '/repo/docs' } })
}

/** Subscribe to every snapshot change of a client (the same way the real facade does). */
export function watchSnapshots(client: AgentClient) {
  const seen: string[] = []
  const unsubscribe = client.subscribe(() => { seen.push(JSON.stringify(client.getSnapshot())) })
  return { seen, unsubscribe }
}
