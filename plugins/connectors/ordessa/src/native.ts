import type { NativeConnection, NativeTransport } from '../../../../packages/frontend/native-bridge/src/index'
import { readRestrictedTokenFile } from './token-file'
import { resolveServerTarget, serverInstanceId, type ServerTarget } from './target'
import { WIRE_VERSION, WireError, WireClient, openEventStream, type EventFrame } from './wire'

type Frame = { method?: string; params?: Record<string, unknown> }
const record = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
const text = (value: unknown): string | undefined => typeof value === 'string' && value ? value : undefined
const number = (value: unknown): number | undefined => typeof value === 'number' && Number.isFinite(value) ? value : undefined

/** A project the Server will not run in; the upper layer must block send and ask for a new pick. */
const PROJECT_INVALID = 'project-invalid'

/**
 * The only error families whose first send might already have been accepted, so only these may settle a
 * draft by querying `sendOutcome.query`. Every other family is a refusal the Server has already answered,
 * and turning one into an unknown outcome invites a resend of a turn that never existed.
 */
const UNDECIDED_CODES = new Set(['UNAVAILABLE', 'WORKER_UNREACHABLE', 'OUTCOME_UNKNOWN'])

/** The Server's typed codes for a project that is gone; they share `NOT_FOUND` with unrelated causes. */
const PROJECT_LOST_CODES = new Set(['LOCAL_PATH_MISSING', 'NATIVE_PROJECT_CHANGED'])

/** `wire.ts` has already narrowed both of these to the closed family set and a code-shaped token, so
 * naming them is safe where a Server-authored message — which may quote a host path — is not. */
const projectLoss = (error: WireError) => error.internalCode !== undefined && PROJECT_LOST_CODES.has(error.internalCode)
const projectLossError = (error: unknown) => new Error(`${PROJECT_INVALID}: the Server will not run in the selected project (${
  error instanceof WireError ? [error.code, error.internalCode].filter(Boolean).join('/') : 'revalidation refused'})`)
const lossNamed = (error: unknown) => error instanceof Error && error.message.startsWith(`${PROJECT_INVALID}:`)

interface ProjectRecord {
  id: string
  normalizedPath: string
  environment: Record<string, unknown>
}

interface Hello {
  serverId: string
  protocolVersion: string
  capabilities: { id: string; supported: boolean; reason?: string }[]
  harnesses: { id: string }[]
  nativeExecution?: unknown
}

const supported = (hello: Hello, method: string) => hello.capabilities.some(item => item.id === method && item.supported)

/**
 * FC-0053: the authenticated hello names this Server combination's execution identity, and that exact
 * `profileId` is the only one a first send may use. `profiles.list` never picks and never ranks — it is
 * cross-checked at that one id, so a second ready profile cannot change the answer and list order cannot
 * substitute for a choice. An isolated hello carries no `nativeExecution`; it must not fall back to a pick.
 */
export function nativeExecutionProfile(hello: Hello, items: readonly unknown[]): { id: string; harness: string; displayName: string } {
  const declared = record(hello.nativeExecution)
  if (!declared) throw new Error('native-execution-missing: this Server declares no native execution identity, so no profile may be chosen on its behalf')
  if (declared.mode !== 'native') throw new Error(`native-execution-mode: hello.nativeExecution.mode is ${JSON.stringify(declared.mode)}, not "native"`)
  const harness = text(declared.harness), id = text(declared.profileId)
  if (!harness || !id) throw new Error('native-execution-incomplete: hello.nativeExecution needs a non-empty harness and profileId')
  if (!hello.harnesses.some(item => item.id === harness)) throw new Error(`native-harness-unregistered: ${harness} is not in this Server's registered harness catalog`)
  const [match] = items.map(record).filter(item => !!item && text(item.id) === id)
  if (!match) throw new Error(`native-profile-unlisted: the profile ${id} hello names is not on this Server`)
  if (match.archivedAt != null) throw new Error(`native-profile-archived: the profile ${id} hello names is archived`)
  if (text(match.harness) !== harness) throw new Error(`native-profile-harness-mismatch: the profile ${id} belongs to ${text(match.harness) ?? 'an unknown harness'}, not ${harness}`)
  // `sendability.state === 'ready'` is the Server's own pre-send verdict; it reports anything it could not
  // read as `unknown`, so a ready state already rules out a pending recovery.
  if (record(match.sendability)?.state !== 'ready') throw new Error(`native-profile-not-ready: the profile ${id} hello names cannot accept a turn`)
  if (match.recoveryPending === true) throw new Error(`native-profile-recovery-pending: the profile ${id} hello names is waiting on a recovery`)
  return { id, harness, displayName: text(match.displayName) ?? id }
}

/**
 * The privileged half of the connector: it is the only place that holds the Server token, and it
 * answers for the Server identity before the renderer freezes a connector id.
 */
