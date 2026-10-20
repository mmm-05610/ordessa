// T11 tests — gate G17 (positive and negative) plus the registry behaviours the
// source must respect. All fakes are test-local: no live server reader exists
// in this repo (the `foundation` checkpoint is absent), so nothing here is L2/L3
// evidence — it is the L1 contract behaviour of the Chat face only.
import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import {
  createChatContributions,
  type ChatActionResult, type ChatInputEntry, type ChatInputQuery, type ChatInputSurface, type ChatLocation,
} from '@extensions/ordessa.chat-api/contract.js'
import {
  createSubagentInputSource, describeDefinition, SUBAGENT_INPUT_SOURCE_ID,
  type SubagentInputSourceDeps,
} from '../src/subagent-input-source'
import type {
  DefinitionState, EffectiveDefinition, ExistingNameIndex, InvokeGateway, InvokeGatewayRequest, SubagentDefinitionReader,
} from '../src/subagent-definitions'

// --- fixtures ----------------------------------------------------------------

const state = (over: Partial<DefinitionState> = {}): DefinitionState =>
  ({ projected: 'yes', loaded: 'unknown', invokable: 'unknown', used: 'unknown', ...over })

const definition = (over: Partial<EffectiveDefinition> = {}): EffectiveDefinition => ({
  definitionId: 'def-01', revision: 1, nativeName: 'reviewer', displayName: 'Reviewer',
  description: 'Read-only code reviewer', harnessId: 'claude', origin: 'managed', state: state(), ...over,
})

const draft = (draftId: string, harnessId = 'claude'): ChatLocation =>
  ({ kind: 'draft', draftId, connectionId: 'conn-1', harnessId, contextRevision: 1 })

const inputQuery = (
  location: ChatLocation, signal: AbortSignal = new AbortController().signal, query = '', surface: ChatInputSurface = 'plus',
): ChatInputQuery => ({ location, query, surface, signal })

/** Location identity as Chat defines it: the discriminated fields, never the
 * object reference — the panel dispatches `execute({ ...location })`, a copy. */
const locationKey = (location: ChatLocation): string => location.kind === 'draft'
  ? `draft|${location.draftId}|${location.connectionId ?? ''}|${location.serverInstanceId ?? ''}|${location.projectId ?? ''}|${location.harnessId ?? ''}|${location.contextRevision}`
  : `session|${location.connectionId}|${location.serverInstanceId ?? ''}|${location.sessionId}|${location.projectId ?? ''}|${location.harnessId ?? ''}|${location.contextRevision}`
const locationEquals = (a: ChatLocation, b: ChatLocation): boolean => locationKey(a) === locationKey(b)

const noExistingNames: ExistingNameIndex = { async names() { return [] } }

const recordingReader = (provide: (location: ChatLocation) => readonly EffectiveDefinition[]) => {
  const calls: ChatLocation[] = []
  const reader: SubagentDefinitionReader & { calls: ChatLocation[] } = {
    calls,
    async readEffective(location) { calls.push(location); return provide(location) },
  }
  return reader
}

const recordingGateway = (result: ChatActionResult = { status: 'accepted' }) => {
  const calls: InvokeGatewayRequest[] = []
  const gateway: InvokeGateway & { calls: InvokeGatewayRequest[] } = {
    calls,
    async invoke(request) { calls.push(request); return result },
  }
  return gateway
}

const depsFor = (over: Partial<SubagentInputSourceDeps> = {}): SubagentInputSourceDeps =>
  ({ gateway: null, existingNames: noExistingNames, isLocationCurrent: () => true, ...over })

const settle = async () => { await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0)) }

/** Narrows to the invoke action; the G17 negative tests additionally scan
 * `kind` across every emitted entry so this never hides a pseudo-call. */
const invokeExecute = (entry: ChatInputEntry) => {
  if (entry.action.kind !== 'invoke') throw new Error(`entry ${entry.id} carries ${entry.action.kind}, expected invoke`)
  return entry.action.execute
}

const disabledReason = (entry: ChatInputEntry): string => {
  if (entry.availability.kind !== 'disabled') throw new Error(`entry ${entry.id} is not disabled`)
  return entry.availability.reason
}

