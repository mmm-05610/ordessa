import { createDurableSubmissionClient, type DurableSubmissionAnswer } from './durable-submission'
import type { FrontendSubmissionJournal, FrontendSubmissionKey, FrontendSubmissionRecord, FrontendSubmissionStorageScope } from './frontend-submission-journal'
import type { WireCall } from './owner-port'

export type SubmissionRecoveryListing =
  | { readonly status: 'available'; readonly records: readonly FrontendSubmissionRecord[] }
  | { readonly status: 'unavailable'; readonly reason: string }

/** Cold recovery reads only the current backend-authorized journal scope. It
 * never resolves a new native binding, scans another realm or dispatches input. */
export function createSubmissionRecoveryClient(options: { wire: WireCall; journal: FrontendSubmissionJournal }) {
  const durable = createDurableSubmissionClient(options)
  async function authorizedScope(): Promise<FrontendSubmissionStorageScope> {
    const answer = await options.wire('agent.submission.scope', {})
    if (answer.kind !== 'Accepted') throw new Error(answer.reason)
    const { namespace, principalScope } = answer.result
    if (typeof namespace !== 'string' || !namespace.trim() || namespace.trim() !== namespace
        || typeof principalScope !== 'string' || !principalScope.trim() || principalScope.trim() !== principalScope
        || [namespace, principalScope].some(value => value.includes('\u0000') || value.includes('\\u0000'))) {
      throw new Error('Authorized submission scope is unavailable')
    }
    return Object.freeze({ namespace, principalScope })
  }
  return {
    async list(): Promise<SubmissionRecoveryListing> {
      try {
        const scope = await authorizedScope()
        const records = await options.journal.list(scope)
        return Object.freeze({ status: 'available', records: Object.freeze([...records]) })
      } catch (cause) {
        return { status: 'unavailable', reason: cause instanceof Error ? cause.message : String(cause) }
      }
    },
    async reconcile(input: FrontendSubmissionKey): Promise<DurableSubmissionAnswer> {
      const key = Object.freeze({ namespace: input.namespace, principalScope: input.principalScope, requestId: input.requestId })
      try {
        const scope = await authorizedScope()
        if (key.namespace !== scope.namespace || key.principalScope !== scope.principalScope) {
          return { status: 'unavailable', reason: 'Original request is outside the currently authorized scope' }
        }
        return durable.reconcile(key)
      } catch (cause) {
        return { status: 'unavailable', reason: cause instanceof Error ? cause.message : String(cause) }
      }
    },
  }
}
