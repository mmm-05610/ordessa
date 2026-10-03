/**
 * F5 frozen public surface (R7/M14 `oe-f5/1`) — TYPES ONLY.
 *
 * This file is the incremental contract freeze of T008-11: the neutral
 * API shapes for state, selectors, projections, queries, tasks, editing,
 * UI storage, interactions and display. Implementations land in T008-12..20
 * against exactly these signatures. Platform provides mechanisms; domain
 * owners hold values — nothing here is a business store and no interface
 * exposes a generic `setState` to consumers (F5 §2).
 */

// -- state (§2) --------------------------------------------------------------

/** Identity-stable immutable snapshots; unmodified access returns the same object. */
export interface ReadonlyStateStore<S> {
  getSnapshot(): S
  subscribe(listener: () => void): ReleaseHandle
}

/** Owner-only write face. Never exposed through a consumer-facing API. */
export interface StateStoreOwner<S> extends ReadonlyStateStore<S> {
  update(recipe: (current: S) => S): void
  /** Batched publish: consumers see exactly one complete snapshot. */
  updateBatched(recipes: ReadonlyArray<(current: S) => S>): void
}

export interface ReleaseHandle {
  /** Idempotent; also invoked automatically when the caller's scope exits. */
  release(): void
}

export interface StateStoreFactory {
  create<S>(initial: S, options?: { equals?: (a: S, b: S) => boolean }): StateStoreOwner<S>
}

// -- selectors (§2) -----------------------------------------------------------

export interface Selector<T, V> {
  (snapshot: T): V
  equals?: (a: V, b: V) => boolean
}

export interface SelectionReader<T, V> {
  /** Reads from an already-authorized snapshot; equal results never notify. */
  select(snapshot: T): V
}

// -- projections (§3, reuses E3 observation semantics) -----------------------

/**
 * Authorized read-only projection. The TS side declares the seam; the
 * observation mechanics are the E3 `readAndSubscribe` contract owned by the
 * Environment (003/004). No second subscription broker is defined here —
 * `observe` is the single entry and gaps are explicit.
 */
export interface AuthorizedProjection<T> {
  observe(cursor: string | null, credits: number): ProjectionFrame<T>
  /** Permission revocation clears accessible snapshots; already-handed data is not retracted. */
  readonly authorization: { scope: string; generation: number }
}

export type ProjectionFrame<T> =
  | { kind: 'snapshot'; revision: string; value: T; cursor: string }
  | { kind: 'delta'; revision: string; patch: unknown; cursor: string }
  | { kind: 'resync-required'; reason: 'gap' | 'overflow' | 'reconnect' }
  | { kind: 'revoked' }

// -- queries (§3) -------------------------------------------------------------

export interface QueryKey {
  environment: string
  connectionGeneration: number
  authorizationScope: string
  authorizationGeneration: number
  serviceTarget: string
  contractVersion: string
  params: Readonly<Record<string, string | number | boolean>>
}

export interface QueryDeclaration<T> {
  key: QueryKey
  /** Must be an effect-free read; non-idempotent effects are refused. */
  run(signal: AbortSignal): Promise<T>
  /** Explicitly configured; off by default (F5 §8). */
  refreshPolicy?: { retry: boolean; refetchOnFocus: boolean; persist: boolean }
  pageSize?: number
}

export interface QueryCache {
  read<T>(decl: QueryDeclaration<T>): QueryEntry<T>
  invalidate(key: QueryKey): void
  refresh(key: QueryKey): Promise<void>
  /** Bounded cache with lifecycle cleanup; never a full history. */
  clearScope(scope: string): void
}

export interface QueryEntry<T> {
  state: 'idle' | 'loading' | 'success' | 'error' | 'stale'
  data: T | undefined
  freshness: 'fresh' | 'stale' | 'streaming' | 'listing'
  subscribe(listener: () => void): ReleaseHandle
}

// -- tasks (§4) ---------------------------------------------------------------

