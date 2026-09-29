/**
 * The Skills → Chat input contribution (Q1 / US6 / G17).
 *
 * Skills contributes DATA to Chat's existing `/` and `+` panel: one
 * `ChatInputSource` whose rows come from the CURRENT confirmed effective
 * snapshot of the running session. Everything this file is responsible for is
 * a refusal, not a capability:
 *
 * * **no invented invocation.** `skills.invokeDescriptor` is declared `unknown`
 *   for pi, codex and claude-code (`src/ordessa_skills/wire.py`,
 *   `harness_adapters/capabilities.py`), so `explicitInvocationSupported` is
 *   false and no entry carries an `invoke` action: the panel cannot render a
 *   "使用此 Skill" button for a call that does not exist (ux.md §Chat `/` 与
 *   `+`, spec.md US6). Rows that only the native Harness can use auto-say
 *   「可自动使用」.
 * * **no text-splicing disguised as a call.** A non-submittable row carries an
 *   `add-content` action that returns a typed `refused` rather than an
 *   `insert-command`: an inserted command text would edit the user's draft and
 *   read as a selection that did something (contracts.md §Chat 可消费的贡献
 *   forbids both "菜单选择时暗发消息" and pasting `SKILL.md`).
 * * **three ordering guards**, all of which a test can turn red:
 *   1. *session guard* — a reply from a superseded query (an older draft or a
 *      previous session) never paints the current menu (G17 「旧响应串到新会话」);
 *   2. *target guard* — a snapshot whose `targetSession` is not the one asked
 *      for is dropped, so a mis-routed read cannot cross sessions either;
 *   3. *generation guard* — a snapshot bound to a lower `runtimeGeneration`
 *      than the one already confirmed for that session cannot repaint it
 *      (G17 「旧 generation 响应不更新新会话」).
 * * **system command names are never displaced** — `skillSlashName()` takes the
 *   `/skills:` namespace on a collision, and an unreadable command catalog is
 *   treated as a collision (unknown is never assumed free).
 *
 * Registration goes through the published chat-api surface only
 * (`ChatContributionsService.forScope(scope).addInputSource`); the scope the
 * host issued owns the lifetime, so disposing it withdraws exactly the Skills
 * source and leaves every other source's rows untouched.
 */
import type {
  ChatContributionsService, ChatInputEntry, ChatInputQuery, ChatInputSource, ChatLocation,
} from '@extensions/ordessa.chat-api/contract.js'
import type { ResourceScope } from '@ordessa/extension-api'
import {
  SKILLS_CHAT_GROUP_EFFECTIVE, SKILLS_CHAT_GROUP_NATIVE, SKILLS_CHAT_GROUP_PENDING,
  SKILLS_CHAT_SOURCE_ID, SKILLS_CHAT_SOURCE_TITLE,
  invocationProven, skillSlashName,
  type SkillChoice, type SkillsChatInvokePort, type SkillsChatSnapshot, type SkillsChatSnapshotPort,
} from '../../contracts/src/chat'
import { originBadge } from './effect-text'

/** The row wording the ux.md §Chat rules require; kept here so a test can pin
 * the exact promise the menu makes. */
export const SKILLS_AUTO_ONLY_REASON = '可自动使用（该品牌无显式调用入口，选择不会发送消息）'
export const SKILLS_PENDING_REASON = '下次发送后可用（当前运行代次尚不可调用）'
export const SKILLS_NAME_CONFLICT_REASON = '名称与 Chat 系统命令冲突：仅只读浏览，不覆盖系统命令'
/** An answer without a runtime generation cannot support a "ready now" claim
 * (G17: the guard needs a confirmed generation; unknown is its own state). */
export const SKILLS_GENERATION_UNKNOWN_REASON = '运行代次未确认：不能承诺本次会话立即可用（待解析）'
export const SKILLS_UNCONFIRMED_NOTICE_ID = 'ordessa.skills.unconfirmed'
const SKILLS_UNCONFIRMED_REASON = '当前会话的 Skill 集合未确认：这不表示没有已启用的 Skill'
const NO_ROUTE_MESSAGE = '该 Skill 没有显式调用入口：不会发送消息，也不会写入草稿'

