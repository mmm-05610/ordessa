/**
 * G17 / US6 — the Skills rows in Chat's `/` and `+` menu.
 *
 * The positives say the menu reads the confirmed snapshot. The counter-examples
 * are the point of the file: an automatic-only Skill must not grow a call
 * button (all three brands declare `skills.invokeDescriptor` unknown), a stale
 * runtime generation must not repaint a newer menu, a previous session's late
 * reply must not land in the new one, a pending profile choice is showable but
 * not submittable, and a system command name is never overwritten.
 *
 * The source is exercised through `createChatContributions()` — the published
 * chat-api service — because that is the object whose entry list the panel
 * renders; a stale reply that the registry paints is exactly the failure the
 * guards exist to prevent.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import {
  createChatContributions, type ChatInputEntry, type ChatInputQuery, type ChatInputSource,
} from '@extensions/ordessa.chat-api/contract.js'
import {
  SKILLS_AUTO_ONLY_REASON, SKILLS_GENERATION_UNKNOWN_REASON, SKILLS_NAME_CONFLICT_REASON, SKILLS_PENDING_REASON, SKILLS_UNCONFIRMED_NOTICE_ID,
  attachSkillsChatContribution, createSkillsChatInputSource, skillsSessionKey,
} from '../src/chatContribution'
import {
  SKILLS_CHAT_SOURCE_ID, type SkillChoice, type SkillsChatSnapshot, type SkillsChatSnapshotPort,
} from '../../contracts/src/chat'

const SESSION_KEY = 'session:c1|-|s1'
const OTHER_KEY = 'session:c1|-|s2'
const loc = (sessionId: string): ChatInputQuery['location'] => ({
  kind: 'session', connectionId: 'c1', sessionId, harnessId: 'pi', contextRevision: 1,
})
const panelQuery = (location: ChatInputQuery['location'], surface: 'plus' | 'slash' = 'slash'): ChatInputQuery => ({
  location, query: '', surface, signal: new AbortController().signal,
})
const flush = async () => { await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0)) }

const deferred = <T,>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const choice = (over: Partial<SkillChoice> = {}): SkillChoice => ({
  targetSession: SESSION_KEY, assetId: 'alpha', revision: 3, nativeName: 'alpha-doc',
  description: '处理 PDF', origin: 'public', state: '在有效集合（全局默认 / 所有 Harness · r3 决定）',
  explicitInvocationSupported: false, ...over,
})
const snap = (over: Partial<SkillsChatSnapshot> = {}): SkillsChatSnapshot => ({
  targetSession: SESSION_KEY, runtimeGeneration: 7, harnessId: 'pi', projectId: null,
  // An explicit empty catalog = "read it, nothing collides". Absent/null means
  // the catalog could not be read, and the row then keeps the `/skills:`
  // namespace instead of assuming a free name — see the naming block below.
  systemCommandNames: [],
  skills: [choice()], ...over,
})

/** A snapshot port whose replies the test releases by hand: the only way to
 * make an old generation or an old session arrive after a newer one. */
function scriptedPort() {
  const gates: ReturnType<typeof deferred<SkillsChatSnapshot | null>>[] = []
  const port: SkillsChatSnapshotPort = {
    read: () => { const gate = deferred<SkillsChatSnapshot | null>(); gates.push(gate); return gate.promise },
  }
  return { port, gates }
}

const ids = (entries: readonly ChatInputEntry[]) => entries.map(entry => entry.id)
const viewIds = (view: { getSnapshot(): readonly { source: ChatInputSource; entries: readonly ChatInputEntry[] }[] }, sourceId = SKILLS_CHAT_SOURCE_ID) => {
  const row = view.getSnapshot().find(item => item.source.id === sourceId)
  return row === undefined ? undefined : ids(row.entries)
}

const cleanup: OwnedResources[] = []
const newScope = () => { const scope = new OwnedResources(); cleanup.push(scope); return scope }
afterEach(() => { for (const scope of cleanup.splice(0).reverse()) scope.dispose() })

