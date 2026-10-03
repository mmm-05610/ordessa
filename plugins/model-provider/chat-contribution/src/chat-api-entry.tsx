// authored in this line (Z3 T05, chat-api consumption): wires the model
// selector into the REAL published Chat contributions API.
// Consumed checkpoint: chat-api READY @ 54ad26c15d8480823374d85590919ba6bcca60d2
// (implementationSha a3ec20c046, token 'ordessa.chat.contributions.v1').
//
// SLOT MAPPING (recorded, not silently substituted): the model-provider design
// wording names a composer footer, but the frozen chat-api contract has no such
// slot — its six slots are frozen and the composer-attached one is
// `composer.toolbar` (Chat renders the composer's contribution area from it).
// This module therefore registers on the owner's published slot; if Z2 later
// freezes a footer slot the switch is mechanical (one slot string + order).
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ComponentType } from 'react'
import type { AgentSessions, AgentWorkspaceSnapshot } from '@extensions/ordessa.agent-contracts/contract.js'
import {
  chatContribution,
  defineChatComponentKey,
  type ChatComponentKey,
  type ChatContributionsService,
  type ChatLocation,
} from '@extensions/ordessa.chat-api/contract.js'
import type { IDisposable, ResourceScope } from '@ordessa/extension-api'
import type { ModelProviderService } from '@extensions/ordessa.model-provider/contract.js'
import { ModelSelector, type ComposerLocation, type QueuedChoice } from './selector'
import { createNextTurnClient, type NextTurnClient, type WireInvoke } from './next-turn-client'

export const MODEL_SELECTOR_ID = 'model-provider.composer.model-selector'

/** The submission guard of the independent model route (021 appendix §3.3).
 * Order 20: after the Profile guard (order 10), so a bound session's Profile
 * pipeline performs its single application first and this guard sees the
 * binding fact before deciding to do nothing. */
export const TURN_APPLICATION_GUARD_ID = 'ordessa.model-provider-chat.turn-application'
export const TURN_APPLICATION_GUARD_ORDER = 20

/** The contribution id whose live props carry the Profile glue's binding
 * facts (the bound/unbound dispatch seam; see `boundFactOf`). */
export const PROFILE_BINDING_CONTRIBUTION_ID = 'ordessa.profile-chat.picker'

/** The key this domain owns for its composer control (ordessa.chat.*
 * namespace via the contract's single factory). */
export const ModelSelectorKey: ChatComponentKey<{ location: ChatLocation }> =
  defineChatComponentKey<{ location: ChatLocation }>('ordessa.chat.model-selector', 1)

/** A per-session click-order serializer (021 §6c F1.2): tasks run one after
 * another, in submission order, so both contributions' registration wire
 * calls reach the Server in click order. */
export type RegistrationEnqueue = <T>(task: () => Promise<T>) => Promise<T>

export interface SelectorWiring {
  service: ModelProviderService
  /** The Server wire invoke; undefined = typed refusal at queue time
   * (REQ-Z3-5 still OPEN), never a silent no-op. */
  invoke?: WireInvoke
  sessions?: Pick<AgentSessions, 'getSnapshot' | 'subscribe' | 'prepareSubmission'>
  /** The bound/unbound dispatch fact for one chat location, read from the
   * Profile glue's registered bindings (see `boundFactOf`). Absent -> the
   * guard still dispatches correctly (the server decides), but the selector
   * skips its bound-mode read-only reconcile. */
  boundProbe?: (location: ChatLocation) => boolean
  /** The §6c F1.2 click-order seam: returns the Profile glue's per-session
   * serializer for this location, or null when the glue is absent/unbound
   * (the choose call then goes out directly, semantics unchanged). */
  registrationSeam?: (location: ChatLocation) => RegistrationEnqueue | null
}

const absentSnapshot: AgentWorkspaceSnapshot = { available: [] }
const absentSubscribe = () => () => undefined

/** Renders the migrated selector against the published ChatLocation shape,
 * owning a per-location next-turn client (queue → pending-next-turn;
 * late/foreign resolutions are rejected inside the client). */