const CLAUDE_READY = definition({ state: state({ invokable: 'yes', loaded: 'yes' }) })

// --- registration through the REAL registry -----------------------------------

describe('registration (real createChatContributions)', () => {
  it('namespaces the source id and the real registry rejects a duplicate', () => {
    const chat = createChatContributions()
    const scope = new OwnedResources()
    const ui = chat.forScope(scope)
    const reader = recordingReader(() => [])
    ui.addInputSource(createSubagentInputSource(reader, depsFor()))
    expect(SUBAGENT_INPUT_SOURCE_ID).toBe('ordessa.assets.native-subagents')
    expect(() => ui.addInputSource(createSubagentInputSource(reader, depsFor())))
      .toThrowError(/ordessa\.assets\.native-subagents/)
    scope.dispose()
  })

  it('an aborted query keeps the previous entries and the source reports ready', async () => {
    const chat = createChatContributions()
    const scope = new OwnedResources()
    let calls = 0
    const reader: SubagentDefinitionReader = {
      async readEffective(location, signal) {
        calls++
        if (calls === 1) return [definition()]
        return new Promise<readonly EffectiveDefinition[]>(resolve => {
          signal.addEventListener('abort', () => resolve([]), { once: true })
        })
      },
    }
    chat.forScope(scope).addInputSource(createSubagentInputSource(reader, depsFor()))
    const first = chat.queryInputSources(inputQuery(draft('d1')))
    await settle()
    expect(first.getSnapshot()[0]!.entries.map(entry => entry.id)).toEqual(['managed/claude/def-01@r1'])
    const controller = new AbortController()
    const second = chat.queryInputSources(inputQuery(draft('d1'), controller.signal))
    expect(second.getSnapshot()[0]!.state.status).toBe('loading')
    controller.abort()
    await settle()
    expect(second.getSnapshot()[0]!.state.status).toBe('ready')
    expect(second.getSnapshot()[0]!.entries.map(entry => entry.id)).toEqual(['managed/claude/def-01@r1'])
    scope.dispose()
  })

  it('a late resolution for a stale location cannot write into the current result', async () => {
    const chat = createChatContributions()
    const scope = new OwnedResources()
    let releaseA: ((defs: readonly EffectiveDefinition[]) => void) | undefined
    const reader: SubagentDefinitionReader = {
      async readEffective(location) {
        if (location.kind === 'draft' && location.draftId === 'A')
          return new Promise<readonly EffectiveDefinition[]>(resolve => { releaseA = resolve })
        return [definition({ definitionId: 'def-b', nativeName: 'beta', displayName: 'Beta' })]
      },
    }
    chat.forScope(scope).addInputSource(createSubagentInputSource(reader, depsFor()))
    chat.queryInputSources(inputQuery(draft('A'))) // starts first, stays pending
    await settle()
    const current = chat.queryInputSources(inputQuery(draft('B'))) // supersedes A
    await settle()
    expect(current.getSnapshot()[0]!.entries.map(entry => entry.id)).toEqual(['managed/claude/def-b@r1'])
    releaseA!([definition({ definitionId: 'def-a-late', nativeName: 'alpha', displayName: 'Alpha' })])
    await settle()
    const ids = current.getSnapshot()[0]!.entries.map(entry => entry.id)
    expect(ids).toEqual(['managed/claude/def-b@r1']) // A's late result never surfaces
    expect(ids.some(id => id.includes('def-a-late'))).toBe(false)
    scope.dispose()
  })
})

// --- G17 positive: proved-invokable only --------------------------------------

