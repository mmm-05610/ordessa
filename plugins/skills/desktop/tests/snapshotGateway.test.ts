/**
 * The real snapshot port (`snapshotGateway.ts`) against realistic
 * `skills.resolve` / `skills.previewEffective` / `skills.invokeDescriptor`
 * answers — the field names here are copied from the backend producers
 * (`assignments/resolver.py` `Resolution.view`, `service.py:398-414`), not
 * invented, because the point of Q1's half of api-requests.md §R-Q1-2 is
 * that the Chat menu is exercised by REAL wire data:
 *
 * * the round-trip binds `target.sessionRef`/`target.runtimeGeneration`,
 *   per-item `selectedBy`/`excludedBy`/`revision`/`capabilityEvidence.effect`
 *   and the resolution-level `diagnostics[]` onto the snapshot DTOs;
 * * a typed refusal (the `error_families.py` code table) surfaces as an
 *   explicit state (a `SkillsSnapshotRefusalError` with code + kind), never
 *   as a resolved empty menu;
 * * the generation guard gets real data: a lower `runtimeGeneration` payload
 *   cannot repaint, and a payload without one is `null` = unknown — it moves
 *   no floor and supports no "usable now" claim;
 * * 「下次发送后可用」 is driven by the answer's own session-override layer /
 *   `pending_until_next_send` diagnostic, not by a test-only flag.
 */
import { describe, expect, it } from 'vitest'
import type { ChatInputQuery } from '@extensions/ordessa.chat-api/contract.js'
import {
  SkillsSnapshotRefusalError, createSkillsSnapshotGateway, refusalFromWire,
  unloadedSkillsSnapshotPort, wireLayerKind,
} from '../src/snapshotGateway'
import { SKILLS_GENERATION_UNKNOWN_REASON, SKILLS_PENDING_REASON, createSkillsChatInputSource } from '../src/chatContribution'
import type { SkillsChatReadTarget, SkillsChatSnapshot, SkillsChatSnapshotPort } from '../../contracts/src/chat'

const SESSION = 'session:c1|-|s1'
const panelQuery = (): ChatInputQuery => ({
  location: { kind: 'session', connectionId: 'c1', sessionId: 's1', harnessId: 'pi', contextRevision: 1 },
  query: '', surface: 'slash', signal: new AbortController().signal,
})
const readTarget = (): SkillsChatReadTarget => ({
  sessionKey: SESSION, harnessId: 'pi', projectId: 'ordessa', signal: new AbortController().signal,
})

// —————————————————————————— realistic backend payloads (resolver.py shapes)

/** `service.py resolve` → `Resolution.view()`: exactly the camelCase keys
 * `resolver.py:110-156` emits. */
function resolvePayload(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    target: { projectId: 'ordessa', harnessId: 'pi', profileId: null, sessionRef: SESSION, runtimeGeneration: 7 },
    serverScope: 'scope:local',
    resolvedSkills: [
      {
        assetId: 'alpha', revision: 3, nativeName: 'alpha-doc', description: '处理 PDF',
        treeDigest: 'sha256:' + 'a'.repeat(64), originScope: 'public', originOwner: null,
        selectedBy: { layer: 'user_global_any', scopeKind: 'user_global', scopeId: '', harnessId: null, rowVersion: 2 },
        excludedBy: null, layerDecisions: [],
        capabilityEvidence: { effect: 'selected', discovery: 'unknown', isolation: 'unknown' },
      },
    ],
    excludedSkills: [
      { assetId: 'off', excludedBy: { layer: 'project_harness', scopeKind: 'project', scopeId: 'ordessa', harnessId: 'codex', rowVersion: 1 }, layerDecisions: [] },
      { assetId: 'never', excludedBy: null, absentReason: 'not_enabled', layerDecisions: [] },
    ],
    diagnostics: [],
    assignmentRevisions: { 'user_global_any|': 2 },
    profileRevision: null,
    ...over,
  }
}

/** A session-override row: `resolver.py:275-283` builds it from the wire's
 * `sessionOverrides` param; its decision layer is `session_override`
 * (`assignments/model.py:70`). It takes effect when the session next sends. */
