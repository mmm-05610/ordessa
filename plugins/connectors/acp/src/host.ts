import type * as acp from '@agentclientprotocol/sdk'
import type { AgentWorkspaceInfo } from '@extensions/ordessa.agent-contracts/contract.js'
import type { AgentNativeBridge } from '../../../../apps/desktop/renderer/agent-native'
import type { AcpChannelHandle, AcpChannelSpec } from './channel'
import type { AcpControlledSubmission, AcpPermissionDecision, AcpSubmissionAdmission } from './submission'

/**
 * The renderer half of the desktop wiring: the ONLY module in this plugin that speaks the
 * `agentNative` bridge frames. It turns one orchestration-issued Server|Harness pair into the
 * same `AcpChannelSpec` the reviewed tests inject, so the production path and the target tests
 * drive one and the same client. Frame names here are this plugin's internal host contract; the
 * real Server seam (`acp.channel.open`, `workspaces.*`, `/wire/v1/acp-channel/{connectionId}`) is
 * owned entirely by native.ts, and a missing Server API surfaces as a refused frame, never as a
 * silently invented channel.
 */

const VALUE = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
const STR = (value: unknown): string | undefined => typeof value === 'string' && value ? value : undefined
const unwrap = (error: unknown): string =>
  (error instanceof Error ? error.message : String(error)).replace(/^Error invoking remote method '[^']+':\s*(?:Error:\s*)?/, '')

export interface AcpOrchestrationEntry {
  /** Orchestration-issued identity for this Server|Harness pair (never a plugin id). */
  serverInstanceId: string
  harness: { id: string; title: string }
}
export interface AcpOrchestration {
  /** False means this Server does not offer the ACP channel API yet — the honest no-op state. */
  offered: boolean
  entries: AcpOrchestrationEntry[]
}

export function parseAcpIdentity(value: unknown): AcpOrchestration {
  const raw = VALUE(value)
  if (typeof raw?.offered !== 'boolean') throw new Error('ACP orchestration identity is incomplete')
  if (!raw.offered) return { offered: false, entries: [] }
  if (!Array.isArray(raw.entries)) throw new Error('ACP orchestration identity has no entries')
  const entries = raw.entries.map(item => {
    const entry = VALUE(item)
    const serverInstanceId = STR(entry?.serverInstanceId), harness = VALUE(entry?.harness)
    const id = STR(harness?.id), title = STR(harness?.title)
    if (!serverInstanceId || !id || !title) throw new Error('ACP orchestration entry is incomplete')
    return { serverInstanceId, harness: { id, title } }
  })
  return { offered: true, entries }
}

/** One bridge instance answers for the whole Server: identity first, connectors derive per pair. */
export async function requestAcpOrchestration(adapterId: string, bridge: AgentNativeBridge) {
  const instanceId = await bridge.open(adapterId).catch((error: unknown) => { throw new Error(unwrap(error)) })
  try {
    const identity = parseAcpIdentity(await bridge.send(instanceId, { method: 'acp/identity' }))
    return { instanceId, orchestration: identity }
  } catch (error) {
    await bridge.close(instanceId).catch(() => undefined)
    throw new Error(unwrap(error))
  }
}

const parseProjects = (value: unknown): readonly AgentWorkspaceInfo[] => {
  const items = VALUE(value)?.items
  if (!Array.isArray(items)) throw new Error('ACP project list is malformed')
  return items.map(item => {
    const raw = VALUE(item)
    const id = STR(raw?.id), normalizedPath = STR(raw?.normalizedPath)
    if (!id || !normalizedPath) throw new Error('ACP project record is incomplete')
    return { id, normalizedPath }
  })
}
const parseBinding = (value: unknown, expectId: string): AgentWorkspaceInfo => {
  const raw = VALUE(value)
  const id = STR(raw?.id), normalizedPath = STR(raw?.normalizedPath)
  if (!id || !normalizedPath) throw new Error(`ACP project binding is incomplete: ${expectId}`)
  return { id, normalizedPath }
}

/**
 * The pair-bound spec: every call is one bridge frame against the orchestration instance, and
 * each acquired channel gets a message-stream bridge — inbound ACP frames arrive as `acp/message`
 * events routed by connectionId, outbound writes ride `acp/channel/send`, and `release()` is the
 * explicit backend stand-down. A transport death arrives as `acp/down` and only errors the stream:
 * it is never a release (the client's own rules decide what that means).
 */
