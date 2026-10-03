// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/stub-chat-contract.ts, verbatim)
/**
 * LOCAL TRANSCRIPTION of the reviewed ChatContributionsToken contract from
 * the unmerged `feature/desktop-workbench-registration` lineage
 * (packages/desktop-platform/contracts/seam/src/chat.ts). main does not carry
 * that contract yet; this stub exists so the contribution's consumer logic is
 * testable in this lane. The real wiring swaps this import for the merged
 * contract - integration dependency #3 (specs/002-model-provider/plan.md §6).
 * The shape is copied verbatim; semantics (duplicate id fails, closed-scope
 * add fails) are pinned by tests in this package.
 */
import { Token, type ResourceScope, type IDisposable } from '@ordessa/extension-api'
import type { ComponentType } from 'react'

export type DraftTarget = { serverInstanceId: string; harnessId: string; projectId: string }
export type ComposerLocation =
  | { kind: 'draft'; target?: DraftTarget }
  | { kind: 'session'; session: { serverInstanceId: string; harnessId: string; acpSessionId: string } }
export type ChatContribution = { id: string; order?: number } & (
  | { slot: 'composer.footer'; component: ComponentType<{ location: ComposerLocation }> }
  | { slot: 'conversation.floating'; component: ComponentType<{ session: unknown }> }
  | { slot: 'chat.settings'; component: ComponentType }
)
export interface ChatContributions {
  forScope(scope: ResourceScope): { add(contribution: ChatContribution): IDisposable }
}
export const ChatContributionsToken = new Token<ChatContributions>('ordessa.chat.contributions.v1')

/** The stub's registry, so tests (and only tests) can play Chat's side. */
export function createChatContributionsStub() {
  const byScope = new Map<ResourceScope, Map<string, ChatContribution>>()
  const closed = new Set<ResourceScope>()
  const stub: ChatContributions = {
    forScope(scope: ResourceScope) {
      return {
        add(contribution: ChatContribution): IDisposable {
          if (closed.has(scope)) throw new Error('cannot add into a closed scope')
          let registry = byScope.get(scope)
          if (registry === undefined) { registry = new Map(); byScope.set(scope, registry) }
          if (registry.has(contribution.id)) {
            throw new Error(`duplicate chat contribution id: ${contribution.id}`)
          }
          registry.set(contribution.id, contribution)
          return { isDisposed: false, dispose() { registry!.delete(contribution.id) } }
        },
      }
    },
  }
  return {
    token: ChatContributionsToken,
    stub,
    contributions: (scope: ResourceScope) => [...(byScope.get(scope)?.values() ?? [])],
    close: (scope: ResourceScope) => closed.add(scope),
  }
}