function sessionOverrideItem(assetId = 'next'): Record<string, unknown> {
  return {
    assetId, revision: 1, nativeName: `${assetId}-doc`, description: null,
    treeDigest: null, originScope: 'profile', originOwner: 'p1',
    selectedBy: { layer: 'session_override', scopeKind: 'session', scopeId: SESSION, harnessId: 'pi', rowVersion: null },
    excludedBy: null, layerDecisions: [],
    capabilityEvidence: { effect: 'selected', discovery: 'unknown', isolation: 'unknown' },
  }
}

/** `service.py:398-414 invoke_descriptor` — today's truthful answer. */
const INVOKE_UNKNOWN = {
  harnessId: 'pi', invocation: 'unknown', browseOnly: true,
  reason: 'no verified explicit-invocation route for this brand',
  citation: 'specs/011-q1-skills/research/brand-matrix.md', versionPin: null, offeredCapabilityAxes: [],
}

type ScriptedStep = { answer?: unknown; failure?: unknown }
function scriptedWire(script: ScriptedStep[]) {
  const calls: { method: string; params: Record<string, unknown> }[] = []
  let index = 0
  const wire = {
    async call(method: string, params: Record<string, unknown>): Promise<unknown> {
      calls.push({ method, params })
      const step = script[index]
      index += 1
      if (step === undefined) throw Error(`unscripted wire call: ${method}`)
      if ('failure' in step && step.failure !== undefined) throw step.failure
      return step.answer ?? null
    },
  }
  return { wire, calls }
}

const refused = (code: string, message: string): Error => Object.assign(Error(message), { code })

/** The port's answer type is (rightly) "null = unconfirmed"; a resolved read
 * in these tests is asserted, never assumed. */
async function readResolved(port: SkillsChatSnapshotPort, target: SkillsChatReadTarget): Promise<SkillsChatSnapshot> {
  const snapshot = await port.read(target)
  if (snapshot === null) throw new Error('expected a resolved snapshot, got the unconfirmed answer (null)')
  return snapshot
}

describe('skills snapshot gateway: round-trip over realistic resolve answers', () => {
  it('calls skills.resolve with flat, wire-shaped params and binds every snapshot field', async () => {
    const { wire, calls } = scriptedWire([{ answer: resolvePayload() }, { answer: INVOKE_UNKNOWN }])
    const snapshot = await readResolved(createSkillsSnapshotGateway(wire), readTarget())
    // Flat params (`wire.py:_resolve_params`), never a nested `target`
    // envelope, and no client path/owner fields.
    expect(calls[0]!.method).toBe('skills.resolve')
    expect(calls[0]!.params).toEqual({ sessionRef: SESSION, harnessId: 'pi', projectId: 'ordessa' })
    expect(snapshot.targetSession).toBe(SESSION)
    expect(snapshot.runtimeGeneration).toBe(7)
    expect(snapshot.harnessId).toBe('pi')
    expect(snapshot.projectId).toBe('ordessa')
    // The Chat command catalog is not a Skills wire surface: unknown, never
    // "read it and it was free".
    expect(snapshot.systemCommandNames).toBeNull()
    const [alpha] = snapshot.skills
    expect(alpha).toMatchObject({
      targetSession: SESSION, assetId: 'alpha', revision: 3, nativeName: 'alpha-doc',
      description: '处理 PDF', origin: 'public', explicitInvocationSupported: false,
      pendingUntilNextSend: false, evidenceLevel: 'selected',
    })
    // Provenance travels verbatim: the resolver's own layer token + row version.
    expect(alpha!.selectedBy).toEqual({
      layer: 'user_global_any', scopeKind: 'user_global', scopeId: '', harnessId: null, rowVersion: 2,
    })
    expect(alpha!.excludedBy).toBeNull()
    expect(alpha).not.toHaveProperty('invokeDescriptor')
    // 调用状态 is worded only from resolver facts: the deciding scope plus the
    // graded evidence (`selected` with its `assignment_decision` proof).
    expect(alpha!.state).toContain('在有效集合')
    expect(alpha!.state).toContain('全局默认')
    expect(alpha!.state).toContain('证据 已选择，尚未投放')
  })

  it('maps the answer-level diagnostics verbatim as UI states', async () => {
    const payload = resolvePayload({
      diagnostics: [
        { kind: 'mandatory_policy_unavailable', reason: 'no permissions-api composed' },
        { kind: 'other_harness_scope', assetId: 'x', harnesses: ['claude'], note: 'assignments exist for other harness scopes' },
        { kind: 'mandatory_policy_applied', assetId: 'alpha', priorState: 'disable', policyDecision: 'enable' },
      ],
    })
    const { wire } = scriptedWire([{ answer: payload }, { answer: INVOKE_UNKNOWN }])
    const snapshot = await readResolved(createSkillsSnapshotGateway(wire), readTarget())
    expect(snapshot.diagnostics).toEqual([
      { code: 'mandatory_policy_unavailable', message: 'no permissions-api composed', assetId: null },
      { code: 'other_harness_scope', message: 'assignments exist for other harness scopes', assetId: 'x' },
      { code: 'mandatory_policy_applied', message: '策略决定 enable', assetId: 'alpha' },
    ])
  })

  it('reflects the per-brand invoke answer: unknown stays false, supported carries a matching descriptor', async () => {
    const unknown = scriptedWire([{ answer: resolvePayload() }, { answer: INVOKE_UNKNOWN }])
    const off = await readResolved(createSkillsSnapshotGateway(unknown.wire), readTarget())
    expect(off.skills[0]!.explicitInvocationSupported).toBe(false)
    const proven = scriptedWire([
      { answer: resolvePayload() },
      { answer: { ...INVOKE_UNKNOWN, invocation: 'supported', browseOnly: false, reason: undefined } },
    ])
    const on = await readResolved(createSkillsSnapshotGateway(proven.wire), readTarget())
    expect(on.skills[0]!.explicitInvocationSupported).toBe(true)
    expect(on.skills[0]!.invokeDescriptor).toEqual({ assetId: 'alpha', revision: 3, kind: 'invoke' })
  })

  it('a failed invoke probe is said through a diagnostic, never silently as "no route, confidently"', async () => {
    const { wire } = scriptedWire([
      { answer: resolvePayload() },
      { failure: refused('INVOKE_DESCRIPTOR_UNKNOWN', 'no plugin-queryable invocation seam') },
    ])
    const snapshot = await readResolved(createSkillsSnapshotGateway(wire), readTarget())
    expect(snapshot.skills).toHaveLength(1)
    expect(snapshot.skills[0]!.explicitInvocationSupported).toBe(false)
    expect(snapshot.diagnostics).toEqual([
      { code: 'INVOKE_ROUTE_UNKNOWN', message: expect.stringContaining('INVOKE_DESCRIPTOR_UNKNOWN'), assetId: null },
    ])
  })
})

