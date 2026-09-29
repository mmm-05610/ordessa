// Type-level counterexamples for the T11 Chat-face deliverable (Z2 convention:
// type counterexamples are deliverables, checked by `tsc --noEmit` here and by
// the desktop-wide typecheck once the build covers this package; never
// bundled, never runtime-loaded). Every @ts-expect-error below must actually
// fire — a relaxed type silently fails this file.
import type {
  ChatActionResult, ChatComponentKey, ChatInputEntry, ChatInputEntryAction, ChatInputSource,
  ChatLocation, ChatScopedAction,
} from '@extensions/ordessa.chat-api/contract.js'
// Type-only reach to the platform component-key type. This package's tsconfig
// does not map the published specifier `@ordessa/ui-components/api` yet (chat-api
// r3 integration item — see the negative below), and a type-only import from the
// platform's public api surface is the only way this file can still see the
// brand it is supposed to fail against. Nothing here is bundled or loaded.
import type { UiComponentKey } from '../../../../../packages/desktop-platform/ui-components/api/ui-components'
import type { DefinitionState, EffectiveDefinition, InvokeGateway } from './subagent-definitions'
import type { SubagentInputSourceDeps } from './subagent-input-source'
import { createSubagentInputSource, describeDefinition } from './subagent-input-source'
import type { SubagentDefinitionReader } from './subagent-definitions'

declare const reader: SubagentDefinitionReader
declare const gateway: InvokeGateway

// --- positives: the shapes the deliverable promises are usable as written ----
const deps: SubagentInputSourceDeps = {
  gateway: null, // explicit "no invocation owner wired yet" is a legal, honest state
  existingNames: { async names() { return [] } },
  isLocationCurrent: () => true,
}
const source: ChatInputSource = createSubagentInputSource(reader, deps)
void source
const withGateway: SubagentInputSourceDeps = { ...deps, gateway }
void createSubagentInputSource(reader, withGateway)
declare const someDefinition: EffectiveDefinition
const detail = describeDefinition(someDefinition)
void (detail satisfies { readonly usableFromChat: boolean; readonly state: DefinitionState })
// r3 positive: what a ready entry now builds — an execute that consumes the
// selection-time ChatLocation, revalidates it and forwards exactly that value.
// This is the composition the source relies on; if the contract's action shape
// drifts again, this line is the first to notice.
const readyAction: ChatInputEntryAction = {
  kind: 'invoke',
  execute: async (location: ChatLocation): Promise<ChatActionResult> =>
    deps.isLocationCurrent(location)
      ? gateway.invoke({ location, definition: someDefinition })
      : { status: 'unavailable' },
}
void readyAction
// r3 positive: `ChatComponentKey` is the platform key type itself, so a chat key
// satisfies every C7-typed consumer and back (contract.ts:24-27).
declare const chatKey: ChatComponentKey<{ readonly x: string }>
const asPlatformKey: UiComponentKey<{ readonly x: string }> = chatKey
const asChatKey: ChatComponentKey<{ readonly x: string }> = asPlatformKey
void asChatKey

// --- negatives: every relaxation below must be a compile error ---------------
{
  // @ts-expect-error the gateway is required explicitly; there is no silent default that pretends an invoke could execute
  const missingGateway: SubagentInputSourceDeps = {
    existingNames: { async names() { return [] } },
    isLocationCurrent: () => true,
  }
  void missingGateway
}
{
  // @ts-expect-error the four facts are separate members; omitting `invokable` is rejected, never implied
  const missingFact: DefinitionState = { projected: 'yes', loaded: 'unknown', used: 'unknown' }
  void missingFact
}
{
  // @ts-expect-error absence of observation is `unknown`, its own state; a boolean would collapse it into `no`
  const collapsed: DefinitionState = { projected: true, loaded: 'unknown', invokable: 'unknown', used: 'unknown' }
  void collapsed
}
{
  interface MyBody { readonly x: string }
  // chat-api r3 makes `ChatComponentKey<P>` the platform's branded
  // `UiComponentKey<P>` (contract.ts:27), so the forgery gate is now the
  // platform's. The negative is written against the platform type because this
  // package's tsconfig has no `@ordessa/ui-components/api` path mapping yet
  // (chat-api r3 integration item; chat/api, chat/frontend,
  // plugins/permissions/frontend and apps/desktop all carry it) — through the
  // alias alone this project would see `any` and the directive would go
  // silently unused, which is exactly the failure mode this file exists to
  // prevent. In the desktop-wide project, where the specifier does resolve, the
  // alias positives above additionally show the two names are one type — so
  // forging an `ordessa.chat.*` key is as impossible as forging this one.
  // @ts-expect-error a hand-written object cannot satisfy the component-key brand, even with the right id and major
  const handKey: UiComponentKey<MyBody> = { id: 'ordessa.chat.message-body', major: 1 }
  void handKey
}
{
  // The r3 invoke action takes the selection-time location. A pre-r3
  // `ChatScopedAction<void>` — the shape this module used to build — is no
  // longer a legal action, so the stale-target argument cannot be "forgotten"
  // into a type that still passes.
  const voidScoped: ChatScopedAction<void> = async () => ({ status: 'unavailable' })
  // @ts-expect-error invoke.execute is not a void-scoped action: Chat dispatches it with the selection-time ChatLocation
  const staleShape: ChatInputEntryAction = { kind: 'invoke', execute: voidScoped }
  void staleShape
}
{
  // The selection-time location is not negotiable: an action that declares a
  // narrower parameter than ChatLocation is rejected, so a draft-only executor
  // cannot be offered to a session selection.
  const draftOnlyAction: ChatInputEntryAction = {
    kind: 'invoke',
    // @ts-expect-error an execute that only accepts a draft location is not a ChatInputEntryAction
    execute: async (location: ChatLocation & { kind: 'draft' }): Promise<ChatActionResult> =>
      ({ status: 'accepted' }),
  }
  void draftOnlyAction
}
{
  const reasonlessEntry: ChatInputEntry = {
    id: 'x', title: 'X', groupId: 'g', order: 1, surfaces: ['plus'],
    // @ts-expect-error a disabled availability must carry its reason
    availability: { kind: 'disabled' },
    action: { kind: 'invoke', execute: async () => ({ status: 'refused', message: 'detail only' }) },
  }
  void reasonlessEntry
}
{
  // @ts-expect-error ChatActionResult is exactly accepted | refused | unavailable; a fourth "pending" state would fake progress
  const bogusResult: ChatActionResult = { status: 'pending' }
  void bogusResult
}
{
  // @ts-expect-error refused must carry its message — a refusal without a concrete reason is the false-green this gate forbids
  const muteRefusal: ChatActionResult = { status: 'refused' }
  void muteRefusal
}
{
  // @ts-expect-error evidence states are the exact three-value union; 'maybe' is not one and never coerces
  const bogusState: DefinitionState = { projected: 'maybe', loaded: 'unknown', invokable: 'unknown', used: 'unknown' }
  void bogusState
}