describe('availability gate (G17 positive)', () => {
  it('a ready entry only when invokable=yes, delegating to the injected gateway with the location Chat passed at selection time', async () => {
    const gateway = recordingGateway()
    const reader = recordingReader(() => [CLAUDE_READY])
    const location = draft('d1')
    const entries = await createSubagentInputSource(reader, depsFor({ gateway })).query(inputQuery(location))
    expect(entries).toHaveLength(1)
    expect(entries[0]!.availability).toEqual({ kind: 'ready' })
    expect(entries[0]!.action.kind).toBe('invoke')
    // The panel dispatches `execute({ ...location })` — a copy of the current
    // target (chat-page.tsx), so identity is never the contract; value is.
    const result = await invokeExecute(entries[0]!)({ ...location })
    expect(result).toEqual({ status: 'accepted' })
    expect(gateway.calls).toHaveLength(1)
    expect(gateway.calls[0]!.location).toEqual(location)
    expect(gateway.calls[0]!.definition.definitionId).toBe('def-01')
  })

  it('a proved-invokable definition without an invocation owner stays disabled, never a hollow ready', async () => {
    const entries = await createSubagentInputSource(recordingReader(() => [CLAUDE_READY]), depsFor({ gateway: null }))
      .query(inputQuery(draft('d1')))
    expect(entries[0]!.availability.kind).toBe('disabled')
    expect(disabledReason(entries[0]!)).toContain('no invocation owner (InvokeGateway) is wired')
  })

  it('a stale location yields unavailable without any business call', async () => {
    const gateway = recordingGateway()
    const reader = recordingReader(() => [CLAUDE_READY])
    let current = true
    const source = createSubagentInputSource(reader, depsFor({ gateway, isLocationCurrent: () => current }))
    const entries = await source.query(inputQuery(draft('d1')))
    expect(reader.calls).toHaveLength(1)
    current = false // Chat moved to another target
    const result = await invokeExecute(entries[0]!)(draft('d1'))
    expect(result).toEqual({ status: 'unavailable' })
    expect(gateway.calls).toHaveLength(0)
    expect(reader.calls).toHaveLength(1) // reader not touched either
  })
})

// --- the selection-time location is the only authoritative target --------------

describe('selection-time location (chat-api r3, G17 stale-target rule)', () => {
  /** A ready entry built for draft A, with "current" meaning draft B: the
   * location valid at render time is not the location at selection time. */
  const readyForA = (gateway: InvokeGateway & { calls: InvokeGatewayRequest[] }, current: ChatLocation) => {
    const reader = recordingReader(() => [CLAUDE_READY])
    const seen: ChatLocation[] = []
    const source = createSubagentInputSource(reader, depsFor({
      gateway,
      isLocationCurrent: location => { seen.push(location); return locationEquals(location, current) },
    }))
    return { reader, seen, source }
  }

  it('the revalidation runs against the location Chat handed to execute, never the one the entry was queried for', async () => {
    const gateway = recordingGateway()
    const locationA = draft('A')
    const { reader, seen, source } = readyForA(gateway, draft('B'))
    const entries = await source.query(inputQuery(locationA))
    expect(reader.calls).toHaveLength(1) // the query itself legitimately read A
    const result = await invokeExecute(entries[0]!)({ ...draft('B') })
    expect(result).toEqual({ status: 'accepted' })
    // This is the assertion that fails loudly if anyone re-captures the query
    // location instead of using the argument: it would see A here.
    expect(seen).toHaveLength(1)
    expect(seen[0]!).toEqual(draft('B'))
    expect(seen[0]!).not.toEqual(locationA)
  })

  it('a foreign location reaches unavailable with zero gateway and zero reader calls, even though the query location was current', async () => {
    const gateway = recordingGateway()
    const { reader, seen, source } = readyForA(gateway, draft('A')) // A is still current
    const entries = await source.query(inputQuery(draft('A')))
    const result = await invokeExecute(entries[0]!)(draft('elsewhere', 'codex'))
    expect(result).toEqual({ status: 'unavailable' })
    expect(seen).toHaveLength(1)
    expect(seen[0]!).toEqual(draft('elsewhere', 'codex'))
    expect(gateway.calls).toHaveLength(0)
    expect(reader.calls).toHaveLength(1) // only the original query — nothing after selection
  })

  it('the gateway is entered exactly once and with the selection location object, not the render location', async () => {
    const gateway = recordingGateway()
    const sessionB: ChatLocation = { kind: 'session', connectionId: 'conn-1', sessionId: 's-2', harnessId: 'claude', contextRevision: 4 }
    const { source } = readyForA(gateway, sessionB)
    const entries = await source.query(inputQuery(draft('A')))
    expect(await invokeExecute(entries[0]!)(sessionB)).toEqual({ status: 'accepted' })
    expect(gateway.calls).toHaveLength(1)
    expect(gateway.calls[0]!.location).toEqual(sessionB)
    expect(gateway.calls[0]!.location).not.toEqual(draft('A'))
    expect(gateway.calls[0]!.definition).toBe(CLAUDE_READY)
  })

  it('a session selection is accepted where the same entry was rendered for a draft', async () => {
    // The entry set is per-query; the action must not assume the draft shape it
    // was built next to — the panel can hand it either ChatLocation variant.
    const gateway = recordingGateway()
    const { seen, source } = readyForA(gateway, { kind: 'session', connectionId: 'conn-1', sessionId: 's-1', contextRevision: 1 })
    const entries = await source.query(inputQuery(draft('A')))
    expect(await invokeExecute(entries[0]!)({ kind: 'session', connectionId: 'conn-1', sessionId: 's-1', contextRevision: 1 }))
      .toEqual({ status: 'accepted' })
    expect(seen[0]!.kind).toBe('session')
  })

  it('a disabled entry still refuses with zero business calls when Chat hands it a live location', async () => {
    const gateway = recordingGateway()
    const reader = recordingReader(() => [definition()]) // invokable unknown
    const entries = await createSubagentInputSource(reader, depsFor({ gateway })).query(inputQuery(draft('A')))
    expect(entries[0]!.availability.kind).toBe('disabled')
    const before = reader.calls.length
    expect(await invokeExecute(entries[0]!)(draft('A'))).toMatchObject({ status: 'refused' })
    expect(gateway.calls).toHaveLength(0)
    expect(reader.calls).toHaveLength(before)
  })
})

