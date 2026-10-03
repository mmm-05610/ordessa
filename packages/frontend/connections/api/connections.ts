// @ordessa/connections — protocol-neutral connection platform public API.
// Contract: specs/010-platform-core/contracts/connections-platform.md (C6) §3/§5.
// This file is side-effect free by design: types, the single ConnectionsToken
// construction site, and the only ConnectionKind factory. The implementation is
// provided by the built-in extension `ordessa.connections` via ConnectionsToken;
// an empty host (no extension enabled) can still import this API (CN-08 scope).
//
// Dependency wall (contract §2): this package must never depend on or import
// React, Workbench, Agent/AgentClient, ACP, Server, Harness, Profile or Pacthold,
// and must contain no run/approval/session/model/provider/release-remote branching.

import { Token, type IDisposable, type ResourceScope } from '@ordessa/extension-api'

/**
 * A connection domain value (whatever the connector produces: a client, a
 * socket wrapper, an in-memory fake, ...). The platform treats `T` as opaque.
 */
declare const connectionKindIdentity: unique symbol

/**
 * Runtime single-instance type reference for connector values.
 *
 * Identity is compared with `===` at open time, and the ONLY construction site
 * is {@link createConnectionKind} in this module. The branded phantom property
 * makes the nominal identity non-forgeable structurally: a generic cast
 * (`otherKind as unknown as ConnectionKind<T>`) still fails the runtime
 * identity check, and two kinds built with the same display name are distinct.
 * Concrete protocol kinds (ACP, Ordessa Server, ...) live in their owning
 * plugins' APIs — the platform never ships a protocol enum.
 */
export interface ConnectionKind<T> {
  readonly [connectionKindIdentity]: (value: T) => T
  /** Display-only label; never used for identity comparison. */
  readonly displayName: string
}

/** The single construction site of {@link ConnectionKind} (exported from the api subpath). */
export function createConnectionKind<T>(displayName: string): ConnectionKind<T> {
  return Object.freeze({ displayName }) as unknown as ConnectionKind<T>
}

/**
 * A connector is registered against the registrant's owner scope with a stable
 * id, a display title and a kind reference (contract §2/§3).
 * `open` must only perform the connection itself; local release happens exactly
 * once per endpoint through {@link ConnectionEndpoint.closeLocal} (contract §4:
 * one owner for the underlying close — connectors may delegate to native-bridge).
 * `signal` is platform-owned: it aborts when the caller aborts the open, the
 * caller scope closes, or the registrant unmounts (§5.2/§5.3).
 */
export interface Connector<T> {
  id: string
  title: string
  kind: ConnectionKind<T>
  open(signal: AbortSignal): Promise<ConnectionEndpoint<T>>
}

/**
 * Successful connector.open result. `closeLocal` releases the LOCAL connection
 * ownership only — it must never be claimed to settle backend executions
 * (contract §3: it must not be bound unaudited to e.g. AgentClient.dispose).
 * The platform calls it at most once per handle, including late-resolve cleanup
 * (CN-03/CN-06).
 */
export interface ConnectionEndpoint<T> {
  value: T
  closeLocal(): Promise<void>
}

/** Optional controls for {@link Connections.open}. `signal` cancels a not-yet-finished open (§2/§5). */
export interface ConnectionOpenOptions {
  signal?: AbortSignal
}

/** Neutral lifecycle state of one connection instance (no business semantics). */
export type ConnectionState = 'opening' | 'connected' | 'closing' | 'close_failed' | 'closed'

/** Safe, neutral per-instance snapshot: no tokens, payloads or transport internals. */
export interface ConnectionInstanceSnapshot {
  instanceId: string
  connectorId: string
  state: ConnectionState
  /** Sanitised one-line summary for diagnostics; never credentials or payloads. */
  error?: string
}

/** Neutral registration summary. `kindName` is display-only; identity is the kind object. */
export interface RegisteredConnectorSnapshot {
  id: string
  title: string
  kindName: string
}

