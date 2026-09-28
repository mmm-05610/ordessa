import { constants, closeSync, fstatSync, openSync, readSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import path from 'node:path'
import type { NativeConnection, NativeTransport } from '../../../../packages/desktop-platform/native-bridge/src/index'

/**
 * The main-process half of the ACP connector. It is the only place this extension holds the Server
 * bearer, and it only ever relays: agent-authored ACP frames cross the bridge nested and unmodified,
 * and every refusal here is phrased without a token or a private path.
 *
 * It speaks the Server's implemented managed-ACP-channel seam (bc-native `docs/acp-channel-minimal-seam.md`
 * and `src/agent_box/server/{wire/handlers,acp_channel,transport/http/app}.py`):
 *  - identity: `server.hello.nativeExecution` {mode:"native", harness, profileId}; this Server answers
 *    channels for exactly that one harness, so the offered state is one Server|Harness pair. A hello
 *    without the pair — or without declared `acp.channel.open`/`acp.channel.release` capabilities —
 *    is an honest not-offered, never a fallback pick.
 *  - projects: the existing `workspaces.list` / `workspaces.open` surface (same as the Ordessa connector);
 *    no project method is invented for this frontend.
 *  - `acp.channel.open {harnessId, projectId}` answers {connectionId, executionId,
 *    binding:{harnessId, projectId, cwd}}, idempotent per live pair (the same connection comes back and
 *    the relay below is reused, never attached twice — a second attach would double-deliver inbound frames).
 *  - the relay is `/wire/v1/acp-channel/{connectionId}`: verbatim text lines both ways, no Server-side
 *    parsing; a socket close (agent death, restart) ends the channel honestly and is never a release —
 *    only the explicit `acp.channel.release {connectionId}` stands the channel down at the backend.
 *  - `executions.get` exists on the seam but is not consumed here: the run's fate arrives in the ACP
 *    frames themselves, and polling the ledger would restate what the channel already said.
 *
 * Server access follows the same conventions as the Ordessa Server connector (loopback http origin,
 * 0600 `secrets/http-token`, one JSON-RPC POST per call, header-bearing Node WebSocket) but is kept
 * self-contained: extensions are independent build inputs and must not import each other's code.
 */

type Frame = { method?: string; params?: Record<string, unknown> }
const record = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
const text = (value: unknown): string | undefined => typeof value === 'string' && value ? value : undefined

const MAX_TOKEN_BYTES = 4096
function refuse(reason: string, source: string): never { throw new Error(`Ordessa Server ${reason}; ${source}`) }

/** The two host-supplied env inputs are the only way this extension learns where the Server is. */
const parseOrigin = (raw: string | undefined): string => {
  const source = 'the desktop host must pass the loopback origin of the Server it started'
  if (!raw) refuse('ORDESSA_SERVER_ORIGIN is not set', source)
  let url: URL
  try { url = new URL(raw) } catch { return refuse('ORDESSA_SERVER_ORIGIN is not a URL', 'expected e.g. http://127.0.0.1:<port>') }
  if (url.protocol !== 'http:') refuse('ORDESSA_SERVER_ORIGIN must use http', 'only loopback http is served by the Server')
  if (!/^(\[::1\]|127\.\d{1,3}\.\d{1,3}\.\d{1,3}|localhost)$/.test(url.hostname)) refuse('ORDESSA_SERVER_ORIGIN host is not loopback', `got ${url.hostname}`)
  if (!url.port) refuse('ORDESSA_SERVER_ORIGIN omits the port', 'never assume the default port')
  if (url.pathname !== '/' || url.search || url.hash) refuse('ORDESSA_SERVER_ORIGIN must be an origin only', 'no path, query or fragment')
  if (url.username || url.password) refuse('ORDESSA_SERVER_ORIGIN must not carry credentials', 'the bearer token comes from the token file')
  return url.origin
}

/** Every ownership fact is checked on one descriptor so a verified path cannot be swapped before reading. */
const readTokenFile = (locator: string): string => {
  const source = path.basename(locator)
  if (source !== 'http-token') refuse('token file is not named http-token', source)
  if (path.basename(path.dirname(locator)) !== 'secrets') refuse('token file is not inside the data-root secrets directory', source)
  const getuid = typeof process.getuid === 'function' ? process.getuid : undefined
  if (!getuid) refuse('token file ownership cannot be checked on this platform', source)
  let descriptor: number
  try { descriptor = openSync(locator, constants.O_RDONLY | constants.O_NOFOLLOW) }
  catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    refuse(code === 'ELOOP' ? 'token file is a symlink'
      : code === 'EACCES' || code === 'EPERM' ? 'token file is not readable by this user'
      : code === 'ENOTDIR' ? 'token file path is not a file' : 'token file is unreadable', source)
  }
  try {
    const stats = fstatSync(descriptor)
    if (!stats.isFile()) refuse('token file is not a regular file', source)
    if ((stats.mode & 0o077) !== 0) refuse('token file is readable by group or other', source)
    if (stats.uid !== getuid()) refuse('token file is owned by another user', source)
    if (stats.size === 0) refuse('token file is empty', source)
    if (stats.size > MAX_TOKEN_BYTES) refuse('token file is too large', source)
    const buffer = Buffer.allocUnsafe(stats.size)
    let length = 0
    for (;;) {
      const read = readSync(descriptor, buffer, length, buffer.byteLength - length, length)
      if (read === 0) break
      length += read
    }
    const token = buffer.subarray(0, length).toString('utf8').replace(/\r?\n$/, '')
    if (!token) refuse('token file is empty', source)
    // An embedded newline would let one file forge extra headers.
    if (/[\u0000-\u001f\u007f]/.test(token)) refuse('token file holds control characters', source)
    return token
  } finally { closeSync(descriptor) }
}