// --- G17 negative: no pseudo-call, unknown ≠ no --------------------------------

describe('no pseudo-call (G17 negative)', () => {
  const mixed = [
    definition({ definitionId: 'u-claude', harnessId: 'claude', nativeName: 'u-claude' }),
    definition({ definitionId: 'u-codex', harnessId: 'codex', nativeName: 'u-codex', state: state() }),
    definition({ definitionId: 'u-pi', harnessId: 'pi', nativeName: 'u-pi', state: state() }),
    definition({ definitionId: 'n-pi', harnessId: 'pi', nativeName: 'n-pi', origin: 'native-discovered' }),
    definition({ definitionId: 'r-claude', harnessId: 'claude', nativeName: 'r-claude', state: state({ invokable: 'yes', loaded: 'yes' }) }),
  ]

  it('emits no insert-command/add-content for any entry — invoke is the only action kind, ready or not', async () => {
    const gateway = recordingGateway()
    const entries = await createSubagentInputSource(recordingReader(() => mixed), depsFor({ gateway }))
      .query(inputQuery(draft('d1')))
    expect(entries).toHaveLength(5)
    const kinds = new Set(entries.map(entry => entry.action.kind))
    expect([...kinds]).toEqual(['invoke']) // the module is incapable of the pseudo-call trap
    const ready = entries.filter(entry => entry.availability.kind === 'ready')
    expect(ready.map(entry => entry.id)).toEqual(['managed/claude/r-claude@r1'])
  })

  it('when every state field is unknown no invoke path can be reached: all disabled, executing refuses with zero side effects', async () => {
    const gateway = recordingGateway()
    const reader = recordingReader(() => [
      definition({ definitionId: 'all-unknown', state: { projected: 'unknown', loaded: 'unknown', invokable: 'unknown', used: 'unknown' } }),
    ])
    const entries = await createSubagentInputSource(reader, depsFor({ gateway })).query(inputQuery(draft('d1')))
    expect(entries[0]!.availability.kind).toBe('disabled')
    const before = reader.calls.length
    const result = await invokeExecute(entries[0]!)(draft('d1'))
    expect(result.status).toBe('refused')
    expect((result as { status: 'refused'; message: string }).message).toContain('detail only')
    expect(result).not.toEqual({ status: 'accepted' })
    expect(gateway.calls).toHaveLength(0)
    expect(reader.calls).toHaveLength(before) // executing a disabled entry performs no business call
  })

  it('unknown and no produce different concrete reasons per pin brand', async () => {
    const sourceFor = (d: EffectiveDefinition) =>
      createSubagentInputSource(recordingReader(() => [d]), depsFor()).query(inputQuery(draft('d1')))
    const unknownClaude = disabledReason((await sourceFor(definition({ harnessId: 'claude', state: state({ invokable: 'unknown' }) })))[0]!)
    expect(unknownClaude).toContain('no proved control entry at pin @agentclientprotocol/claude-agent-acp@0.81.2')
    expect(unknownClaude).toContain('unobserved — unknown is not no')
    const absentClaude = disabledReason((await sourceFor(definition({ harnessId: 'claude', state: state({ invokable: 'no' }) })))[0]!)
    expect(absentClaude).toContain('observed as absent at pin @agentclientprotocol/claude-agent-acp@0.81.2')
    expect(absentClaude).not.toBe(unknownClaude)
    const unknownCodex = disabledReason((await sourceFor(definition({ harnessId: 'codex', state: state() })))[0]!)
    expect(unknownCodex).toContain('@agentclientprotocol/codex-acp@1.1.14')
    const unknownPi = disabledReason((await sourceFor(definition({ harnessId: 'pi', state: state() })))[0]!)
    expect(unknownPi).toContain('Pi extension-backed entry absent')
    const absentPi = disabledReason((await sourceFor(definition({ harnessId: 'pi', state: state({ invokable: 'no' }) })))[0]!)
    expect(absentPi).toContain('Pi extension-backed entry absent')
  })

  it('an unregistered brand cites no pin at all (G01 negative: no versioned claim from thin air)', async () => {
    const entry = (await createSubagentInputSource(recordingReader(() => [definition({ harnessId: 'mystery' })]), depsFor())
      .query(inputQuery(draft('d1'))))[0]!
    const reason = disabledReason(entry)
    expect(reason).toContain('harness "mystery" has no registered capability pin')
    expect(reason).not.toContain('@agentclientprotocol')
    expect(reason).not.toContain('@automatalabs')
  })

  it('native-discovered items are read-only detail even if a loader claims invokability', async () => {
    const entry = (await createSubagentInputSource(
      recordingReader(() => [definition({ origin: 'native-discovered', state: state({ invokable: 'yes' }) })]),
      depsFor({ gateway: recordingGateway() }),
    ).query(inputQuery(draft('d1'))))[0]!
    expect(entry.id).toContain('native/claude/')
    expect(disabledReason(entry)).toContain('native-discovered item is not managed by Ordessa')
  })

  it('a resolver refusal surfaces its code and detail verbatim', async () => {
    const entry = (await createSubagentInputSource(
      recordingReader(() => [definition({ refusal: { code: 'PERMISSION_EXCEEDS_CEILING', detail: 'Bash declared over the session ceiling' } })]),
      depsFor(),
    ).query(inputQuery(draft('d1'))))[0]!
    expect(disabledReason(entry)).toContain('PERMISSION_EXCEEDS_CEILING: Bash declared over the session ceiling')
  })
})