export interface SkillsChatSourceOptions {
  /** Reads the confirmed effective snapshot; never a draft preview. */
  snapshot: SkillsChatSnapshotPort
  /** The session owner's explicit-invocation route (Z2/C0). Absent means no
   * row is ever submittable, which is today's honest state for all brands. */
  invoke?: SkillsChatInvokePort
  /** Confirmed floors kept for stale-generation comparison across sessions. */
  historySize?: number
}

/** The source plus the read-only diagnostics the guards publish, so a test (or
 * the panel) can see what was actually confirmed instead of inferring it from
 * the rendered rows. */
export interface SkillsChatInputSource extends ChatInputSource {
  confirmedGeneration(sessionKey: string): number | null
  readonly activeSessionKey: string | null
}

/** Session identity for the menu, built from chat-api's own `ChatLocation`
 * fields (connectionId + serverInstanceId? + sessionId, else the draft id).
 * Never derived from a title or an endpoint (contracts.md §3). */
export function skillsSessionKey(location: ChatLocation): string {
  return location.kind === 'session'
    ? `session:${location.connectionId}|${location.serverInstanceId ?? '-'}|${location.sessionId}`
    : `draft:${location.draftId}|${location.connectionId ?? '-'}|${location.serverInstanceId ?? '-'}`
}

const byNameThenId = (a: SkillChoice, b: SkillChoice): number =>
  a.nativeName.localeCompare(b.nativeName) || a.assetId.localeCompare(b.assetId)

/** One entry id, unique inside the source even when a managed row and a native
 * observation carry the same assetId. */
const entryIdOf = (choice: SkillChoice): string => `ordessa.skills:${choice.assetId}:${choice.origin}`

const originText = (choice: SkillChoice): string =>
  choice.origin === 'native' ? '由 Harness 或项目提供（原生发现）' : originBadge(choice.origin)

/** The rows the current menu shows for one confirmed snapshot. Pure apart from
 * the invocation port it closes over. */