describe('skills chat input source: positives', () => {
  const mixed = (): SkillsChatSnapshot => snap({
    skills: [
      choice({ assetId: 'z', nativeName: 'zeta-proj', origin: 'project' }),
      choice({ assetId: 'a', nativeName: 'alpha-doc', origin: 'public' }),
      choice({ assetId: 'n', nativeName: 'beta-native', origin: 'native', state: '已投放，未确认装载' }),
      choice({ assetId: 'p', nativeName: 'pending-one', origin: 'profile', pendingUntilNextSend: true }),
    ],
  })

  it('lists the confirmed snapshot on the slash and plus surfaces in a stable order', async () => {
    const source = createSkillsChatInputSource({ snapshot: { read: async () => mixed() } })
    const entries = await source.query(panelQuery(loc('s1'), 'plus'))
    // Name then assetId, independent of the order the snapshot arrived in, so a
    // re-read never shuffles the panel (same rule as the settings list).
    expect(ids(entries)).toEqual([
      'ordessa.skills:a:public', 'ordessa.skills:n:native', 'ordessa.skills:p:profile', 'ordessa.skills:z:project',
    ])
    const alpha = entries[0]!
    expect(alpha.surfaces).toEqual(['slash', 'plus'])
    expect(alpha.title).toBe('alpha-doc')
    // 名称之外必须带上简介、来源、品牌与调用状态 (ux.md §Chat)
    expect(alpha.description).toContain('处理 PDF')
    expect(alpha.description).toContain('公共库')
    expect(alpha.description).toContain('pi')
    expect(alpha.description).toContain('在有效集合')
    expect(entries.find(e => e.id === 'ordessa.skills:n:native')!.description).toContain('由 Harness 或项目提供（原生发现）')
    expect(entries.find(e => e.id === 'ordessa.skills:n:native')!.description).toContain('已投放，未确认装载')
  })

  it('the published merge puts managed rows before pending ones and native observations last', async () => {
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(createSkillsChatInputSource({ snapshot: { read: async () => mixed() } }))
    const view = chat.queryInputSources(panelQuery(loc('s1'), 'plus'))
    await flush()
    expect(viewIds(view)).toEqual([
      'ordessa.skills:a:public', 'ordessa.skills:z:project', 'ordessa.skills:p:profile', 'ordessa.skills:n:native',
    ])
  })

  it('registers through the public chat-api service and withdraws only itself', async () => {
    const chat = createChatContributions()
    const skillsScope = newScope()
    const otherScope = newScope()
    const { source } = attachSkillsChatContribution(chat, skillsScope, { snapshot: { read: async () => snap() } })
    expect(source.id).toBe(SKILLS_CHAT_SOURCE_ID)
    chat.forScope(otherScope).addInputSource({
      id: 'other.source', title: 'Other', groups: [{ id: 'g', title: 'G', order: 1 }],
      query: async () => [{ id: 'other.row', title: 'other', groupId: 'g', order: 1, surfaces: ['plus'], availability: { kind: 'ready' }, action: { kind: 'insert-command', text: '/other' } }],
    })
    const view = chat.queryInputSources(panelQuery(loc('s1')))
    await flush()
    expect(viewIds(view)).toEqual(['ordessa.skills:alpha:public'])
    expect(viewIds(view, 'other.source')).toEqual(['other.row'])
    // Scope disposal is the withdrawal: the next query sees exactly the other
    // source, and its rows are untouched (the registry pins the source set at
    // query time, so the withdrawal is proved on the live seam, not on a view
    // captured before it).
    skillsScope.dispose()
    const after = chat.queryInputSources(panelQuery(loc('s1')))
    await flush()
    expect(after.getSnapshot().map(item => item.source.id)).toEqual(['other.source'])
    expect(ids(after.getSnapshot()[0]!.entries)).toEqual(['other.row'])
  })

  it('offers no unconfirmed snapshot as an empty menu: the notice says 未确认', async () => {
    const source = createSkillsChatInputSource({ snapshot: { read: async () => null } })
    const entries = await source.query(panelQuery(loc('s1')))
    expect(ids(entries)).toEqual([SKILLS_UNCONFIRMED_NOTICE_ID])
    expect(entries[0]!.availability).toEqual({ kind: 'disabled', reason: expect.stringContaining('未确认') })
    expect(source.confirmedGeneration(SESSION_KEY)).toBeNull()
  })
})