// --- query scoping and cancellation -------------------------------------------

describe('location scoping', () => {
  it('returns entries only for the location it was asked about', async () => {
    const reader = recordingReader(location =>
      location.kind === 'draft' && location.draftId === 'A'
        ? [definition({ definitionId: 'only-a' })]
        : [definition({ definitionId: 'only-b', nativeName: 'beta' })])
    const source = createSubagentInputSource(reader, depsFor())
    const a = await source.query(inputQuery(draft('A')))
    const b = await source.query(inputQuery(draft('B')))
    expect(a.map(entry => entry.id)).toEqual(['managed/claude/only-a@r1'])
    expect(b.map(entry => entry.id)).toEqual(['managed/claude/only-b@r1'])
    expect(reader.calls.map(location => location.kind === 'draft' ? location.draftId : '?')).toEqual(['A', 'B'])
  })

  it('a query issued on an already-aborted signal surfaces nothing new', async () => {
    const controller = new AbortController()
    controller.abort()
    const source = createSubagentInputSource(recordingReader(() => [definition()]), depsFor())
    const entries = await source.query(inputQuery(draft('d1'), controller.signal))
    expect(entries).toEqual([])
  })

  it('a superseded in-flight query never surfaces its own late result', async () => {
    let releaseA: ((defs: readonly EffectiveDefinition[]) => void) | undefined
    const reader: SubagentDefinitionReader = {
      async readEffective(location) {
        if (location.kind === 'draft' && location.draftId === 'A')
          return new Promise<readonly EffectiveDefinition[]>(resolve => { releaseA = resolve })
        return [definition({ definitionId: 'def-b' })]
      },
    }
    const source = createSubagentInputSource(reader, depsFor())
    const pendingA = source.query(inputQuery(draft('A')))
    const current = await source.query(inputQuery(draft('B')))
    expect(current.map(entry => entry.id)).toEqual(['managed/claude/def-b@r1'])
    releaseA!([definition({ definitionId: 'def-a-late' })])
    const late = await pendingA
    expect(late.map(entry => entry.id)).not.toContain('managed/claude/def-a-late@r1')
    expect(late.map(entry => entry.id)).toEqual(['managed/claude/def-b@r1']) // content-neutral replay of current
  })
})