/** Platform-wide snapshot view (contract §3): registrable connectors + live instances. */
export interface ConnectionsSnapshot {
  connectors: readonly RegisteredConnectorSnapshot[]
  /** Instances from `opening` until a terminal result; successfully closed instances are removed, while `close_failed` records stay visible for host diagnosis (§5.6). */
  instances: readonly ConnectionInstanceSnapshot[]
}

/** Result of an explicit {@link ConnectionHandle.close}. Failures are never dressed as closed (§5.4). */
export type CloseOutcome =
  | { status: 'closed' }
  | { status: 'close_failed'; error: string }

/**
 * Caller-held handle for one successful open (owned by the caller's scope —
 * §5.1/§5.2). Each open creates an independent instance; the platform never
 * pools or auto-selects by connector id (CN-04).
 */
export interface ConnectionHandle<T> {
  readonly instanceId: string
  readonly connectorId: string
  readonly value: T
  getSnapshot(): ConnectionInstanceSnapshot
  subscribe(listener: () => void): () => void
  /**
   * Concurrent/duplicate close calls coalesce into one pending `closeLocal`
   * (§5.4). A rejected closeLocal yields `close_failed` without marking the
   * handle closed; a later explicit close retries — never an auto loop.
   */
  close(): Promise<CloseOutcome>
}

/** One late-open cleanup recorded by settlement (§5.3/§5.5): the endpoint that resolved after invalidation and was closed exactly once. */
export interface LateOpenClosure {
  connectorId: string
  instanceId: string
  /** True once the late endpoint's `closeLocal` resolved; false if it failed. */
  closed: boolean
  error?: string
}

/** One failed local release recorded by settlement (§5.5). */
export interface CloseFailureRecord {
  connectorId: string
  instanceId: string
  error: string
}

/**
 * Awaitable settlement report for asynchronous cleanup started by synchronous
 * scope dispose (§5.5). Entries are cumulative since service creation. The
 * report is protocol-neutral and carries NO business pendingReleases.
 */
export interface ConnectionsSettlementReport {
  lateOpenClosures: readonly LateOpenClosure[]
  closeFailures: readonly CloseFailureRecord[]
}

/** Scope-bound registration surface returned by {@link Connections.forScope}. */
export interface ScopedConnectorRegistration {
  /**
   * Binds the connector to the registrant's owner scope: unmounting that scope
   * removes the registration and invalidates new opens (§5.2). Duplicate stable
   * ids are rejected at registration with a clear error (CN-02).
   */
  add<T>(connector: Connector<T>): IDisposable
}

/**
 * The protocol-neutral connections service. Resolved through
 * {@link ConnectionsToken} by the built-in extension `ordessa.connections`;
 * absent when the extension is not enabled — consumers must reject absence
 * rather than substitute a private registry (constitution: no service locator,
 * empty host valid).
 */
export interface Connections {
  forScope(owner: ResourceScope): ScopedConnectorRegistration
  /**
   * Checks registration, kind identity and BOTH scopes' liveness before
   * `connector.open` is ever called (CN-02, §5.1). Rejections are Errors. The
   * resulting handle is owned by `scope` (the caller scope).
   */
  open<T>(scope: ResourceScope, id: string, kind: ConnectionKind<T>, options?: ConnectionOpenOptions): Promise<ConnectionHandle<T>>
  getSnapshot(): ConnectionsSnapshot
  subscribe(listener: () => void): () => void
  /**
   * Resolves once every asynchronous cleanup started so far (late-open closures,
   * scope-dispose releases) has settled; pending rejections are recorded in the
   * report instead of being swallowed (§5.5). Resolves immediately when nothing
   * is pending.
   */
  whenSettled(): Promise<ConnectionsSettlementReport>
}

/** The single construction site of the Connections DI token in this repository. */
export const ConnectionsToken = new Token<Connections>('ordessa.connections.v1')