describe('skills snapshot gateway: typed refusals are states, not empty menus', () => {
  it('a PROFILE_LAYER_UNAVAILABLE refusal rejects with code + explicit state', async () => {
    const { wire } = scriptedWire([{ failure: refused('PROFILE_LAYER_UNAVAILABLE', 'profile facet seam not composed (§G3)') }])
    const failure = await createSkillsSnapshotGateway(wire).read(readTarget())
      .then(() => null)
      .catch((error: unknown) => error) as SkillsSnapshotRefusalError
    expect(failure).toBeInstanceOf(SkillsSnapshotRefusalError)
    expect(failure.code).toBe('PROFILE_LAYER_UNAVAILABLE')
    expect(failure.kind).toBe('unavailable')
    expect(failure.retryable).toBe(true)
  })

  it('the chat source re-throws the refusal: the panel keeps an error state, the menu is not blanked', async () => {
    const ok = scriptedWire([{ answer: resolvePayload() }, { answer: INVOKE_UNKNOWN }])
    const failing = scriptedWire([{ failure: refused('SNAPSHOT_TARGET_MISMATCH', 'another target') }])
    const source = createSkillsChatInputSource({ snapshot: createSkillsSnapshotGateway(ok.wire) })
    await source.query(panelQuery())
    const switched = createSkillsChatInputSource({ snapshot: createSkillsSnapshotGateway(failing.wire) })
    // The source owns the current view; a refusal propagates rather than
    // resolving to [] which the panel would paint as "nothing installed".
    await expect(switched.query(panelQuery())).rejects.toThrow(/SNAPSHOT_TARGET_MISMATCH/)
  })

  it('an answer that said nothing is a refusal (RESOLVE_ANSWER_MISSING), never an empty success', async () => {
    const { wire } = scriptedWire([{ answer: null }])
    const failure = await createSkillsSnapshotGateway(wire).read(readTarget()).catch((error: unknown) => error) as SkillsSnapshotRefusalError
    expect(failure).toBeInstanceOf(SkillsSnapshotRefusalError)
    expect(failure.code).toBe('RESOLVE_ANSWER_MISSING')
    expect(failure.kind).toBe('malformed-answer')
    // A well-formed shell missing its declared lists is the same state class.
    const broken = scriptedWire([{ answer: { target: { sessionRef: SESSION }, diagnostics: [] } }])
    await expect(createSkillsSnapshotGateway(broken.wire).read(readTarget())).rejects.toThrow(/RESOLVE_ANSWER_MALFORMED/)
  })

  it('an unclassifiable wire failure still refuses with an explicit state', () => {
    const failure = refusalFromWire(new Error('connection reset by peer'))
    expect(failure.code).toBe('WIRE_ANSWER_UNCLASSIFIED')
    expect(failure.kind).toBe('unknown-refusal')
    expect(failure.retryable).toBe(false)
  })
})