// --- ordering, collisions, budgets ---------------------------------------------

describe('deterministic ordering', () => {
  const set = [
    definition({ definitionId: 'x2', harnessId: 'codex', nativeName: 'zeta', displayName: 'Zeta' }),
    definition({ definitionId: 'x1', harnessId: 'claude', nativeName: 'alpha', displayName: 'Alpha' }),
    definition({ definitionId: 'x3', harnessId: 'claude', nativeName: 'alpha', displayName: 'Alpha II', origin: 'native-discovered' }),
  ]
  const idsIn = (defs: readonly EffectiveDefinition[]) =>
    createSubagentInputSource(recordingReader(() => defs), depsFor()).query(inputQuery(draft('d1')))
    .then(entries => entries.map(entry => entry.id))

  it('is independent of the reader return order (never last-registered-wins)', async () => {
    const forward = await idsIn(set)
    const backward = await idsIn([...set].reverse())
    expect(backward).toEqual(forward)
    expect(forward).toEqual([
      'managed/claude/x1@r1', 'native/claude/x3@r1', 'managed/codex/x2@r1',
    ])
  })

  it('carries strictly ascending order fields and brand/origin visible in title and description', async () => {
    const entries = await createSubagentInputSource(recordingReader(() => set), depsFor()).query(inputQuery(draft('d1')))
    expect(entries.map(entry => entry.order)).toEqual([1, 2, 3])
    expect(entries.every(entry => entry.title.includes('·'))).toBe(true)
    expect(entries[0]!.description).toContain('Ordessa-managed')
    expect(entries[1]!.description).toContain('not Ordessa-managed')
    expect(entries.every(entry => entry.surfaces.join() === 'plus,slash')).toBe(true)
  })

  it('same nativeName from different ids disables every claimant with a diagnostic, no winner', async () => {
    const entries = await createSubagentInputSource(recordingReader(() => [
      definition({ definitionId: 'c1', nativeName: 'reviewer' }),
      definition({ definitionId: 'c2', nativeName: 'reviewer', displayName: 'Reviewer twin' }),
    ]), depsFor()).query(inputQuery(draft('d1')))
    expect(entries).toHaveLength(2)
    for (const entry of entries) expect(disabledReason(entry)).toContain('NATIVE_NAME_CONFLICT')
    expect(disabledReason(entries[0]!)).toContain('claimed by 2 definitions')
  })

  it('a collision with an existing slash command or Skill disables only the colliding item', async () => {
    const names: ExistingNameIndex = { async names() { return [{ name: 'reviewer', kind: 'slash-command' as const }] } }
    const entries = await createSubagentInputSource(
      recordingReader(() => [CLAUDE_READY, definition({ definitionId: 'other', nativeName: 'planner', displayName: 'Planner' })]),
      depsFor({ existingNames: names }),
    ).query(inputQuery(draft('d1')))
    const reviewer = entries.find(entry => entry.id.includes('def-01'))!
    expect(disabledReason(reviewer)).toContain('already owned by an existing slash command')
    expect(entries.find(entry => entry.id.includes('other'))!.availability.kind).toBe('disabled') // still unknown-evidence
    expect(entries.find(entry => entry.id.includes('other'))!.id).toBe('managed/claude/other@r1')
  })

  it('a reserved native name is detail-only', async () => {
    const entries = await createSubagentInputSource(
      recordingReader(() => [definition({ nativeName: 'main', state: state({ invokable: 'yes' }) })]),
      depsFor({ gateway: recordingGateway() }),
    ).query(inputQuery(draft('d1')))
    expect(disabledReason(entries[0]!)).toContain('reserved native name')
  })
})