export function ChatModelSelector({ wiring, location }: {
  wiring: SelectorWiring
  location: ChatLocation
}) {
  const snapshot = useSyncExternalStore(wiring.sessions?.subscribe ?? absentSubscribe,
    wiring.sessions?.getSnapshot ?? (() => absentSnapshot), wiring.sessions?.getSnapshot ?? (() => absentSnapshot))
  const identity = JSON.stringify([location.kind, location.connectionId,
    location.kind === 'session' ? location.sessionId : location.draftId,
    location.runtimeGeneration, snapshot.selectedConnectionId, snapshot.agent?.selectedSessionId,
    snapshot.draft?.active, snapshot.selectionRevision, snapshot.runtimeGeneration])
  return <NativeSessionSelector key={identity} wiring={wiring} location={location} snapshot={snapshot} />
}

function NativeSessionSelector({ wiring, location, snapshot }: {
  wiring: SelectorWiring; location: ChatLocation; snapshot: AgentWorkspaceSnapshot
}) {
  const [owner, setOwner] = useState<ComposerLocation | undefined>()
  const [reason, setReason] = useState('正在确认原生会话身份。')
  const [queued, setQueued] = useState<QueuedChoice | null>(null)
  const [lastConfirmed, setLastConfirmed] = useState<QueuedChoice | null>(null)
  const [current, setCurrent] = useState<import('./selector').ObservedModel | null>(null)
  const [queueError, setQueueError] = useState('')
  const [queueing, setQueueing] = useState(false)
  const live = useRef(true)
  const busy = useRef(false)
  const sessionId = location.kind === 'session' ? location.sessionId : undefined
  const isCurrent = useCallback(() => {
    const current = wiring.sessions?.getSnapshot()
    return live.current && location.kind === 'session' && !!current && !current.draft?.active
      && current.selectedConnectionId === location.connectionId
      && current.agent?.selectedSessionId === location.sessionId
      && current.agent?.connection.status === 'connected'
      && current.selectionRevision === snapshot.selectionRevision
      && current.runtimeGeneration === snapshot.runtimeGeneration
      && (location.runtimeGeneration === undefined || current.runtimeGeneration === location.runtimeGeneration)
  }, [wiring.sessions, location.kind, location.connectionId, sessionId, location.runtimeGeneration,
    snapshot.selectionRevision, snapshot.runtimeGeneration])
  useEffect(() => {
    live.current = true
    let active = true
    if (location.kind !== 'session') setReason('选择模型需要已有原生会话；草稿不会创建会话。')
    else if (!isCurrent() || !wiring.sessions?.prepareSubmission) setReason('当前原生会话身份不可用。')
    else {
      // Only the already-selected session branch is entered; never prepare a draft on render.
      void wiring.sessions.prepareSubmission().then(value => {
        if (!active || !isCurrent()) return
        if (value.sessionId !== location.sessionId
          || (location.serverInstanceId && value.serverInstanceId !== location.serverInstanceId)
          || ![value.serverInstanceId, value.harnessId, value.nativeSessionId].every(part => typeof part === 'string' && part.trim())) {
          setReason('原生会话身份不匹配。'); return
        }
        setOwner({ kind: 'session', session: { serverInstanceId: value.serverInstanceId,
          harnessId: value.harnessId, acpSessionId: value.nativeSessionId } })
        setReason('')
      }, cause => { if (active && isCurrent()) setReason(cause instanceof Error ? cause.message : String(cause)) })
    }
    return () => { active = false; live.current = false }
  }, [wiring.sessions, location.kind, sessionId, location.serverInstanceId, isCurrent])
  const client = useMemo(() => createNextTurnClient(wiring.invoke, owner ?? { kind: 'draft' }, isCurrent),
    [wiring.invoke, owner, isCurrent])
  // The submission guard of this wiring reads exactly this client per session,
  // so the send gate and the composer UI share one queue bookkeeping.
  useEffect(() => {
    if (!owner || owner.kind !== 'session') return
    const identity = JSON.stringify(owner.session)
    const clients = clientRegistryOf(wiring)
    clients.set(identity, { client, isCurrent })
    return () => { clients.delete(identity) }
  }, [client, owner, isCurrent, wiring])
  // Submit outcomes and reconciles update the projection live: a ready
  // consumed the intent (queue empty), a refusal keeps it visible.
  useEffect(() => client.onUpdate(() => {
    setQueued(client.pending)
    if (client.pending === null) setQueueError('')
  }), [client])
  const queryEpoch = useRef(0)
  const refresh = useCallback(async () => {
    if (!owner || busy.current || !isCurrent()) return
    const epoch = ++queryEpoch.current
    const observation = await client.query()
    if (!isCurrent() || epoch !== queryEpoch.current) return
    if (observation.state === 'observed') {
      setQueued(observation.desired); setLastConfirmed(observation.lastConfirmed); setCurrent(observation.current ?? null); setQueueError('')
    } else {
      setCurrent(null)
      setQueueError(`模型选择状态未知：${observation.code}；重新打开可查询，不会重试选择。`)
    }
  }, [owner, isCurrent, client])
  const observedOwner = useRef<ComposerLocation | undefined>(undefined)
  const runStatus = Object.values(snapshot.agent?.runs ?? {})
    .filter(run => location.kind === 'session' && run.sessionId === location.sessionId).at(-1)?.status ?? 'idle'
  // Chat reprojects location on every keystroke. Its object identity is not a
  // turn/application event: observe only the derived binding fact here.
  const profileBound = wiring.boundProbe?.(location) === true
  useEffect(() => {
    const firstObservation = owner !== undefined && observedOwner.current !== owner
    observedOwner.current = owner
    if (['running', 'starting', 'stop-requested'].includes(runStatus)) {
      // One read-only initial observation, never a mutation of the active turn.
      if (firstObservation) void refresh()
      return
    }
    // Bound mode (appendix §3.3): the Profile pipeline applied the intent, so
    // this side only syncs its projection with a read-only observation after
    // the send; unbound mode's submit already consumed the queue.
    if (profileBound && client.pending) {
      const epoch = ++queryEpoch.current
      void client.reconcile().then(outcome => {
        if (!isCurrent() || epoch !== queryEpoch.current) return
        if (outcome.state === 'refused') {
          setQueueError(`模型选择被核实为未应用：${outcome.code}；意图已保留。`)
        } else if (outcome.state === 'unknown-outcome') {
          setQueueError(`模型选择结果未知：${outcome.code}；请先核实。`)
        }
        return refresh()
      })
      return
    }
    void refresh()
  }, [refresh, runStatus, profileBound, client, isCurrent, owner])
  const inspect = useCallback(async (choice: QueuedChoice, version?: number) => {
    if (!owner || owner.kind !== 'session' || !wiring.invoke || !isCurrent())
      return { eligibility: 'unknown' as const, reason: '原生会话身份不可用。' }
    try {
      const answer = await wiring.invoke('modelProvider.inspectChoice', { target: owner.session,
        choice: { providerConfigId: choice.providerConfigId, modelId: choice.modelId } }) as {
          verdict?: string; reason?: string; providerConfigId?: string; configVersion?: number
        }
      if (!isCurrent()) return { eligibility: 'unknown' as const, reason: '会话已切换。' }
      if (answer?.providerConfigId !== choice.providerConfigId || !Number.isSafeInteger(answer.configVersion)
        || (version !== undefined && answer.configVersion !== version))
        return { eligibility: 'unknown' as const, reason: '模型判断的配置身份或版本不可核实。' }
      return { eligibility: answer.verdict === 'supported' ? 'ready' as const
        : answer.verdict === 'unsupported' ? 'unsupported' as const : 'unknown' as const,
        reason: answer.reason ?? (answer.verdict === 'supported' ? undefined : '模型可选择性未获确认。') }
    } catch (cause) {
      return { eligibility: 'unknown' as const, reason: cause instanceof Error ? cause.message : String(cause) }
    }
  }, [owner, wiring.invoke, isCurrent])
  const queue = async (choice: QueuedChoice) => {
    if (busy.current || !isCurrent()) return
    ++queryEpoch.current // a query begun before this explicit choice cannot overwrite its receipt
    busy.current = true; setQueueing(true); setQueueError('')
    try {
      const evidence = await inspect(choice, choice.configVersion)
      if (!isCurrent()) return
      if (evidence.eligibility !== 'ready') { setQueueError(evidence.reason ?? '此模型暂不可选。'); return }
      // §6c F1.2: the click's chooseForSession joins the Profile glue's
      // per-session click-order queue when one is projected, so the two
      // contributions' registration calls reach the Server in click order;
      // without the seam (no Profile glue / unbound) it goes out directly.
      const enqueue = wiring.registrationSeam?.(location) ?? null
      const outcome = enqueue ? await enqueue(() => client.queue(choice)) : await client.queue(choice)
      if (!isCurrent()) return
      if (outcome.state === 'pending-next-turn') setQueued(client.pending)
      else setQueueError(outcome.state === 'refused' ? `模型选择被拒绝：${outcome.code}` : `模型选择结果未知：${outcome.code}；请先核实。`)
    } finally {
      busy.current = false
      if (live.current) setQueueing(false)
    }
  }
  return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, minWidth: 0, maxWidth: '100%' }}>
    {reason && <span role="status" data-testid="model-owner-note" title={reason}
      aria-label={`${reason}；打开模型菜单查看完整原因。`}
      style={{ fontSize: 11, color: 'var(--ordessa-color-muted,#77777e)', whiteSpace: 'nowrap' }}>
      {location.kind === 'draft' ? '需先建会话' : '身份待确认'}
    </span>}
    {queueError && <span role="alert" data-testid="model-queue-error" title={queueError}
      style={{ fontSize: 11, color: 'var(--ordessa-color-danger,#b3261e)', minWidth: 64, maxWidth: 220,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{queueError}</span>}
    <ModelSelector service={wiring.service} location={owner ?? adaptLocation(location)}
      inspectChoice={inspect} disabled={!owner || queueing || !isCurrent()} queued={queued}
      lastConfirmed={lastConfirmed} current={current} onOpen={() => { void refresh() }}
      statusReason={reason}
      onQueue={choice => { void queue(choice) }} />
  </span>
}

/** The component bound to {@link ModelSelectorKey}. Chat resolves a
 * contribution by binding its key through `ui.bind(key, { required: false })`,
 * so the contribution registration alone renders nothing: the provider for
 * this key must be registered too. The service and the wire port are closed
 * over here, never passed through Chat's props. */
export function modelSelectorComponent(wiring: SelectorWiring): ComponentType<{ location: ChatLocation }> {
  return function ModelSelectorForLocation(props: { location: ChatLocation }) {
    return <ChatModelSelector wiring={wiring} location={props.location} />
  }
}

function adaptLocation(location: ChatLocation) {
  // ChatLocation → the selector's session reference; a draft has no native
  // session id, so the selector shows its honest "pick a harness/session
  // first" degradation and the client refuses to queue (TARGET_UNAVAILABLE).
  if (location.kind === 'session') {
    return { kind: 'session' as const, session: {
      serverInstanceId: location.serverInstanceId ?? '',
      harnessId: location.harnessId ?? '',
      acpSessionId: location.sessionId,
    } }
  }
  return { kind: 'draft' as const, target: {
    serverInstanceId: location.serverInstanceId ?? '',
    harnessId: location.harnessId ?? '',
    projectId: location.projectId ?? '',
  } }
}

/** Registers the selector under `scope`; disposing the returned handle (or
 * closing the scope) revokes exactly this registration — Chat keeps working
 * without it (US-4 absence comparison). Nothing here touches Chat's internal
 * store: the wiring travels as projection props keyed by ModelSelectorKey.
 *
 * 021 T04: the same scope also carries this route's submission guard. The
 * guard and the selector component share one client registry, so the send
 * gate reads exactly the queue bookkeeping the composer UI shows. */
export function registerModelSelector(
  chat: ChatContributionsService, scope: ResourceScope, wiring: SelectorWiring,
): IDisposable {
  const registration = chatContribution<{ location: ChatLocation }>({
    id: MODEL_SELECTOR_ID,
    slot: 'composer.toolbar',
    order: 100,
    key: ModelSelectorKey,
    project: (context) => {
      if (context.slot !== 'composer.toolbar') return { hidden: true as const }
      return {
        hidden: false as const,
        props: { location: context.location },
      }
    },
  })
  // The wiring travels through the KEY-BOUND COMPONENT (see
  // `modelSelectorComponent`), not through these projection props: Chat's
  // contribution context is a read-only display context and must not be handed
  // a service instance.
  void wiring
  const scoped = chat.forScope(scope)
  const clients = clientRegistryOf(wiring)
  const guard = scoped.addSubmissionGuard({
    id: TURN_APPLICATION_GUARD_ID,
    order: TURN_APPLICATION_GUARD_ORDER,
    async prepare(snapshot) {
      const target = snapshot.target
      if (target.kind !== 'session') return { status: 'ready' }
      const identity = targetIdentityOf(target)
      if (identity === undefined) return { status: 'ready' }
      // §6c F2.3 (codex review F2): the bound fact alone is no longer a
      // sufficient send permit — the NEWEST intent's handover fate gates the
      // send. The bound fact is re-projected fresh on every send, so a
      // registration/unregistration between click and send re-evaluates here.
      const bound = boundFactOf(chat, target)
      const registered = clients.get(JSON.stringify(identity))
      let fate = registered?.client.intentFate?.() ?? null
      if (bound && fate?.kind === 'independent') {
        // First Profile registration may have adopted this queue since the
        // click. Observe that handover; never apply it a second time here.
        const observation = await registered!.client.query()
        if (observation.state !== 'observed') return { status: 'unknown' }
        fate = registered!.client.intentFate()
      }
      if (bound && (!registered || fate?.kind === 'independent')) {
        try {
          if (!wiring.invoke) return { status: 'unknown' }
          const state = await wiring.invoke('modelProvider.queryChoice', { target: identity }) as {
            desired?: unknown; intentRoute?: string | null
          }
          if (state?.desired != null && state.intentRoute !== 'profile-overlay') {
            return { status: 'refused', reason: '模型意图尚未完成 Profile 交接；草稿与选择已保留。' }
          }
          if (!state || !Object.hasOwn(state, 'desired')) return { status: 'unknown' }
        } catch { return { status: 'unknown' } }
      }
      if (fate?.kind === 'handover-failed') {
        // the intent never reached the Profile overlay (or the handover is
        // unknown): zero prompt, draft and intent kept, explicit re-pick
        return { status: 'refused',
          reason: `模型选择转交 Profile 会话失败（${fate.code}）；本次发送已阻止，草稿与所选模型已保留，请重新选择模型。` }
      }
      if (fate?.kind === 'undecided') {
        // the queue answer named no route: an unsafe state is never read as
        // "independent" — blocked until an observation settles it
        return { status: 'refused',
          reason: `模型选择结果未知（${fate.code}）；本次发送已阻止，草稿与所选模型已保留，请重新打开模型选择器核实。` }
      }
      if (fate?.kind === 'routed' && !bound) {
        // the intent was handed to a Profile session whose binding has since
        // vanished: passing would send with zero evidence about the model
        return { status: 'refused',
          reason: '模型选择已转交 Profile 会话，但该绑定在发送前消失了；无证据不放行，请重新选择模型。' }
      }
      if (!bound) {
        const outcome = registered
          ? await registered.client.submitTurn()
          : await submitBlindly(wiring.invoke, identity)
        if (outcome.state === 'ready' || outcome.state === 'no-intent') return { status: 'ready' }
        if (outcome.state === 'refused') {
          return { status: 'refused', reason: `模型应用被拒绝：${outcome.code}；所选模型与草稿已保留，可显式重试。` }
        }
        return { status: 'unknown' }
      }
      // bound: the Profile guard (order 10, already run) performed the one
      // real application; this side only syncs its projection afterwards.
      return { status: 'ready' }
    },
  })
  const handle = scoped.addContribution(registration)
  let disposed = false
  return {
    get isDisposed() { return disposed },
    dispose() {
      if (disposed) return
      disposed = true
      guard.dispose()
      handle.dispose()
    },
  } as IDisposable
}

/** The live client registry one wiring shares between its composer components
 * (writers) and its submission guard (reader). Keyed by the wiring object, so
 * two registrations never share bookkeeping. */
const clientRegistries = new WeakMap<SelectorWiring, Map<string, { client: NextTurnClient; isCurrent: () => boolean }>>()
export function clientRegistryOf(wiring: SelectorWiring):
  Map<string, { client: NextTurnClient; isCurrent: () => boolean }> {
  let clients = clientRegistries.get(wiring)
  if (!clients) {
    clients = new Map()
    clientRegistries.set(wiring, clients)
  }
  return clients
}

/** The three native reference keys of a session location, or undefined when
 * the location cannot honestly name one (a missing key is never guessed). */
export function targetIdentityOf(target: ChatLocation): Record<string, string> | undefined {
  if (target.kind !== 'session') return undefined
  const { serverInstanceId, harnessId, sessionId } = target
  if (![serverInstanceId, harnessId, sessionId].every(
    value => typeof value === 'string' && value.trim())) return undefined
  return { serverInstanceId: serverInstanceId!, harnessId: harnessId!, acpSessionId: sessionId! }
}

/** The bound fact of one chat session, read through the published read-side
 * contribution view of the Profile glue. The glue projects its registered
 * binding (a backend fact it learned at registerNativeSession) into its live
 * picker props; its absence — no Profile extension, no binding — reads as
 * unbound. Never a guess from the UI session id alone. */
export function boundFactOf(chat: ChatContributionsService, target: ChatLocation): boolean {
  if (target.kind !== 'session') return false
  for (const view of chat.contributionsBySlot('composer.toolbar').getSnapshot()) {
    if (view.id !== PROFILE_BINDING_CONTRIBUTION_ID || !view.project) continue
    try {
      const projected = view.project({
        slot: 'composer.toolbar', location: target, connection: { status: 'unknown' },
      })
      if (projected.hidden) continue
      const bound = (projected.props as { boundNativeSession?: { serverInstanceId?: string; sessionId?: string } | null })
        ?.boundNativeSession
      if (bound && bound.serverInstanceId === target.serverInstanceId
        && bound.sessionId === target.sessionId) return true
    } catch {
      // an unreadable projection is absence, never a bound verdict
    }
  }
  return false
}

/** The §6c F1.2 click-order seam of one chat session, read through the same
 * published read-side projection as {@link boundFactOf}: the Profile glue's
 * per-session registration serializer. Null — no Profile extension, no
 * binding, unreadable projection — means the caller invokes its registration
 * wire call directly, exactly as before the seam existed. */
export function profileRegistrationSeamOf(chat: ChatContributionsService,
                                          target: ChatLocation): RegistrationEnqueue | null {
  if (target.kind !== 'session') return null
  for (const view of chat.contributionsBySlot('composer.toolbar').getSnapshot()) {
    if (view.id !== PROFILE_BINDING_CONTRIBUTION_ID || !view.project) continue
    try {
      const projected = view.project({
        slot: 'composer.toolbar', location: target, connection: { status: 'unknown' },
      })
      if (projected.hidden) continue
      const hook = (projected.props as { serializeRegistration?: RegistrationEnqueue | null })
        ?.serializeRegistration
      if (typeof hook === 'function') return hook
    } catch {
      // an unreadable projection is absence, never a seam
    }
  }
  return null
}

async function submitBlindly(invoke: WireInvoke | undefined,
                              target: Record<string, string>) {
  // The composer component did not register a client (e.g. the picker was
  // never opened). The server still owns the truth: a queued intent applies,
  // an empty queue answers no-intent and the send passes.
  if (!invoke) return { state: 'refused', code: 'MODEL_PROVIDER_CHAT_TRANSPORT_MISSING' } as const
  try {
    const answer = await invoke('modelProvider.beginTurnApplication', {
      target, operationKey: `chat-submit-${target.acpSessionId}-${globalThis.crypto.randomUUID()}`,
    }) as { outcome?: string; reason?: string | null }
    if (answer?.outcome === 'ready' || answer?.outcome === 'no-intent') return { state: 'ready' } as const
    if (answer?.outcome === 'refused') return { state: 'refused', code: answer.reason ?? 'OPERATION_UNKNOWN' } as const
    return { state: 'unknown-outcome', code: answer?.reason ?? 'OPERATION_UNKNOWN' } as const
  } catch (error) {
    const fact = error as { details?: { internalCode?: string } }
    return { state: 'unknown-outcome', code: fact?.details?.internalCode ?? 'OPERATION_UNKNOWN' } as const
  }
}

export { ModelSelector }