export default function createTransport(): NativeTransport {
  return { async open(onFrame): Promise<NativeConnection> {
    const target: ServerTarget = await resolveServerTarget(process.env, readRestrictedTokenFile)
    const wire = new WireClient(target)
    const hello = await wire.call<Hello>('server.hello', {
      clientVersions: [WIRE_VERSION],
      clientPresentationSupports: ['agent-snapshot.v1'],
    })
    if (hello.protocolVersion !== WIRE_VERSION) throw new WireError('CAPABILITY_UNSUPPORTED', `Server speaks ${hello.protocolVersion}, not ${WIRE_VERSION}`)
    const instance = serverInstanceId(target.origin, hello.serverId)

    /** The Server declares support per method id; calling an undeclared one would only guess at a failure. */
    const required = (method: string) => {
      if (!supported(hello, method)) throw new WireError('CAPABILITY_UNSUPPORTED', `${method} is not available on this Server`)
    }

    // Raw environments stay here; the renderer never learns a path it could replay against another Server.
    const projects = new Map<string, ProjectRecord>()
    const streams = new Map<string, { close(): void }>()

    const loadProjects = async () => {
      required('workspaces.list')
      const listed = await wire.call<{ items: Record<string, unknown>[] }>('workspaces.list', { includeArchived: false })
      // Rebuilt every time: a project the Server stopped listing must stop resolving here, not age out as valid.
      projects.clear()
      for (const item of listed.items ?? []) {
        const id = text(item.id), normalizedPath = text(item.normalizedPath), environment = record(item.environment)
        if (id && normalizedPath && environment) projects.set(id, { id, normalizedPath, environment })
      }
      return listed.items ?? []
    }

    /** `workspaces.open` upserts by path, so a same-path archived row or a re-keyed record must not read as valid. */
    const revalidateProject = async (id: string) => {
      required('workspaces.open')
      await loadProjects()
      const known = projects.get(id)
      if (!known) throw new Error(`${PROJECT_INVALID}: the Server has no unarchived project with that identity`)
      const opened = await wire.call<{ workspace?: Record<string, unknown> }>('workspaces.open', {
        requestId: wire.newRequestId('workspace'), environment: known.environment, path: known.normalizedPath,
      })
      const workspace = record(opened.workspace)
      if (text(workspace?.id) !== known.id) throw new Error(`${PROJECT_INVALID}: the Server resolved a different project identity`)
      if (workspace?.archivedAt != null) throw new Error(`${PROJECT_INVALID}: the project is archived`)
      return { id: known.id, normalizedPath: text(workspace?.normalizedPath) ?? known.normalizedPath }
    }

    const executionProfile = async () => {
      required('profiles.list')
      const listed = await wire.call<{ items: Record<string, unknown>[] }>('profiles.list', { includeArchived: false })
      return nativeExecutionProfile(hello, listed.items ?? [])
    }

    /**
     * An accepted first send is only proven by a real session id; an unknown outcome is queried, never
     * re-issued. FC-0057 splits the two refusals this used to collapse into one: a deterministic project
     * loss must not be dressed up as an uncertain send, and an uncertain send must not be re-issued.
     */
    const firstSend = async (workspaceId: string, message: string, requestId: string) => {
      const profile = await executionProfile()
      required('sessions.createAndSend')
      const params = {
        requestId, workspaceId, profileId: profile.id, overrides: [],
        message: { text: message, attachments: [] },
      }
      // Nothing has left this client yet, so the caller's request id is untouched: a refusal here answers
      // with zero `sessions.createAndSend` frames and zero outcome queries, whatever its family was.
      try { await revalidateProject(workspaceId) }
      catch (error) {
        if (lossNamed(error)) throw error
        if (error instanceof WireError && (projectLoss(error) || error.code === 'NOT_FOUND')) throw projectLossError(error)
        throw error
      }
      let sessionId: string | undefined
      try {
        const sent = await wire.call<Record<string, unknown>>('sessions.createAndSend', params)
        sessionId = text(record(sent.session)?.id)
      } catch (error) {
        if (!(error instanceof WireError)) throw error
        // The frame went out, so only a family that could still have been accepted may be queried; every
        // other refusal is the Server's settled answer and stays exactly that visible.
        if (!UNDECIDED_CODES.has(error.code)) throw projectLoss(error) ? projectLossError(error) : error
      }
      if (!sessionId) {
        const queried = await wire.call<Record<string, unknown>>('sendOutcome.query', { requestId }).catch(() => undefined)
        if (queried?.outcome === 'accepted') sessionId = text(queried.sessionId)
      }
      if (!sessionId) throw new WireError('OUTCOME_UNKNOWN', 'the first send was not confirmed; the same request id stays reserved for it')
      return { sessionId, profileId: profile.id }
    }

    // Flips before the sockets are torn down, so a callback already queued cannot reach a closed bridge.
    let closed = false
    const openStream = (sessionId: string, cursor: string | undefined) => {
      streams.get(sessionId)?.close()
      streams.set(sessionId, openEventStream(target, sessionId, cursor, {
        frame: (frame: EventFrame) => { if (!closed) onFrame({ method: 'ordessa/event', params: { sessionId, frame } }) },
        down: reason => { if (!closed) onFrame({ method: 'ordessa/down', params: { sessionId, reason } }) },
      }))
    }

    const dispatch = async (frame: Frame): Promise<unknown> => {
      const params = frame.params ?? {}
      const sessionId = text(params.sessionId)
      switch (frame.method) {
        case 'identity':
          return { serverInstanceId: instance, protocolVersion: hello.protocolVersion, capabilities: hello.capabilities, harnesses: hello.harnesses }
        case 'projects': {
          await loadProjects()
          return [...projects.values()].map(item => ({ id: item.id, normalizedPath: item.normalizedPath }))
        }
        case 'openProject': {
          const id = text(params.id)
          if (!id) throw new Error(`${PROJECT_INVALID}: no project selected`)
          return await revalidateProject(id)
        }
        case 'addProject': {
          required('workspaces.open')
          const path = text(params.path)
          if (!path || !path.startsWith('/') || path.includes('\0')) throw new Error(`${PROJECT_INVALID}: choose an absolute local directory`)
          const opened = await wire.call<{ workspace?: Record<string, unknown> }>('workspaces.open', {
            requestId: wire.newRequestId('workspace'), path,
            environment: { kind: 'local', host: null, user: null },
          })
          const workspace = record(opened.workspace), id = text(workspace?.id)
          if (!id || workspace?.archivedAt != null) throw new Error(`${PROJECT_INVALID}: the Server did not accept this project`)
          await loadProjects()
          const known = projects.get(id)
          if (!known) throw new Error(`${PROJECT_INVALID}: the new project is not in the Server list`)
          return { id, normalizedPath: known.normalizedPath }
        }
        case 'sessions': {
          required('sessions.list')
          // The list is filtered by project, so a session id in this frame would silently widen the query.
          const workspaceId = text(params.workspaceId)
          const listed = await wire.call<{ items: Record<string, unknown>[] }>('sessions.list', {
            includeArchived: false, page: { limit: 200 }, ...(workspaceId ? { workspaceId } : {}),
          })
          return (listed.items ?? []).map(item => ({ id: text(item.id) ?? '', title: text(item.displayName) ?? text(item.id) ?? '',
            updatedAt: text(item.updatedAt), workspaceId: text(item.workspaceId) }))
        }
        case 'createAndSend': {
          const workspaceId = text(params.workspaceId), message = text(params.text), requestId = text(params.requestId)
          if (!workspaceId || !message || !requestId) throw new Error(`${PROJECT_INVALID}: a first send needs a project, text and request id`)
          return await firstSend(workspaceId, message, requestId)
        }
        case 'send': {
          if (!sessionId || !text(params.text)) throw new Error('send needs a session and text')
          required('sessions.send')
          return await wire.call('sessions.send', { requestId: wire.newRequestId('send'), sessionId,
            overrides: [], message: { text: params.text, attachments: [] } })
        }
        case 'outcome': {
          const requestId = text(params.requestId)
          if (!requestId) throw new Error('an outcome query needs the request id')
          required('sendOutcome.query')
          return await wire.call('sendOutcome.query', { requestId })
        }
        case 'history': {
          if (!sessionId) throw new Error('history needs a session')
          required('history.snapshot')
          const older = text(params.olderCursor), resume = text(params.cursor)
          // A live resume cursor and a backward page cursor are different reads; sending both
          // would let the Server pick one while this side believed it asked for the other.
          if (older && resume) throw new WireError('INVALID_REQUEST', 'a history read either resumes the stream or pages backwards, never both')
          return await wire.call('history.snapshot', older
            ? { sessionId, page: { limit: 50, cursor: older } }
            : { sessionId, ...(resume ? { cursor: resume } : {}), page: { limit: 50 } })
        }
        case 'stream': {
          if (!sessionId) throw new Error('the event stream needs a session')
          openStream(sessionId, text(params.cursor))
          return {}
        }
        case 'stop': {
          const executionId = text(params.executionId)
          if (!sessionId || !executionId) throw new Error('stop needs a session and execution')
          required('runs.stop')
          return await wire.call('runs.stop', { requestId: wire.newRequestId('stop'), sessionId, executionId })
        }
        case 'decide': {
          const approvalId = text(params.approvalId)
          const expectedVersion = number(params.expectedVersion)
          const decision = text(params.decision)
          if (!approvalId || expectedVersion === undefined || (decision !== 'allow' && decision !== 'deny')) throw new Error('an approval decision needs id, version and allow or deny')
          required('approvals.decide')
          return await wire.call('approvals.decide', { requestId: wire.newRequestId('approval'), approvalId, expectedVersion, decision,
            scope: record(params.scope) ?? { kind: 'once' } })
        }
        case 'closeStream': {
          if (sessionId) { streams.get(sessionId)?.close(); streams.delete(sessionId) }
          return {}
        }
        default:
          throw new Error('Unsupported Ordessa Server operation')
      }
    }

    return {
      async send(input) {
        if (closed) throw new Error('Ordessa transport closed')
        const frame = record(input)
        if (!frame || !text(frame.method)) throw new Error('Invalid Ordessa native frame')
        return await dispatch(frame as Frame)
      },
      async close() {
        if (closed) return
        closed = true
        for (const stream of streams.values()) stream.close()
        streams.clear()
      },
    }
  } }
}