describe('skills chat input source: no fabricated invocation (G17, US6)', () => {
  // `skills.invokeDescriptor` is unknown for every shipped brand
  // (src/ordessa_skills/wire.py, harness_adapters/capabilities.py), so the menu
  // must not offer a call for any of them.
  for (const harnessId of ['pi', 'codex', 'claude-code']) {
    it(`${harnessId}: automatic-only rows say 可自动使用 and carry no invoke action`, async () => {
      const source = createSkillsChatInputSource({
        snapshot: { read: async () => snap({
          harnessId,
          skills: [
            choice({ assetId: 'auto', nativeName: 'auto-only' }),
            // Even a descriptor that looks callable is not callable without the
            // session-owner route: the flag has to be proved, not assumed.
            choice({ assetId: 'ghost', nativeName: 'ghost-descriptor', invokeDescriptor: { assetId: 'ghost', revision: 3, kind: 'browse-only' } }),
          ],
        }) },
      })
      const entries = await source.query(panelQuery(loc('s1')))
      expect(entries.some(entry => entry.action.kind === 'invoke')).toBe(false)
      // Nothing may splice text into the draft either — that would fake a call.
      expect(entries.some(entry => entry.action.kind === 'insert-command')).toBe(false)
      for (const entry of entries) {
        expect(entry.availability).toEqual({ kind: 'disabled', reason: SKILLS_AUTO_ONLY_REASON })
        expect(entry.availability.kind === 'disabled' && entry.availability.reason).toContain('可自动使用')
        if (entry.action.kind !== 'add-content') throw new Error('unreachable: a non-callable row must carry a refusal')
        const prepared = await entry.action.prepare(loc('s1'))
        expect(prepared.status).toBe('refused')
      }
    })
  }

  it('a proved flag alone is not a route; only the injected session owner produces an invoke', async () => {
    const callable = choice({ assetId: 'real', nativeName: 'real-invoke', explicitInvocationSupported: true, invokeDescriptor: { assetId: 'real', revision: 3, kind: 'invoke' } })
    const withoutOwner = createSkillsChatInputSource({ snapshot: { read: async () => snap({ skills: [callable] }) } })
    expect((await withoutOwner.query(panelQuery(loc('s1'))))[0]!.availability.kind).toBe('disabled')
    expect((await withoutOwner.query(panelQuery(loc('s1'))))[0]!.action.kind).not.toBe('invoke')

    const calls: string[] = []
    const withOwner = createSkillsChatInputSource({
      snapshot: { read: async () => snap({ skills: [callable] }) },
      invoke: async ({ targetSession }) => { calls.push(targetSession); return { status: 'accepted' as const } },
    })
    const entry = (await withOwner.query(panelQuery(loc('s1'))))[0]!
    expect(entry.availability).toEqual({ kind: 'ready' })
    if (entry.action.kind !== 'invoke') throw new Error('expected the proven route to be an invoke')
    expect(await entry.action.execute(loc('s1'))).toEqual({ status: 'accepted' })
    // The call goes to the session owner for THIS session; no message is written
    // into the draft, and nothing is sent behind the selection.
    expect(calls).toEqual([skillsSessionKey(loc('s1'))])
  })

  it('a pending profile choice is listed but labelled 下次发送后可用 and cannot be submitted', async () => {
    const source = createSkillsChatInputSource({
      snapshot: { read: async () => snap({ skills: [
        choice({ assetId: 'here', nativeName: 'available-now' }),
        // The Profile layer chose it; the running generation has not applied it.
        choice({ assetId: 'pend', nativeName: 'next-send', origin: 'profile', pendingUntilNextSend: true }),
      ] }) },
    })
    const entries = await source.query(panelQuery(loc('s1')))
    const pending = entries.find(entry => entry.id === 'ordessa.skills:pend:profile')!
    expect(pending.title).toBe('next-send')
    expect(pending.availability).toEqual({ kind: 'disabled', reason: SKILLS_PENDING_REASON })
    expect(pending.availability.kind === 'disabled' && pending.availability.reason).toContain('下次发送后可用')
    expect(pending.action.kind).not.toBe('invoke')
    if (pending.action.kind !== 'add-content') throw new Error('expected a refusal, not a command')
    const prepared = await pending.action.prepare(loc('s1'))
    expect(prepared.status).toBe('refused')
    // The control row is a different shape, so the label is not simply how every
    // row reads: the pending one sits in its own group.
    const readyRow = entries.find(entry => entry.id === 'ordessa.skills:here:public')!
    expect(readyRow.groupId).not.toBe(pending.groupId)
    expect(readyRow.availability.kind).toBe('disabled')
    expect(readyRow.availability.kind === 'disabled' && readyRow.availability.reason).not.toContain('下次发送后可用')
  })
})