describe('skills snapshot gateway: the generation guard runs on real data', () => {
  it('a payload with a lower runtimeGeneration than the confirmed floor cannot repaint the menu', async () => {
    const stale = resolvePayload({
      target: { projectId: 'ordessa', harnessId: 'pi', profileId: null, sessionRef: SESSION, runtimeGeneration: 3 },
      resolvedSkills: [{ ...sessionOverrideItem('stale'), selectedBy: { layer: 'user_global_any', scopeKind: 'user_global', scopeId: '', harnessId: null, rowVersion: 9 }, pending: undefined }],
    })
    const { wire } = scriptedWire([
      { answer: resolvePayload() }, { answer: INVOKE_UNKNOWN },
      { answer: stale }, { answer: INVOKE_UNKNOWN },
    ])
    const source = createSkillsChatInputSource({ snapshot: createSkillsSnapshotGateway(wire) })
    const fresh = await source.query(panelQuery())
    expect(fresh.map(entry => entry.id)).toContain('ordessa.skills:alpha:public')
    expect(source.confirmedGeneration(SESSION)).toBe(7)
    const after = await source.query(panelQuery())
    // The stale (generation 3) rows never appear; the confirmed view stands.
    expect(after.map(entry => entry.id)).toEqual(fresh.map(entry => entry.id))
    expect(after.map(entry => entry.id)).not.toContain('ordessa.skills:stale:profile')
    expect(source.confirmedGeneration(SESSION)).toBe(7)
  })

  it('a missing runtimeGeneration normalizes to null: no floor moves, no repaint over a confirmed one', async () => {
    const { target } = resolvePayload()
    const noGeneration = resolvePayload({
      target: { ...(target as Record<string, unknown>), runtimeGeneration: undefined },
      resolvedSkills: [sessionOverrideItem('unknown-era')],
    })
    const { wire } = scriptedWire([
      { answer: resolvePayload() }, { answer: INVOKE_UNKNOWN },
      { answer: noGeneration }, { answer: INVOKE_UNKNOWN },
    ])
    const source = createSkillsChatInputSource({ snapshot: createSkillsSnapshotGateway(wire) })
    await source.query(panelQuery())
    const after = await source.query(panelQuery())
    expect(source.confirmedGeneration(SESSION)).toBe(7)
    // The unknown-generation reply could not prove freshness → the confirmed
    // rows stand; the "usable now" claim was never granted to it.
    expect(after.map(entry => entry.id)).not.toContain('ordessa.skills:unknown-era:profile')
  })

  it('an unknown generation paints as its own disabled state before any floor exists', async () => {
    const noGeneration = resolvePayload({
      target: { projectId: null, harnessId: 'pi', profileId: null, sessionRef: SESSION },
    })
    const { wire } = scriptedWire([{ answer: noGeneration }, { answer: INVOKE_UNKNOWN }])
    const source = createSkillsChatInputSource({ snapshot: createSkillsSnapshotGateway(wire) })
    const entries = await source.query(panelQuery())
    const row = entries.find(entry => entry.id === 'ordessa.skills:alpha:public')!
    expect(row.availability).toEqual({ kind: 'disabled', reason: SKILLS_GENERATION_UNKNOWN_REASON })
    expect(source.confirmedGeneration(SESSION)).toBeNull()
    // A later confirmed-generation answer can still establish the floor.
    const later = scriptedWire([{ answer: resolvePayload() }, { answer: INVOKE_UNKNOWN }])
    const laterSource = createSkillsChatInputSource({ snapshot: createSkillsSnapshotGateway(later.wire) })
    await laterSource.query(panelQuery())
    expect(laterSource.confirmedGeneration(SESSION)).toBe(7)
  })
})