export function skillChoicesToEntries(
  snapshot: SkillsChatSnapshot,
  invoke: SkillsChatInvokePort | undefined,
): ChatInputEntry[] {
  // A missing runtime generation is unknown, not 0: no row may claim
  // "ready in this session" until a generation was actually confirmed (G17).
  const generationUnknown = snapshot.runtimeGeneration === null
  const rows = [...snapshot.skills].sort(byNameThenId).map((choice, index) => {
    const slash = skillSlashName(choice.nativeName, snapshot.systemCommandNames)
    const pending = choice.pendingUntilNextSend === true
    // A proven route needs all four: a confirmed generation, the flag, an
    // `invoke` descriptor for THIS asset/revision, and an injected session-owner
    // invoker.
    const callable = !pending && !generationUnknown && invocationProven(choice, invoke) && !slash.refused
    const unavailableReason = slash.refused
      ? SKILLS_NAME_CONFLICT_REASON
      : pending
        ? SKILLS_PENDING_REASON
        : generationUnknown
          ? SKILLS_GENERATION_UNKNOWN_REASON
          : NO_ROUTE_MESSAGE
    const availability: ChatInputEntry['availability'] = pending
      ? { kind: 'disabled', reason: SKILLS_PENDING_REASON }
      : slash.refused
        ? { kind: 'disabled', reason: SKILLS_NAME_CONFLICT_REASON }
        : generationUnknown
          ? { kind: 'disabled', reason: SKILLS_GENERATION_UNKNOWN_REASON }
          : callable
            ? { kind: 'ready' }
            : { kind: 'disabled', reason: SKILLS_AUTO_ONLY_REASON }
    const detail = [choice.description, originText(choice), snapshot.harnessId, choice.state]
      .filter((part): part is string => typeof part === 'string' && part.length > 0)
      .join(' · ')
    const action: ChatInputEntry['action'] = callable && invoke !== undefined
      // The location the panel selected at is the routing target; the session
      // owner (Z2/C0) sends the native call, never this source.
      ? { kind: 'invoke', execute: location => invoke({ targetSession: skillsSessionKey(location), choice, signal: new AbortController().signal }) }
      // Never `insert-command`: splicing text into the draft would look like a
      // call. A typed refusal is explicit and cannot be interpreted as success.
      : { kind: 'add-content', prepare: async () => ({ status: 'refused', message: unavailableReason }) }
    return {
      // A Skill never takes a name Chat's command catalog already owns: the
      // display name and the routing id both go into the `/skills:` namespace,
      // so nothing downstream can resolve this row as the system command.
      id: entryIdOf(choice),
      title: slash.namespaced ? `skills:${choice.nativeName}` : choice.nativeName,
      description: slash.namespaced ? `${detail} · 输入 ${slash.text}` : detail,
      groupId: pending ? SKILLS_CHAT_GROUP_PENDING : choice.origin === 'native' ? SKILLS_CHAT_GROUP_NATIVE : SKILLS_CHAT_GROUP_EFFECTIVE,
      order: index,
      surfaces: ['slash', 'plus'],
      availability,
      action,
    } satisfies ChatInputEntry
  })
  // Backend diagnostics ride to the panel as explicit notice rows: an
  // unavailable layer (mandatory policy unreadable, other-harness scopes) is
  // said, never filtered into silence (contracts.md 不可用不以静默过滤达成"成功").
  const diagnostics = (snapshot.diagnostics ?? []).map((diagnostic, index): ChatInputEntry => ({
    id: `ordessa.skills.diag:${diagnostic.code}:${diagnostic.assetId ?? '-'}`,
    title: `Skills 诊断 · ${diagnostic.code}`,
    description: diagnostic.assetId === null ? diagnostic.message : `${diagnostic.message}（${diagnostic.assetId}）`,
    groupId: SKILLS_CHAT_GROUP_EFFECTIVE,
    order: rows.length + index,
    surfaces: ['slash', 'plus'],
    availability: { kind: 'disabled', reason: `解析诊断 ${diagnostic.code}：${diagnostic.message}` },
    action: {
      kind: 'add-content',
      prepare: async () => ({ status: 'refused', message: `解析诊断 ${diagnostic.code}：${diagnostic.message}` }),
    },
  }))
  return [...rows, ...diagnostics]
}

const noticeEntry = (): ChatInputEntry => ({
  id: SKILLS_UNCONFIRMED_NOTICE_ID,
  title: 'Skills',
  description: SKILLS_UNCONFIRMED_REASON,
  groupId: SKILLS_CHAT_GROUP_EFFECTIVE,
  order: 0,
  surfaces: ['slash', 'plus'],
  availability: { kind: 'disabled', reason: SKILLS_UNCONFIRMED_REASON },
  action: { kind: 'add-content', prepare: async () => ({ status: 'refused', message: SKILLS_UNCONFIRMED_REASON }) },
})