describe('skills chat input source: stale results never reach the menu (G17)', () => {
  it('registry view: an older-generation reply leaves the merged menu on the newer rows', async () => {
    const chat = createChatContributions()
    const { port, gates } = scriptedPort()
    const source = createSkillsChatInputSource({ snapshot: port })
    chat.forScope(newScope()).addInputSource(source)
    const view = chat.queryInputSources(panelQuery(loc('s1')))
    gates[0]!.resolve(snap({ runtimeGeneration: 7, skills: [choice({ assetId: 'fresh', nativeName: 'fresh' })] }))
    await flush()
    expect(viewIds(view)).toEqual(['ordessa.skills:fresh:public'])

    // The panel re-queries (e.g. a keystroke); the reply that comes back is
    // bound to an older runtime generation.
    chat.queryInputSources(panelQuery(loc('s1')))
    gates[1]!.resolve(snap({ runtimeGeneration: 3, skills: [choice({ assetId: 'stale', nativeName: 'stale' })] }))
    await flush()
    expect(viewIds(view)).toEqual(['ordessa.skills:fresh:public'])
    expect(viewIds(view)).not.toContain('ordessa.skills:stale:public')
    expect(source.confirmedGeneration(SESSION_KEY)).toBe(7)
  })

  it('generation guard: a stale reply returns the current rows and keeps the floor', async () => {
    const { port, gates } = scriptedPort()
    const source = createSkillsChatInputSource({ snapshot: port })
    const fresh = source.query(panelQuery(loc('s1')))
    gates[0]!.resolve(snap({ runtimeGeneration: 7, skills: [choice({ assetId: 'fresh', nativeName: 'fresh' })] }))
    expect(ids(await fresh)).toEqual(['ordessa.skills:fresh:public'])

    const stale = source.query(panelQuery(loc('s1')))
    gates[1]!.resolve(snap({ runtimeGeneration: 4, skills: [choice({ assetId: 'stale', nativeName: 'stale' })] }))
    expect(ids(await stale)).toEqual(['ordessa.skills:fresh:public'])
    expect(source.confirmedGeneration(SESSION_KEY)).toBe(7)

    // A newer generation still gets through — the guard is staleness, not
    // "freeze the first answer".
    const newer = source.query(panelQuery(loc('s1')))
    gates[2]!.resolve(snap({ runtimeGeneration: 8, skills: [choice({ assetId: 'newer', nativeName: 'newer' })] }))
    expect(ids(await newer)).toEqual(['ordessa.skills:newer:public'])
    expect(source.confirmedGeneration(SESSION_KEY)).toBe(8)
  })

  it('session guard: a previous session reply arriving late never lands in the new session menu', async () => {
    const chat = createChatContributions()
    const { port, gates } = scriptedPort()
    chat.forScope(newScope()).addInputSource(createSkillsChatInputSource({ snapshot: port }))

    // Panel opens on session s1 (slow read), the user switches to s2 (fast read).
    const view = chat.queryInputSources(panelQuery(loc('s1')))
    chat.queryInputSources(panelQuery(loc('s2')))
    gates[1]!.resolve(snap({ targetSession: OTHER_KEY, skills: [choice({ assetId: 's2-row', nativeName: 's2-row' })] }))
    await flush()
    expect(viewIds(view)).toEqual(['ordessa.skills:s2-row:public'])

    // The s1 reply now arrives late: it must not repaint s2's menu.
    gates[0]!.resolve(snap({ targetSession: SESSION_KEY, skills: [choice({ assetId: 's1-row', nativeName: 's1-row' })] }))
    await flush()
    const entries = viewIds(view)
    expect(entries).toBeDefined()
    expect(entries).toEqual(['ordessa.skills:s2-row:public'])
    expect(entries).not.toContain('ordessa.skills:s1-row:public')
  })

  it('target guard: a snapshot about another session is dropped, not adopted', async () => {
    const source = createSkillsChatInputSource({
      snapshot: { read: async () => snap({ targetSession: OTHER_KEY, skills: [choice({ assetId: 'elsewhere', nativeName: 'elsewhere' })] }) },
    })
    expect(ids(await source.query(panelQuery(loc('s1'))))).toEqual([])
    expect(source.confirmedGeneration(SESSION_KEY)).toBeNull()
  })

  it('a read failure for the live query surfaces as the source error, never as an empty list', async () => {
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(createSkillsChatInputSource({
      snapshot: { read: async () => { throw new Error('snapshot unavailable') } },
    }))
    const view = chat.queryInputSources(panelQuery(loc('s1')))
    expect(view.getSnapshot()[0]!.state.status).toBe('loading')
    await flush()
    const state = view.getSnapshot()[0]!.state
    expect(state.status).toBe('error')
    expect(state.error).toContain('snapshot unavailable')
  })
})

