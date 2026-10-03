/**
 * F5 token identities (R7/M14 `oe-f5/1`) — literal freeze.
 *
 * T008-11 freezes the identity LITERALS here (pure, no runtime import).
 * T008-12 constructs the single runtime Token objects at the carrier's one
 * construction point (same C7 discipline as WorkbenchToken: one file, one
 * construction, shared via `@extensions/ordessa.contracts/contract.js`).
 * A second construction point is the "Token 两份" counterexample.
 */

export const F5_TOKEN_IDS = {
  /** Owner-managed state stores; the factory never holds business values. */
  stateStores: 'ordessa.f5.state-stores.v1',
  /** Ordinary read cache (declarations only; no effectful queries). */
  queryCache: 'ordessa.f5.query-cache.v1',
  /** Injectable UI persistence (absent adapter => session-only). */
  uiStorage: 'ordessa.f5.ui-storage.v1',
  /** Notifications/progress/quick-pick/confirm presentation. */
  interactionService: 'ordessa.f5.interaction-service.v1',
} as const

export type F5TokenId = (typeof F5_TOKEN_IDS)[keyof typeof F5_TOKEN_IDS]

/** Contract version of this freeze; bumps only with a reviewed revision. */
export const F5_CONTRACT_VERSION = 'oe-f5/1'