export interface TaskHandle<R> {
  readonly taskId: string
  readonly target: { activation: string; generation: number }
  readonly requestKey: string
  result(): Promise<TaskResult<R>>
  /** Cancels THIS waiter only — never claims the backend/native stopped. */
  cancelWait(): void
  onProgress(cb: (fraction: number | null) => void): ReleaseHandle
}

export type TaskResult<R> =
  | { kind: 'done'; value: R }
  | { kind: 'failed'; reason: string }
  | { kind: 'cancelled-wait' }
  | { kind: 'unknown'; queryHint: string }

export interface TaskScope {
  run<R>(target: { activation: string; generation: number }, body: (signal: AbortSignal) => Promise<R>): TaskHandle<R>
  /** A-request late results never overwrite B selections (generation check). */
  barrierLatest(): void
  releaseAll(): void
}

// -- editing (§5) -------------------------------------------------------------

export interface EditSession<V> {
  readonly editId: string
  readonly baseRevision: string
  readonly editRevision: number
  dirtyFields(): ReadonlySet<keyof V & string>
  setValue<K extends keyof V & string>(field: K, value: V[K]): void
  /** Commit captures the field mask + base/edit revisions; success clears only
   *  fields that are STILL unchanged since the capture (ABA safe). */
  commit(): Promise<EditOutcome>
  cancel(): void
  onConflict(cb: (info: { field: string; theirRevision: string }) => void): ReleaseHandle
}

export type EditOutcome =
  | { kind: 'saved'; consumedFields: ReadonlyArray<string> }
  | { kind: 'conflict'; field: string; theirRevision: string } // local values kept
  | { kind: 'rejected'; reason: string }
  | { kind: 'unknown'; queryHint: string } // never auto-retried

export interface SettingsContribution {
  id: string
  label: string
  defaultValueSource: 'domain-owner' | 'declared'
  editableScope: 'user' | 'workspace' | 'window'
  validate(value: unknown): string | null
  read(): Promise<unknown>
  submit(value: unknown): Promise<EditOutcome>
  /** Secret fields speak SecretRef only — never plaintext in generic stores. */
  sensitive?: boolean
}

// -- UI storage (§6) ----------------------------------------------------------

export interface UiStoreContract {
  readonly capability: 'available' | 'session-only' | 'unavailable'
  read<T>(ns: UiNamespace, key: string): Promise<T | undefined>
  /** Conditional write; unknown schema versions are refused, never overwritten. */
  write<T>(ns: UiNamespace, key: string, value: T, opts: { ifRevision?: string }): Promise<'written' | 'conflict'>
  remove(ns: UiNamespace, key: string): Promise<void>
  migrate(ns: UiNamespace, toSchemaVersion: number): Promise<'migrated' | 'refused'>
}

export interface UiNamespace {
  pluginNamespace: string
  workspace: string | null
  windowOrSharedPurpose: string
  schemaVersion: number
}

// -- interactions & display (§7) ---------------------------------------------

export interface NotificationHandle {
  readonly id: string
  update(text: string): void
  close(): void
}

export interface ProgressHandle {
  readonly id: string
  update(fraction: number | null, text?: string): void
  /** Cancel requests project the task's declared cancel; UI never claims "stopped". */
  requestCancel(): void
  close(): void
}

export interface InteractionService {
  notify(opts: { id?: string; severity: 'info' | 'warning' | 'error'; text: string }): NotificationHandle
  progress(opts: { id?: string; text: string; cancel?: () => void }): ProgressHandle
  quickPick<T>(opts: { title: string; items: ReadonlyArray<{ id: string; label: string; value: T }> }): Promise<{ kind: 'picked'; value: T } | { kind: 'cancelled' }>
  confirm(opts: { title: string; text: string }): Promise<'confirmed' | 'cancelled'>
}

export interface ContextKeyRegistry {
  /** Namespaced, scoped keys derived from focus/selection/authorized projections. */
  set(name: string, value: string | number | boolean | null): void
  evaluate(when: string): boolean
}