describe('skills chat input source: slash names never displace system commands', () => {
  it('a colliding Skill takes the /skills: namespace instead of the command name', async () => {
    const source = createSkillsChatInputSource({
      snapshot: { read: async () => snap({ systemCommandNames: ['new', 'clear'], skills: [choice({ assetId: 'na', nativeName: 'new' })] }) },
    })
    const entries = await source.query(panelQuery(loc('s1')))
    expect(entries).toHaveLength(1)
    const row = entries[0]!
    expect(row.id).not.toBe('new')
    expect(row.title).toBe('skills:new')
    expect(row.description).toContain('输入 /skills:new')
    expect(row.title).not.toBe('new')
  })

  it('an unreadable command catalog is not assumed free: the namespace is applied', async () => {
    const source = createSkillsChatInputSource({
      snapshot: { read: async () => snap({ systemCommandNames: null, skills: [choice({ assetId: 'na', nativeName: 'new' })] }) },
    })
    expect((await source.query(panelQuery(loc('s1'))))[0]!.title).toBe('skills:new')
  })

  it('when even the namespace is taken the row is read-only and refuses instead of overwriting', async () => {
    const source = createSkillsChatInputSource({
      snapshot: { read: async () => snap({
        systemCommandNames: ['new', 'skills:new'],
        skills: [choice({ assetId: 'na', nativeName: 'new', explicitInvocationSupported: true, invokeDescriptor: { assetId: 'na', revision: 3, kind: 'invoke' } })],
      }) },
      invoke: async () => ({ status: 'accepted' as const }),
    })
    const row = (await source.query(panelQuery(loc('s1'))))[0]!
    expect(row.availability).toEqual({ kind: 'disabled', reason: SKILLS_NAME_CONFLICT_REASON })
    expect(row.action.kind).not.toBe('invoke')
    if (row.action.kind !== 'add-content') throw new Error('expected a refusal')
    const prepared = await row.action.prepare(loc('s1'))
    expect(prepared.status).toBe('refused')
    expect(prepared.status === 'refused' && prepared.message).toContain('不覆盖系统命令')
  })

  it('a proven-free name keeps its plain form (no gratuitous namespacing)', async () => {
    const source = createSkillsChatInputSource({
      snapshot: { read: async () => snap({ systemCommandNames: [], skills: [choice({ assetId: 'na', nativeName: 'new' })] }) },
    })
    const row = (await source.query(panelQuery(loc('s1'))))[0]!
    expect(row.title).toBe('new')
    expect(row.description).not.toContain('/skills:')
  })
})