describe('aggregate caps', () => {
  const three = [
    definition({ definitionId: 'b1', nativeName: 'a-one', displayName: 'One' }),
    definition({ definitionId: 'b2', nativeName: 'a-two', displayName: 'Two' }),
    definition({ definitionId: 'b3', nativeName: 'a-three', displayName: 'Three' }),
  ]

  it('a max entry count drops the tail only with a visible diagnostic entry', async () => {
    // sort order by nativeName: a-one < a-three < a-two, so b2 is the tail
    const entries = await createSubagentInputSource(recordingReader(() => three), depsFor({ limits: { maxEntries: 2 } }))
      .query(inputQuery(draft('d1')))
    expect(entries).toHaveLength(3) // 2 kept + 1 diagnostic — nothing silently dropped
    const diagnostic = entries.find(entry => entry.id === 'budget/diagnostic')!
    expect(diagnostic.availability.kind).toBe('disabled')
    expect(disabledReason(diagnostic)).toContain('managed/claude/b2@r1')
    expect(disabledReason(diagnostic)).not.toContain('b1@r1')
    expect(disabledReason(diagnostic)).not.toContain('b3@r1')
    const result = await invokeExecute(diagnostic)(draft('d1'))
    expect(result.status).toBe('refused')
  })

  it('a description budget drop is diagnosed the same way, and no budget means no diagnostic', async () => {
    const dropped = await createSubagentInputSource(
      recordingReader(() => three), depsFor({ limits: { maxDescriptionChars: 60 } }),
    ).query(inputQuery(draft('d1')))
    expect(dropped.some(entry => entry.id === 'budget/diagnostic')).toBe(true)
    const all = await createSubagentInputSource(recordingReader(() => three), depsFor()).query(inputQuery(draft('d1')))
    expect(all.some(entry => entry.id === 'budget/diagnostic')).toBe(false)
    expect(all).toHaveLength(3)
  })

  it('the query filter runs before budgeting and matches case-insensitively', async () => {
    const entries = await createSubagentInputSource(recordingReader(() => three), depsFor()).query(inputQuery(draft('d1'), undefined, 'TWO'))
    expect(entries.map(entry => entry.id)).toEqual(['managed/claude/b2@r1'])
  })
})

// --- detail payload (T09 reuse face) -------------------------------------------

describe('describeDefinition', () => {
  it('is a pure read-only detail projection that keeps unknown visible', () => {
    const d = definition({ state: { projected: 'unknown', loaded: 'unknown', invokable: 'unknown', used: 'unknown' } })
    const first = describeDefinition(d)
    expect(first).toEqual(describeDefinition(d)) // pure
    expect(first.state).toEqual(d.state) // the four facts pass through verbatim
    expect(first.usableFromChat).toBe(false)
    expect(first.detailOnlyReason).toContain('unobserved — unknown is not no')
    expect(Object.values(first)).not.toContain(undefined)
  })

  it('marks a proved-invokable detail usable while noting the runtime gates it cannot see', () => {
    const detail = describeDefinition(CLAUDE_READY)
    expect(detail.usableFromChat).toBe(true)
    expect(detail.detailOnlyReason).toContain('location revalidation')
  })

  it('detail for a native-discovered item states read-only provenance, never a degraded invoke', () => {
    const detail = describeDefinition(definition({ origin: 'native-discovered' }))
    expect(detail.usableFromChat).toBe(false)
    expect(detail.detailOnlyReason).toContain('not managed by Ordessa')
  })
})