export function createSkillsChatInputSource(options: SkillsChatSourceOptions): SkillsChatInputSource {
  const historyLimit = options.historySize ?? 8
  /** The last published rows per session key — what the menu currently shows. */
  const published = new Map<string, readonly ChatInputEntry[]>()
  /** The highest runtime generation confirmed per session key: the floor a
   * stale reply is measured against. */
  const floors = new Map<string, number>()
  const viewOf = (sessionKey: string): readonly ChatInputEntry[] => published.get(sessionKey) ?? []
  let active: { readonly token: number; readonly sessionKey: string } | null = null
  let sequence = 0

  const remember = (sessionKey: string, entries: readonly ChatInputEntry[]) => {
    published.set(sessionKey, entries)
    // The active session is never evicted: its floor is what the next reply is
    // measured against.
    while (published.size > historyLimit) {
      const oldest = [...published.keys()].find(key => key !== sessionKey)
      if (oldest === undefined) break
      published.delete(oldest)
      floors.delete(oldest)
    }
  }

  return {
    id: SKILLS_CHAT_SOURCE_ID,
    title: SKILLS_CHAT_SOURCE_TITLE,
    groups: [
      { id: SKILLS_CHAT_GROUP_EFFECTIVE, title: '本次会话可用', order: 20 },
      { id: SKILLS_CHAT_GROUP_PENDING, title: '下次发送后可用', order: 21 },
      { id: SKILLS_CHAT_GROUP_NATIVE, title: '由 Harness 或项目提供', order: 22 },
    ],
    confirmedGeneration: sessionKey => floors.get(sessionKey) ?? null,
    get activeSessionKey() { return active?.sessionKey ?? null },

    async query(request: ChatInputQuery): Promise<readonly ChatInputEntry[]> {
      const sessionKey = skillsSessionKey(request.location)
      const mine = { token: ++sequence, sessionKey }
      active = mine
      const isCurrent = () => active?.token === mine.token
      /** What the menu shows right now, for whichever session owns it. */
      const currentView = () => viewOf(active?.sessionKey ?? sessionKey)
      let snapshot: SkillsChatSnapshot | null
      try {
        snapshot = await options.snapshot.read({
          sessionKey,
          harnessId: request.location.harnessId ?? null,
          projectId: request.location.projectId ?? null,
          signal: request.signal,
        })
      } catch (failure) {
        // A read failure on a superseded query is not this session's error
        // either; the live query owns the state.
        if (!isCurrent()) return currentView()
        throw failure
      }

      // SESSION GUARD: this reply is no longer the menu the panel asked for.
      // Returning the *current* session's rows (never this reply's) means a
      // previous session's late result cannot overwrite a newer one, and an
      // older empty answer cannot blank it either.
      if (!isCurrent()) return currentView()

      // TARGET GUARD: the port answered about a different session — identity is
      // never guessed, so the reply is dropped and the current view stands.
      if (snapshot !== null && snapshot.targetSession !== sessionKey) return viewOf(sessionKey)

      if (snapshot === null) {
        const notice = [noticeEntry()]
        remember(sessionKey, notice)
        return notice
      }

      // GENERATION GUARD: an older confirmed generation never repaints a newer
      // one for the same session (G17). An answer without a generation is
      // unknown — it cannot prove it is newer either, so once a generation was
      // confirmed for this session only an equal-or-higher one may repaint.
      const floor = floors.get(sessionKey)
      if (snapshot.runtimeGeneration === null) {
        if (floor !== undefined) return viewOf(sessionKey)
        const unknownGenEntries = skillChoicesToEntries(snapshot, options.invoke)
        remember(sessionKey, unknownGenEntries)
        return unknownGenEntries
      }
      if (floor !== undefined && snapshot.runtimeGeneration < floor) return viewOf(sessionKey)

      const entries = skillChoicesToEntries(snapshot, options.invoke)
      floors.set(sessionKey, snapshot.runtimeGeneration)
      remember(sessionKey, entries)
      return entries
    },
  }
}

/**
 * Publish the source through the chat-api public surface and bind its lifetime
 * to the host-issued scope. Returns the registration disposable; disposing it
 * (or the scope) withdraws exactly the Skills source — the registry keeps every
 * other source's rows and status untouched.
 */
export function registerSkillsChatInputSource(
  chat: ChatContributionsService,
  scope: ResourceScope,
  source: ChatInputSource,
) {
  return chat.forScope(scope).addInputSource(source)
}

/** Build-and-register in one call for the activation path. */
export function attachSkillsChatContribution(
  chat: ChatContributionsService,
  scope: ResourceScope,
  options: SkillsChatSourceOptions,
): { readonly source: SkillsChatInputSource; readonly disposable: ReturnType<typeof registerSkillsChatInputSource> } {
  const source = createSkillsChatInputSource(options)
  return { source, disposable: registerSkillsChatInputSource(chat, scope, source) }
}

export type { SkillChoice, SkillsChatSnapshot, SkillsChatSnapshotPort, SkillsChatInvokePort }