describe('skills chat input source: generation discipline on real-data shapes (R-Q1-2)', () => {
  const invoker = async () => ({ status: 'accepted' as const })
  const callableChoice = choice({
    explicitInvocationSupported: true,
    invokeDescriptor: { assetId: 'alpha', revision: 3, kind: 'invoke' },
  })

  it('ready is granted only when a runtime generation was confirmed', async () => {
    const known = createSkillsChatInputSource({
      snapshot: { read: async () => snap({ skills: [callableChoice] }) }, invoke: invoker,
    })
    const readyRow = (await known.query(panelQuery(loc('s1')))).find(entry => entry.id === 'ordessa.skills:alpha:public')!
    expect(readyRow.availability).toEqual({ kind: 'ready' })
    // The snapshotGateway normalizes a missing `target.runtimeGeneration` to
    // null; a full route (flag + descriptor + invoker) still cannot claim
    // "usable now" on an unknown generation.
    const unknown = createSkillsChatInputSource({
      snapshot: { read: async () => snap({ runtimeGeneration: null, skills: [callableChoice] }) }, invoke: invoker,
    })
    const row = (await unknown.query(panelQuery(loc('s1')))).find(entry => entry.id === 'ordessa.skills:alpha:public')!
    expect(row.availability).toEqual({ kind: 'disabled', reason: SKILLS_GENERATION_UNKNOWN_REASON })
    if (row.action.kind === 'add-content') {
      await expect(row.action.prepare(loc('s1'))).resolves.toMatchObject({ status: 'refused' })
    } else {
      throw new Error('an unconfirmed generation must not carry an invoke action')
    }
    // Unknown never moves the floor: a later confirmed answer still rules.
    expect(unknown.confirmedGeneration(SESSION_KEY)).toBeNull()
  })

  it('an unknown-generation reply cannot repaint a menu whose generation was confirmed', async () => {
    const { port, gates } = scriptedPort()
    const source = createSkillsChatInputSource({ snapshot: port })
    const pendingQuery = source.query(panelQuery(loc('s1')))
    gates[0]!.resolve(snap({ runtimeGeneration: 7, skills: [choice({ assetId: 'fresh', nativeName: 'fresh' })] }))
    await expect(pendingQuery).resolves.toHaveLength(1)
    const lateQuery = source.query(panelQuery(loc('s1')))
    gates[1]!.resolve(snap({ runtimeGeneration: null, skills: [choice({ assetId: 'era-unknown', nativeName: 'era-unknown' })] }))
    const entries = await lateQuery
    expect(ids(entries)).toEqual(['ordessa.skills:fresh:public'])
    expect(source.confirmedGeneration(SESSION_KEY)).toBe(7)
  })

  it('backend diagnostics ride to the panel as explicit notice rows, never filtered', async () => {
    const source = createSkillsChatInputSource({
      snapshot: { read: async () => snap({ diagnostics: [
        { code: 'mandatory_policy_unavailable', message: '强制策略层不可读', assetId: null },
        { code: 'other_harness_scope', message: '其他品牌存在分配', assetId: 'x' },
      ] }) },
    })
    const entries = await source.query(panelQuery(loc('s1')))
    expect(ids(entries)).toEqual([
      'ordessa.skills:alpha:public',
      'ordessa.skills.diag:mandatory_policy_unavailable:-',
      'ordessa.skills.diag:other_harness_scope:x',
    ])
    const diag = entries[1]!
    expect(diag.availability.kind).toBe('disabled')
    expect(diag.description).toContain('强制策略层不可读')
    if (diag.action.kind !== 'add-content') throw new Error('a notice row never invokes')
    const prepared = await diag.action.prepare(loc('s1'))
    expect(prepared.status).toBe('refused')
  })
})