interface ServerTarget { origin: string; socket: string; token: string }
const resolveTarget = (): ServerTarget => {
  const origin = parseOrigin(process.env.ORDESSA_SERVER_ORIGIN)
  const locator = process.env.ORDESSA_SERVER_TOKEN_FILE
  if (!locator) refuse('ORDESSA_SERVER_TOKEN_FILE is not set', 'the desktop host must pass the token locator for the same data-root')
  if (!path.isAbsolute(locator)) refuse('ORDESSA_SERVER_TOKEN_FILE is not absolute', 'expected the Server data-root token file path')
  return { origin, socket: origin.replace(/^http:/, 'ws:'), token: readTokenFile(locator) }
}

class WireError extends Error {
  constructor(readonly code: string, message: string) { super(message) }
}

/** One JSON-RPC call per HTTP POST, exactly as the wire surface defines it; redirects would replay the bearer. */
const rpc = async (target: ServerTarget, method: string, params: Record<string, unknown>): Promise<unknown> => {
  let response: Response
  try {
    response = await fetch(`${target.origin}/wire/v1/${method}`, {
      method: 'POST', redirect: 'error',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${target.token}` },
      body: JSON.stringify({ jsonrpc: '2.0', id: method, method, params }),
    })
  } catch {
    throw new WireError('UNAVAILABLE', `${method} did not reach the Server at ${target.origin}`)
  }
  const envelope = await response.json().catch(() => undefined) as { result?: unknown; error?: { code?: unknown; message?: unknown } } | undefined
  if (!response.ok) throw new WireError('UNAVAILABLE', `${method} was refused with HTTP ${response.status}`)
  if (envelope?.error) throw new WireError(text(envelope.error.code) ?? 'UNAVAILABLE',
    text(envelope.error.message) ?? `${method} failed`)
  return envelope?.result
}

/** Only Node's WebSocket honours a header-bearing options object; the DOM lib types it as protocols.
 * Resolved per connection, exactly like `fetch`, so the global in force at connect time is the one used. */
type NodeWebSocket = new (url: string, options: { headers: Record<string, string> }) => WebSocket
const connectSocket = () => WebSocket as unknown as NodeWebSocket

const RELAY_QUEUE_LIMIT = 256

interface Relay { socket: WebSocket; ready: boolean; queue: string[]; released: boolean }
interface ProjectRecord { id: string; normalizedPath: string; environment: Record<string, unknown> }

export default function createTransport(): NativeTransport {
  return { async open(onFrame): Promise<NativeConnection> {
    const target = resolveTarget()
    const hello = record(await rpc(target, 'server.hello', { clientVersions: ['wire/1'], clientPresentationSupports: [] }))
    if (text(hello?.protocolVersion) !== 'wire/1') {
      throw new Error(`Ordessa Server speaks ${text(hello?.protocolVersion) ?? 'an unknown protocol'}, not wire/1`)
    }
    const serverId = text(hello?.serverId)
    if (!serverId) throw new Error('Ordessa Server hello named no serverId; the ACP identity cannot be derived')
    const capabilities = Array.isArray(hello?.capabilities) ? hello.capabilities as Record<string, unknown>[] : []
    const supported = (id: string) => capabilities.some(item => item.id === id && item.supported === true)
    const required = (id: string) => {
      if (!supported(id)) throw new WireError('CAPABILITY_UNSUPPORTED', `${id} is not available on this Server`)
    }

    // The native-execution identity is the only harness this Server answers channels for, and hello
    // re-verifies the same facts server-side — an incomplete or unregistered identity is not-offered,
    // never a fallback pick (the Ordessa connector's `nativeExecutionProfile` reads it the same way).
    const native = record(hello?.nativeExecution)
    const harnessId = native?.mode === 'native' ? text(native.harness) : undefined
    const registered = Array.isArray(hello?.harnesses)
      && hello.harnesses.some(item => record(item)?.id === harnessId)
    const supportedChannel = supported('acp.channel.open') && supported('acp.channel.release')
    const instance = `${target.origin}|${serverId}`
    const pair = harnessId && text(native?.profileId) && registered && supportedChannel
      ? { serverInstanceId: `${instance}|${harnessId}`, harnessId } : undefined

    // Raw environments stay here; the renderer never learns a path it could replay against another Server.
    const projects = new Map<string, ProjectRecord>()
    const relays = new Map<string, Relay>()
    let closed = false
    const live = (frame: Record<string, unknown>) => { if (!closed) onFrame(frame) }

    const loadProjects = async () => {
      required('workspaces.list')
      const listed = record(await rpc(target, 'workspaces.list', { includeArchived: false }))
      // Rebuilt every time: a project the Server stopped listing must stop resolving here, not age out.
      projects.clear()
      for (const item of Array.isArray(listed?.items) ? listed.items as Record<string, unknown>[] : []) {
        const id = text(item.id), normalizedPath = text(item.normalizedPath), environment = record(item.environment)
        if (id && normalizedPath && environment) projects.set(id, { id, normalizedPath, environment })
      }
      return [...projects.values()]
    }

    const openRelay = (connectionId: string): Relay => {
      const relay: Relay = { socket: undefined as never, ready: false, queue: [], released: false }
      const Socket = connectSocket()
      const socket = new Socket(`${target.socket}/wire/v1/acp-channel/${encodeURIComponent(connectionId)}`, {
        headers: { authorization: `Bearer ${target.token}` },
      })
      relay.socket = socket
      socket.addEventListener('open', () => {
        relay.ready = true
        for (const pending of relay.queue.splice(0)) socket.send(pending)
      })
      socket.addEventListener('message', message => {
        let frame: unknown
        try { frame = JSON.parse(String(message.data)) }
        catch { return down(connectionId, 'malformed agent frame') }
        live({ method: 'acp/message', connectionId, params: { frame } })
      })
      socket.addEventListener('error', () => down(connectionId, 'agent channel socket failed'))
      socket.addEventListener('close', () => down(connectionId, 'agent channel closed'))
      relays.set(connectionId, relay)
      return relay
    }
    // A transport death is reported, then the relay is gone; it is never a release, and the renderer
    // client alone decides what an unconfirmed in-flight turn means.
    const down = (connectionId: string, reason: string) => {
      const relay = relays.get(connectionId)
      if (!relay || relay.released) return
      relay.released = true
      relays.delete(connectionId)
      live({ method: 'acp/down', connectionId, params: { reason } })
    }

    const dispatch = async (frame: Frame): Promise<unknown> => {
      const params = frame.params ?? {}
      switch (frame.method) {
        case 'acp/identity':
          return pair
            ? { offered: true, entries: [{ serverInstanceId: pair.serverInstanceId, harness: { id: pair.harnessId, title: pair.harnessId } }] }
            : { offered: false, entries: [] }
        case 'acp/projects': {
          if (!pair || params.instanceId !== pair.serverInstanceId) throw new Error('ACP projects were asked for an instance this Server never offered')
          return { items: await loadProjects() }
        }
        case 'acp/openProject': {
          // `workspaces.open` upserts by path, so the record is re-listed first and the Server's own
          // answer is trusted for identity and path — same revalidation the Ordessa connector runs.
          if (!pair || params.instanceId !== pair.serverInstanceId) throw new Error('opening an ACP project needs the offered instance')
          const id = text(params.id)
          if (!id) throw new Error('opening an ACP project needs the project identity')
          required('workspaces.open')
          await loadProjects()
          const known = projects.get(id)
          if (!known) throw new Error(`project-invalid: the Server has no unarchived project with that identity`)
          const opened = record(await rpc(target, 'workspaces.open', {
            requestId: `workspace_${randomUUID()}`, environment: known.environment, path: known.normalizedPath,
          }))
          const workspace = record(opened?.workspace)
          if (text(workspace?.id) !== known.id) throw new Error('project-invalid: the Server resolved a different project identity')
          if (workspace?.archivedAt != null) throw new Error('project-invalid: the project is archived')
          return { id: known.id, normalizedPath: text(workspace?.normalizedPath) ?? known.normalizedPath }
        }
        case 'acp/addProject': {
          // Registering a user-picked directory rides the SAME existing `workspaces.open` upsert the
          // Ordessa connector's addProject uses (workspaces.open is upsert-by-path on the wire) — no
          // backend method is invented here; only this bridge frame name is ours. The Server's answer
          // is re-listed before it is trusted, exactly like `acp/openProject` revalidates.
          if (!pair || params.instanceId !== pair.serverInstanceId) throw new Error('adding an ACP project needs the offered instance')
          const directory = text(params.path)
          if (!directory || !directory.startsWith('/') || directory.includes('\0')) {
            throw new Error('project-invalid: choose an absolute local directory')
          }
          required('workspaces.open')
          const added = record(await rpc(target, 'workspaces.open', {
            requestId: `workspace_${randomUUID()}`, path: directory,
            environment: { kind: 'local', host: null, user: null },
          }))
          const workspace = record(added?.workspace)
          const id = text(workspace?.id)
          if (!id || workspace?.archivedAt != null) throw new Error('project-invalid: the Server did not accept this project')
          await loadProjects()
          const known = projects.get(id)
          if (!known) throw new Error('project-invalid: the added project is not in the Server list')
          return { id, normalizedPath: text(workspace?.normalizedPath) ?? known.normalizedPath }
        }
        case 'acp/channel/open': {
          if (!pair || params.instanceId !== pair.serverInstanceId) throw new Error('opening an ACP channel needs the offered instance')
          const projectId = text(params.projectId)
          if (!projectId) throw new Error('opening an ACP channel needs the project identity')
          required('acp.channel.open')
          // The harness is never a client choice: it is this Server's native identity, checked again
          // by the Server itself, which starts nothing on any mismatch.
          const opened = record(await rpc(target, 'acp.channel.open', { harnessId: pair.harnessId, projectId }))
          const connectionId = text(opened?.connectionId), executionId = text(opened?.executionId)
          const binding = record(opened?.binding)
          const cwd = text(binding?.cwd)
          if (!connectionId || !executionId || !cwd || text(binding?.projectId) !== projectId || text(binding?.harnessId) !== pair.harnessId) {
            throw new Error('the Server granted an ACP channel without a connection id or with a moved binding')
          }
          // The open is idempotent per live pair; a second attach would double-deliver inbound frames,
          // so the existing relay is reused rather than re-attached.
          if (!relays.has(connectionId)) openRelay(connectionId)
          return { connectionId, executionId, binding: { id: projectId, normalizedPath: cwd } }
        }
        case 'acp/channel/send': {
          const connectionId = text(params.connectionId)
          const relay = connectionId ? relays.get(connectionId) : undefined
          if (!relay) throw new Error('ACP channel relay unavailable')
          const encoded = JSON.stringify(params.frame)
          if (encoded === undefined) throw new Error('ACP channel frame is not transmissible')
          if (!relay.ready) {
            if (relay.queue.length >= RELAY_QUEUE_LIMIT) throw new Error('ACP channel relay buffer exceeded')
            relay.queue.push(encoded)
          } else relay.socket.send(encoded)
          return {}
        }
        case 'acp/channel/authorizeSubmission': {
          const connectionId = text(params.connectionId)
          if (!connectionId || !relays.has(connectionId)) throw new Error('ACP channel admission needs a live owned relay')
          required('acp.submission.authorize')
          const submission = record(params.submission)
          if (!submission || !text(submission.submissionId) || !text(submission.nativeSessionId)
            || typeof submission.text !== 'string' || !text(submission.configurationDigest)
            || !Array.isArray(submission.attachments)) {
            throw new Error('ACP channel admission requires a complete submission')
          }
          // The Server derives principal and channel generation from its authenticated ledger;
          // no renderer supplied identity or permit is forwarded as authority.
          return await rpc(target, 'acp.submission.authorize', { connectionId, submission })
        }
        case 'acp/channel/authorizePermission': {
          const connectionId = text(params.connectionId)
          if (!connectionId || !relays.has(connectionId)) throw new Error('ACP permission admission needs a live owned relay')
          required('acp.permission.authorize')
          const decision = record(params.decision)
          if (!decision || !text(decision.nativeSessionId) || !text(decision.interactionId)
            || !text(decision.runId) || !text(decision.optionId)) {
            throw new Error('ACP permission decision is incomplete')
          }
          return await rpc(target, 'acp.permission.authorize', { connectionId, decision })
        }
        case 'acp/channel/release': {
          const connectionId = text(params.connectionId)
          if (!connectionId) throw new Error('releasing an ACP channel needs its connection id')
          required('acp.channel.release')
          const standDown = () => {
            const relay = relays.get(connectionId)
            if (relay) {
              relay.released = true
              relays.delete(connectionId)
              try { relay.socket.close() } catch { /* already gone */ }
            }
          }
          let answer: Record<string, unknown>
          try { answer = record(await rpc(target, 'acp.channel.release', { connectionId })) ?? {} }
          // A channel the ledger already ended (agent death, restart) has nothing left to stand down;
          // every other refusal stays a refusal the renderer hears about.
          catch (error) {
            if (error instanceof WireError && error.code === 'NOT_FOUND') { standDown(); return {} }
            throw error
          }
          // The backend may only answer `released: true` on the entry's OS-confirmed receipt; an
          // honest `released: false` is a successful RPC carrying a failure. Nothing is stood down
          // here: the pair stays live and retryable, and the reason rides the existing diagnostic.
          if (answer.released !== true) {
            throw new Error(`ACP channel release unconfirmed: ${text(answer.reason) ?? 'the backend gave no reason'}`)
          }
          standDown()
          return {}
        }
        default:
          throw new Error('Unsupported ACP native frame')
      }
    }

    return {
      async send(input) {
        if (closed) throw new Error('ACP transport closed')
        const frame = record(input)
        if (!frame || !text(frame.method)) throw new Error('Invalid ACP native frame')
        return await dispatch(frame as Frame)
      },
      async close() {
        if (closed) return
        closed = true
        for (const relay of relays.values()) { relay.released = true; try { relay.socket.close() } catch { /* already gone */ } }
        relays.clear()
      },
    }
  } }
}