export function hostChannelSpec(adapterId: string, bridge: AgentNativeBridge, instanceId: string, entry: AcpOrchestrationEntry): AcpChannelSpec {
  const inboxes = new Map<string, { message(message: acp.AnyMessage): void; down(reason: string): void }>()
  // The subscription outlives individual channels: events for released connections find no inbox
  // and are dropped. The plugin scope closes the instance itself.
  const unsubscribe = bridge.subscribe(event => {
    if (event.instanceId !== instanceId) return
    const frame = VALUE(event.frame)
    const connectionId = STR(frame?.connectionId)
    if (!connectionId) return
    const inbox = inboxes.get(connectionId)
    if (!inbox) return
    // The ACP message rides nested: the wrapper's own `method` names the bridge event, and the
    // agent's JSON-RPC frame must reach the SDK untouched.
    if (frame?.method === 'acp/message') {
      const message = VALUE(frame.params)?.frame
      if (message) inbox.message(message as acp.AnyMessage)
    }
    else if (frame?.method === 'acp/down') inbox.down(unwrap(String(VALUE(frame.params)?.reason ?? 'channel closed')))
  })
  const call = async (method: string, params: Record<string, unknown>) => {
    try { return await bridge.send(instanceId, { method, params }) }
    catch (error) { throw new Error(unwrap(error)) }
  }
  return {
    serverInstanceId: entry.serverInstanceId,
    harness: entry.harness,
    listProjects: async () => parseProjects(await call('acp/projects', { instanceId: entry.serverInstanceId })),
    openProject: async id => parseBinding(await call('acp/openProject', { instanceId: entry.serverInstanceId, id }), id),
    // The add rides the Server's existing `workspaces.open` upsert (native.ts owns that call and
    // validates the path); a Server without the capability refuses the frame honestly, and the UI
    // keeps the entry disabled.
    addProject: async path => parseBinding(await call('acp/addProject', { instanceId: entry.serverInstanceId, path }), 'added'),
    async acquireChannel(projectId) {
      const opened = VALUE(await call('acp/channel/open', { instanceId: entry.serverInstanceId, projectId }))
      const connectionId = STR(opened?.connectionId)
      if (!connectionId) throw new Error(`ACP channel open returned no connection id for project ${projectId}`)
      const binding = parseBinding(opened?.binding, projectId)
      let controller!: ReadableStreamDefaultController<acp.AnyMessage>
      const downListeners = new Set<(reason: string) => void>()
      let downReason: string | undefined
      const markDown = (reason: string) => {
        if (downReason !== undefined) return
        downReason = reason
        for (const listener of [...downListeners]) listener(reason)
        downListeners.clear()
      }
      const readable = new ReadableStream<acp.AnyMessage>({ start: c => { controller = c } })
      inboxes.set(connectionId, {
        message: message => { controller.enqueue(message) },
        down: reason => { markDown(reason); try { controller.error(new Error(reason)) } catch { /* already ended */ } },
      })
      const stream: acp.Stream = {
        readable,
        writable: new WritableStream<acp.AnyMessage>({
          write: async message => { await call('acp/channel/send', { connectionId, frame: message }) },
          close: () => { inboxes.delete(connectionId); markDown('channel stream closed') },
        }),
      }
      return {
        connectionId, binding, stream,
        subscribeDown(listener) {
          if (downReason !== undefined) listener(downReason)
          else downListeners.add(listener)
          return () => { downListeners.delete(listener) }
        },
        authorizeSubmission: async (submission: AcpControlledSubmission): Promise<AcpSubmissionAdmission> => {
          const answer = VALUE(await call('acp/channel/authorizeSubmission', { connectionId, submission }))
          if (answer?.kind === 'accepted' && answer.submissionId === submission.submissionId) {
            return { kind: 'accepted', submissionId: submission.submissionId }
          }
          if (answer?.kind === 'refused' && STR(answer.code) && STR(answer.reason)) {
            return { kind: 'refused', code: answer.code as string, reason: answer.reason as string }
          }
          if (answer?.kind === 'unknown' && STR(answer.operationId) && STR(answer.reason)) {
            return { kind: 'unknown', operationId: answer.operationId as string, reason: answer.reason as string }
          }
          throw new Error('ACP backend admission answer is malformed')
        },
        authorizePermission: async (decision: AcpPermissionDecision): Promise<AcpSubmissionAdmission> => {
          const answer = VALUE(await call('acp/channel/authorizePermission', { connectionId, decision }))
          if (answer?.kind === 'accepted' && answer.submissionId === decision.interactionId) {
            return { kind: 'accepted', submissionId: decision.interactionId }
          }
          if (answer?.kind === 'refused' && STR(answer.code) && STR(answer.reason)) {
            return { kind: 'refused', code: answer.code as string, reason: answer.reason as string }
          }
          if (answer?.kind === 'unknown' && STR(answer.operationId) && STR(answer.reason)) {
            return { kind: 'unknown', operationId: answer.operationId as string, reason: answer.reason as string }
          }
          throw new Error('ACP backend permission answer is malformed')
        },
        async release() {
          inboxes.delete(connectionId)
          markDown('ACP channel released')
          try { controller.error(new Error('ACP channel released')) } catch { /* already ended */ }
          await call('acp/channel/release', { connectionId })
        },
      } satisfies AcpChannelHandle
    },
  }
}