describe('skills snapshot gateway: pending 「下次发送后可用」 from real diagnostics', () => {
  it('a session_override selectedBy makes the row pending; a plain layer does not', async () => {
    const payload = resolvePayload({
      resolvedSkills: [
        (resolvePayload().resolvedSkills as Record<string, unknown>[])[0],
        sessionOverrideItem('next'),
      ],
    })
    const { wire } = scriptedWire([{ answer: payload }, { answer: INVOKE_UNKNOWN }])
    const snapshot = await readResolved(createSkillsSnapshotGateway(wire), readTarget())
    expect(snapshot.skills.find(s => s.assetId === 'alpha')!.pendingUntilNextSend).toBe(false)
    const next = snapshot.skills.find(s => s.assetId === 'next')!
    expect(next.pendingUntilNextSend).toBe(true)
    expect(next.state).toContain('本次会话')
    expect(next.state).toContain('待本次发送生效')
    // Through the source: pending rows sit in the 下次发送后可用 group and
    // refuse with the pending wording, never a silently submittable row.
    const source = createSkillsChatInputSource({ snapshot: createSkillsSnapshotGateway(
      scriptedWire([{ answer: payload }, { answer: INVOKE_UNKNOWN }]).wire,
    ) })
    const entries = await source.query(panelQuery())
    const row = entries.find(entry => entry.id === 'ordessa.skills:next:profile')!
    expect(row.groupId).toBe('ordessa.skills.pending')
    expect(row.availability).toEqual({ kind: 'disabled', reason: SKILLS_PENDING_REASON })
    if (row.action.kind === 'add-content') {
      await expect(row.action.prepare(panelQuery().location)).resolves.toMatchObject({ status: 'refused' })
    } else {
      throw new Error('a pending row must never carry an invoke action')
    }
  })

  it('a pending_until_next_send diagnostic drives the same state without the layer', async () => {
    const payload = resolvePayload({ diagnostics: [{ kind: 'pending_until_next_send', assetId: 'alpha' }] })
    const { wire } = scriptedWire([{ answer: payload }, { answer: INVOKE_UNKNOWN }])
    const snapshot = await readResolved(createSkillsSnapshotGateway(wire), readTarget())
    expect(snapshot.skills[0]!.pendingUntilNextSend).toBe(true)
  })

  it('previewEffective is opt-in only: the chat menu default stays the confirmed resolve', async () => {
    const byDefault = scriptedWire([{ answer: resolvePayload() }, { answer: INVOKE_UNKNOWN }])
    await createSkillsSnapshotGateway(byDefault.wire).read(readTarget())
    expect(byDefault.calls[0]!.method).toBe('skills.resolve')
    const drafted = scriptedWire([{ answer: resolvePayload() }, { answer: INVOKE_UNKNOWN }])
    await createSkillsSnapshotGateway(drafted.wire, { method: 'skills.previewEffective' }).read(readTarget())
    expect(drafted.calls[0]!.method).toBe('skills.previewEffective')
  })
})

describe('skills snapshot gateway: honest fallbacks', () => {
  it('a snapshot echoed about another session is passed through for the target guard, not adopted', async () => {
    const payload = resolvePayload({ target: { projectId: null, harnessId: 'pi', profileId: null, sessionRef: 'session:c1|-|other', runtimeGeneration: 9 } })
    const { wire } = scriptedWire([{ answer: payload }, { answer: INVOKE_UNKNOWN }])
    const snapshot = await readResolved(createSkillsSnapshotGateway(wire), readTarget())
    expect(snapshot.targetSession).toBe('session:c1|-|other')
  })

  it('the unloaded port answers null so the menu renders the 未确认 notice, not an empty list', async () => {
    await expect(unloadedSkillsSnapshotPort.read(readTarget())).resolves.toBeNull()
  })

  it('layer tokens map onto display kinds, unknowns fall to none', () => {
    expect(wireLayerKind('user_global_harness')).toBe('user-global')
    expect(wireLayerKind('project_any')).toBe('project')
    expect(wireLayerKind('session_override')).toBe('session')
    expect(wireLayerKind('mandatory_policy')).toBe('mandatory')
    expect(wireLayerKind('brand_new_layer')).toBe('none')
  })
})
