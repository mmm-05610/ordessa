// Type-level counterexamples for the chat-api public surface (spec R06: type
// counterexamples are deliverables). Checked with the desktop sources by
// apps/desktop/tsconfig.json and by the package `typecheck` script; never
// bundled and never runtime-loaded. A relaxed type silently fails this file,
// because every expectation directive below must actually fire.
import type { ChatComponentKey, ChatLocation, ChatSubmissionResult } from './contract'
import { chatContribution, ChatComposerKey, ChatMessageBodyKey, ChatReasoningKey, ChatToolActivityKey, ChatContributionsToken } from './contract'

interface BodyProps { readonly body: string }
interface WiderProps { readonly body: string; readonly extra: number }

declare const bodyKey: ChatComponentKey<BodyProps>
declare const widerKey: ChatComponentKey<WiderProps>
declare const scope: import('@ordessa/extension-api').ResourceScope

// --- positives: the shapes the contract promises are usable as written ---------
const messageKey = ChatMessageBodyKey
void (messageKey satisfies { readonly id: string; readonly major: number })
const platformKey: import('@ordessa/ui-components/api').UiComponentKey<import('./contract').ChatMessageBodyProps> = messageKey
void platformKey
const project: import('./contract').ChatProjection<import('./contract').ChatMessageBodyProps> = context =>
  context.slot === 'composer.toolbar' && context.location.kind === 'draft'
    ? { hidden: false, props: { conversationKey: 'c1', messageId: 'm1', role: 'assistant', body: 'hi', status: 'complete' } }
    : { hidden: true }
const contribution = chatContribution({
  id: 'sample.body', slot: 'composer.toolbar', order: 1, key: messageKey, project,
})
void contribution
void chatContribution({ id: 'sample.reasoning', slot: 'session.actions', order: 2, key: ChatReasoningKey })
void chatContribution({
  id: 'sample.diff', slot: 'content.renderers', order: 3, key: ChatToolActivityKey, contentKind: 'sample.diff',
  decode: payload => {
    if (typeof payload !== 'object' || payload === null) return null
    const record = payload as { readonly kind?: unknown }
    if (record.kind !== 'sample.diff') return null
    return { conversationKey: 'c1', toolId: 't1', title: 'Diff', state: 'completed' as const }
  },
})
void chatContribution({ id: 'sample.composer', slot: 'settings.sections', order: 4, key: ChatComposerKey })
void (ChatContributionsToken.name === 'ordessa.chat.contributions.v1')
declare const service: import('./contract').ChatContributionsService
void (service.forScope satisfies (scope: import('@ordessa/extension-api').ResourceScope) => {
  addContribution(registration: import('./contract').ChatContributionRegistration): import('@ordessa/extension-api').IDisposable
  addInputSource(source: import('./contract').ChatInputSource): import('@ordessa/extension-api').IDisposable
})

// --- negatives: every relaxation below must be a compile error -----------------
{
  // @ts-expect-error a lookalike object cannot fabricate the C7 key brand
  const forged: ChatComponentKey<BodyProps> = { id: 'ordessa.chat.forged', major: 1 }
  void forged
}
{
  // @ts-expect-error a contribution whose props do not match its key must not typecheck
  chatContribution<BodyProps>({ id: 'bad.body', slot: 'composer.toolbar', order: 1, key: widerKey, project: () => ({ hidden: false, props: { body: 'x' } }) })
}
{
  // The conditional slot rules below are enforced by the factory at RUNTIME
  // (TypeError): the type signature cannot express "required only for this
  // slot member". chat-api.test.ts asserts both rejections for real.
  void chatContribution({ id: 'bad.renderer', slot: 'content.renderers', order: 1, key: messageKey, contentKind: 'bad.kind' })
  void chatContribution({ id: 'bad.kind-slot', slot: 'session.auxiliary', order: 1, key: messageKey })
}
{
  // @ts-expect-error callers cannot self-issue an owner id; ownership comes from the scope
  chatContribution({ id: 'bad.owner', slot: 'composer.toolbar', order: 1, key: messageKey, ownerId: 'sample' })
}
{
  const render = (result: ChatSubmissionResult): string => {
    switch (result.status) {
      case 'accepted': return 'accepted'
      case 'refused': return result.reason
      case 'unknown': return 'unknown'
      default: {
        const exhaustive: never = result
        // @ts-expect-error ChatSubmissionResult has exactly three states; a fourth member is rejected
        return exhaustive.status
      }
    }
  }
  void render
}
{
  const entry: import('./contract').ChatInputEntry = {
    id: 'e1', title: 'Entry', groupId: 'g', order: 1, surfaces: ['plus'],
    // @ts-expect-error a disabled availability must carry its reason
    availability: { kind: 'disabled' },
    action: { kind: 'insert-command', text: '/x' },
  }
  void entry
}
{
  const location: ChatLocation = { kind: 'session', connectionId: 'c', sessionId: 's', contextRevision: 1 }
  // @ts-expect-error a draft location requires its draftId
  const bad: ChatLocation = { kind: 'draft', contextRevision: 1 }
  void location; void bad
}
declare const key: ChatComponentKey<BodyProps>
void key
