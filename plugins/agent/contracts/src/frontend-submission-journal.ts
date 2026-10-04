/** Agent-owned durable record of a frontend submission attempt.
 * This journal records submission identity and evidence only; it is not a
 * configuration authority, draft store, or general UI persistence service. */

export interface FrontendSubmissionKey {
  readonly namespace: string
  readonly principalScope: string
  readonly requestId: string
}

export interface FrontendSubmissionCapture {
  readonly key: FrontendSubmissionKey
  /** Canonical target resolved by the Agent owner; callers must not derive it from UI selection. */
  readonly target: string
  readonly guarantee: 'reliable'
  readonly generation: string | number
  /** Exact native binding evidence captured for this submission, when available. */
  readonly binding?: Readonly<Record<string, unknown>>
  /** These values participate in same-key comparison when supplied. Production callers provide them. */
  readonly inputSchema?: string
  readonly submissionMode?: 'existing' | 'createWithConfig'
  readonly draft: {
    readonly draftId: string
    readonly draftRevision: number
    readonly text: string
    /** UI item identities are retained for recovery; only immutable refs are sent to Agent. */
    readonly attachmentIds?: readonly string[]
    readonly attachmentRefs: readonly string[]
  }
  readonly configOperationIds: readonly string[]
}

export interface FrontendSubmissionResultObservation {
  readonly outcome: 'accepted' | 'known-rejected' | 'unknown'
  readonly facts?: unknown
  readonly observedAt?: string
}

export interface FrontendSubmissionRecord extends FrontendSubmissionCapture {
  readonly state: 'captured' | 'possibly-submitted' | 'result-recorded'
  readonly results: readonly FrontendSubmissionResultObservation[]
}

export interface FrontendSubmissionStorageScope {
  readonly namespace: string
  readonly principalScope: string
}

export interface FrontendSubmissionTransactionOptions {
  /** Opaque, collision-free encoding of namespace + principal + requestId. */
  readonly key: string
  readonly mode: 'readonly' | 'readwrite'
  /** Writes must request durable commit semantics. */
  readonly durability: 'strict'
}

export interface FrontendSubmissionTransactionResult<T> {
  readonly value: T
  /** Omitted means no write. The storage port commits this atomically with the read. */
  readonly record?: FrontendSubmissionRecord
}

/**
 * An atomic single-key transaction port. Implementations must serialize
 * read-modify-write transactions for a key across all live clients, and resolve
 * only after a successful transaction commit. IndexedDB is the default.
 */
export interface FrontendSubmissionJournalStoragePort {
  transact<T>(
    options: FrontendSubmissionTransactionOptions,
    operation: (current: FrontendSubmissionRecord | undefined) => FrontendSubmissionTransactionResult<T>,
  ): Promise<T>
  list(scope: FrontendSubmissionStorageScope): Promise<readonly FrontendSubmissionRecord[]>
  close(): void | Promise<void>
}

export interface FrontendSubmissionJournalOptions {
  /** Inject a host-provided durable journal port. No in-memory fallback is used. */
  readonly storage?: FrontendSubmissionJournalStoragePort
  readonly indexedDB?: IDBFactory
  readonly databaseName?: string
}

export type FrontendSubmissionCaptureResult =
  | { readonly status: 'created' | 'existing'; readonly record: FrontendSubmissionRecord }
  | { readonly status: 'conflict'; readonly record: FrontendSubmissionRecord }

export type FrontendSubmissionClaimResult =
  | { readonly status: 'dispatch-authorized'; readonly record: FrontendSubmissionRecord }
  | { readonly status: 'already-possibly-submitted' | 'result-recorded' | 'missing'; readonly record?: FrontendSubmissionRecord }

export type FrontendSubmissionResultWrite =
  | { readonly status: 'recorded'; readonly record: FrontendSubmissionRecord }
  | { readonly status: 'missing' | 'not-dispatched'; readonly record?: FrontendSubmissionRecord }

export interface FrontendSubmissionJournal {
  capture(capture: FrontendSubmissionCapture): Promise<FrontendSubmissionCaptureResult>
  /** Grants one dispatch claim only after the possibly-submitted marker commits. */
  markPossiblySubmitted(key: FrontendSubmissionKey): Promise<FrontendSubmissionClaimResult>
  /** Appends observed outcome facts; unknown remains query-only and never grants a new dispatch. */
  recordResult(key: FrontendSubmissionKey, result: FrontendSubmissionResultObservation): Promise<FrontendSubmissionResultWrite>
  get(key: FrontendSubmissionKey): Promise<FrontendSubmissionRecord | undefined>
  list(scope: FrontendSubmissionStorageScope): Promise<readonly FrontendSubmissionRecord[]>
  /** Closes this view/connection without deleting or expiring journal records. */
  dispose(): Promise<void>
}

export class FrontendSubmissionJournalUnavailableError extends Error {
  readonly code = 'FRONTEND_SUBMISSION_JOURNAL_UNAVAILABLE'
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'FrontendSubmissionJournalUnavailableError'
  }
}

export class FrontendSubmissionJournalCommitError extends Error {
  readonly code = 'FRONTEND_SUBMISSION_JOURNAL_COMMIT_FAILED'
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'FrontendSubmissionJournalCommitError'
  }
}

export class FrontendSubmissionGuaranteeUnsupportedError extends Error {
  readonly code = 'FRONTEND_SUBMISSION_GUARANTEE_UNSUPPORTED'
  constructor(message: string) {
    super(message)
    this.name = 'FrontendSubmissionGuaranteeUnsupportedError'
  }
}

const DEFAULT_DATABASE_NAME = 'ordessa.agent.frontend-submission-journal.v1'
const OBJECT_STORE = 'submissions'
const INVALID = Symbol('invalid-json-value')

function logicalKey(key: FrontendSubmissionKey): string {
  return `${key.namespace}\u0000${key.principalScope}\u0000${key.requestId}`
}

function requireNonEmpty(value: unknown, field: string): asserts value is string {
  if (typeof value !== 'string' || value.length === 0 || value.trim() !== value) {
    throw new TypeError(`Invalid frontend submission ${field}`)
  }
  if (value.includes('\u0000') || value.includes('\\u0000')) {
    throw new TypeError(`Frontend submission ${field} contains a reserved key separator`)
  }
}

function freezeJson(value: unknown, ancestors = new WeakSet<object>()): unknown | typeof INVALID {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value
  if (typeof value === 'number') return Number.isFinite(value) ? value : INVALID
  if (typeof value !== 'object' || ancestors.has(value)) return INVALID
  ancestors.add(value)
  try {
    if (Array.isArray(value)) {
      const copy: unknown[] = []
      for (let index = 0; index < value.length; index += 1) {
        if (!(index in value)) return INVALID
        const item = freezeJson(value[index], ancestors)
        if (item === INVALID) return INVALID
        copy.push(item)
      }
      return Object.freeze(copy)
    }
    const prototype = Object.getPrototypeOf(value)
    if (prototype !== Object.prototype && prototype !== null) return INVALID
    const copy: Record<string, unknown> = Object.create(null)
    for (const key of Object.keys(value)) {
      const item = freezeJson((value as Record<string, unknown>)[key], ancestors)
      if (item === INVALID) return INVALID
      copy[key] = item
    }
    return Object.freeze(copy)
  } finally {
    ancestors.delete(value)
  }
}

function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  const record = value as Record<string, unknown>
  return `{${Object.keys(record).sort().map(key => `${JSON.stringify(key)}:${canonical(record[key])}`).join(',')}}`
}

function freezeCapture(input: FrontendSubmissionCapture, compareUnsupportedGuarantee = false): FrontendSubmissionCapture {
  requireNonEmpty(input?.key?.namespace, 'namespace')
  requireNonEmpty(input.key.principalScope, 'principal scope')
  requireNonEmpty(input.key.requestId, 'request ID')
  requireNonEmpty(input.target, 'canonical target')
  if (input.guarantee !== 'reliable' && !compareUnsupportedGuarantee) {
    throw new TypeError('Frontend submission journal accepts reliable submissions only')
  }
  if (!(typeof input.generation === 'string' && input.generation.length > 0)
    && !(typeof input.generation === 'number' && Number.isSafeInteger(input.generation) && input.generation >= 0)) {
    throw new TypeError('Invalid frontend submission generation')
  }
  const draft = input.draft
  requireNonEmpty(draft?.draftId, 'draft ID')
  if (!Number.isSafeInteger(draft.draftRevision) || draft.draftRevision < 0 || typeof draft.text !== 'string') {
    throw new TypeError('Invalid frontend submission draft capture')
  }
  if (!Array.isArray(draft.attachmentRefs) || !draft.attachmentRefs.every(value => typeof value === 'string' && value.length > 0)) {
    throw new TypeError('Invalid immutable attachment references')
  }
  if (draft.attachmentIds !== undefined && (!Array.isArray(draft.attachmentIds)
    || !draft.attachmentIds.every(value => typeof value === 'string' && value.length > 0)
    || draft.attachmentIds.length !== draft.attachmentRefs.length)) {
    throw new TypeError('Captured attachment identities and immutable references must correspond one-to-one')
  }
  if (!Array.isArray(input.configOperationIds)
    || !input.configOperationIds.every(value => typeof value === 'string' && value.length > 0)
    || new Set(input.configOperationIds).size !== input.configOperationIds.length) {
    throw new TypeError('Invalid configuration operation IDs')
  }
  if (input.inputSchema !== undefined) requireNonEmpty(input.inputSchema, 'input schema')
  if (input.submissionMode !== undefined && input.submissionMode !== 'existing' && input.submissionMode !== 'createWithConfig') {
    throw new TypeError('Invalid submission mode')
  }

  const binding = input.binding === undefined ? undefined : freezeJson(input.binding)
  if (binding === INVALID) throw new TypeError('Submission binding must be immutable JSON data')
  return Object.freeze({
    key: Object.freeze({ ...input.key }),
    target: input.target,
    guarantee: input.guarantee,
    generation: input.generation,
    ...(binding === undefined ? {} : { binding: binding as Readonly<Record<string, unknown>> }),
    ...(input.inputSchema === undefined ? {} : { inputSchema: input.inputSchema }),
    ...(input.submissionMode === undefined ? {} : { submissionMode: input.submissionMode }),
    draft: Object.freeze({
      draftId: draft.draftId,
      draftRevision: draft.draftRevision,
      text: draft.text,
      ...(draft.attachmentIds === undefined ? {} : { attachmentIds: Object.freeze([...draft.attachmentIds]) }),
      attachmentRefs: Object.freeze([...draft.attachmentRefs]),
    }),
    configOperationIds: Object.freeze([...input.configOperationIds]),
  })
}

function immutableRecord(record: FrontendSubmissionRecord): FrontendSubmissionRecord {
  const capture = freezeCapture(record)
  const results = record.results.map(result => {
    if (!['accepted', 'known-rejected', 'unknown'].includes(result.outcome)) throw new TypeError('Invalid submission result outcome')
    const facts = result.facts === undefined ? undefined : freezeJson(result.facts)
    if (facts === INVALID) throw new TypeError('Submission result facts must be immutable JSON data')
    if (result.observedAt !== undefined && typeof result.observedAt !== 'string') throw new TypeError('Invalid observation time')
    return Object.freeze({ outcome: result.outcome, ...(facts === undefined ? {} : { facts }),
      ...(result.observedAt === undefined ? {} : { observedAt: result.observedAt }) })
  })
  if (!['captured', 'possibly-submitted', 'result-recorded'].includes(record.state)) throw new TypeError('Invalid journal state')
  return Object.freeze({ ...capture, state: record.state, results: Object.freeze(results) })
}

function sameCapture(left: FrontendSubmissionCapture, right: FrontendSubmissionCapture): boolean {
  return canonical(freezeCapture(left, true)) === canonical(freezeCapture(right, true))
}

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message
  return typeof error === 'string' ? error : String(error)
}

function commitError(message: string, cause: unknown): FrontendSubmissionJournalCommitError {
  const causeText = errorText(cause)
  const fullMessage = causeText && !message.includes(causeText) ? `${message}: ${causeText}` : message
  if (cause instanceof FrontendSubmissionJournalCommitError && cause.message.includes(causeText)) return cause
  return new FrontendSubmissionJournalCommitError(fullMessage, { cause })
}

function assertActive(active: boolean): void {
  if (!active) throw new FrontendSubmissionJournalUnavailableError('Frontend submission journal is disposed')
}

function createIndexedDbStorage(indexedDBFactory: IDBFactory, databaseName: string): FrontendSubmissionJournalStoragePort {
  let databasePromise: Promise<IDBDatabase> | undefined
  let closed = false
  const openDatabase = () => {
    if (closed) return Promise.reject(new FrontendSubmissionJournalUnavailableError('Frontend submission journal is disposed'))
    databasePromise ??= new Promise<IDBDatabase>((resolve, reject) => {
      let request: IDBOpenDBRequest
      try { request = indexedDBFactory.open(databaseName, 1) }
      catch (error) { reject(new FrontendSubmissionJournalUnavailableError('IndexedDB could not be opened', { cause: error })); return }
      request.onupgradeneeded = () => {
        const db = request.result
        if (!db.objectStoreNames.contains(OBJECT_STORE)) db.createObjectStore(OBJECT_STORE, { keyPath: 'storageKey' })
      }
      request.onerror = () => reject(new FrontendSubmissionJournalUnavailableError('IndexedDB could not be opened', { cause: request.error ?? undefined }))
      request.onblocked = () => reject(new FrontendSubmissionJournalUnavailableError('IndexedDB journal upgrade is blocked'))
      request.onsuccess = () => {
        if (closed) { request.result.close(); reject(new FrontendSubmissionJournalUnavailableError('Frontend submission journal is disposed')); return }
        request.result.onversionchange = () => request.result.close()
        resolve(request.result)
      }
    })
    return databasePromise
  }

  return {
    async transact<T>(options: FrontendSubmissionTransactionOptions, operation: (current: FrontendSubmissionRecord | undefined) => FrontendSubmissionTransactionResult<T>) {
      if (closed) throw new FrontendSubmissionJournalUnavailableError('Frontend submission journal is disposed')
      const db = await openDatabase()
      let transaction: IDBTransaction
      try {
        transaction = options.mode === 'readwrite'
          ? db.transaction(OBJECT_STORE, 'readwrite', { durability: options.durability })
          : db.transaction(OBJECT_STORE, 'readonly')
      } catch (error) {
        throw new FrontendSubmissionJournalUnavailableError('IndexedDB does not support the required journal transaction', { cause: error })
      }
      return new Promise<T>((resolve, reject) => {
        let value!: T
        let operationError: unknown
        let request: IDBRequest
        try { request = transaction.objectStore(OBJECT_STORE).get(options.key) }
        catch (error) { transaction.abort(); reject(new FrontendSubmissionJournalCommitError('Journal transaction could not read its record', { cause: error })); return }
        request.onsuccess = () => {
          try {
            const current = request.result as FrontendSubmissionRecord | undefined
            const result = operation(current ? immutableRecord(current) : undefined)
            value = result.value
            if (options.mode === 'readwrite' && result.record) {
              const record = immutableRecord(result.record)
              transaction.objectStore(OBJECT_STORE).put({ ...record, storageKey: options.key })
            }
          } catch (error) {
            operationError = error
            try { transaction.abort() } catch { /* already inactive */ }
          }
        }
        request.onerror = () => {
          operationError = request.error ?? new Error('IndexedDB read failed')
          try { transaction.abort() } catch { /* already inactive */ }
        }
        transaction.oncomplete = () => resolve(value)
        transaction.onabort = () => reject(new FrontendSubmissionJournalCommitError('Journal transaction did not commit', {
          cause: operationError ?? transaction.error ?? undefined,
        }))
        transaction.onerror = () => { /* onabort carries the final transaction outcome */ }
      })
    },
    async list(scope) {
      if (closed) throw new FrontendSubmissionJournalUnavailableError('Frontend submission journal is disposed')
      const db = await openDatabase()
      let transaction: IDBTransaction
      try { transaction = db.transaction(OBJECT_STORE, 'readonly') }
      catch (error) { throw new FrontendSubmissionJournalUnavailableError('IndexedDB journal read is unavailable', { cause: error }) }
      return new Promise<readonly FrontendSubmissionRecord[]>((resolve, reject) => {
        let records: FrontendSubmissionRecord[] = []
        const request = transaction.objectStore(OBJECT_STORE).getAll()
        request.onsuccess = () => {
          try {
            records = (request.result as Array<FrontendSubmissionRecord & { storageKey: string }>)
              .filter(record => record.key.namespace === scope.namespace && record.key.principalScope === scope.principalScope)
              .map(record => immutableRecord(record))
          } catch (error) {
            try { transaction.abort() } catch { /* already inactive */ }
            reject(error)
          }
        }
        request.onerror = () => { try { transaction.abort() } catch { /* already inactive */ } }
        transaction.oncomplete = () => resolve(Object.freeze(records))
        transaction.onabort = () => reject(new FrontendSubmissionJournalCommitError('Journal list transaction did not complete', {
          cause: transaction.error ?? undefined,
        }))
      })
    },
    close() {
      if (closed) return
      closed = true
      void databasePromise?.then(db => db.close(), () => undefined)
    },
  }
}

export function createFrontendSubmissionJournal(options: FrontendSubmissionJournalOptions = {}): FrontendSubmissionJournal {
  let storage: FrontendSubmissionJournalStoragePort
  if (options.storage) storage = options.storage
  else {
    const factory = options.indexedDB ?? globalThis.indexedDB
    if (!factory) throw new FrontendSubmissionJournalUnavailableError('IndexedDB is unavailable; reliable submission is disabled')
    storage = createIndexedDbStorage(factory, options.databaseName ?? DEFAULT_DATABASE_NAME)
  }
  let active = true

  const transact = <T>(key: FrontendSubmissionKey, mode: 'readonly' | 'readwrite', operation: (record: FrontendSubmissionRecord | undefined) => FrontendSubmissionTransactionResult<T>) => {
    assertActive(active)
    return storage.transact({ key: logicalKey(key), mode, durability: 'strict' }, current => operation(current))
  }

  return {
    async capture(input) {
      // Validate and copy all comparison fields first, but let a same-key raw
      // attempt compare as a conflict instead of throwing before key lookup.
      const captured = freezeCapture(input, true)
      return transact(captured.key, 'readwrite', current => {
        if (current) {
          const existing = immutableRecord(current)
          return { value: { status: sameCapture(existing, captured) ? 'existing' : 'conflict', record: existing } as FrontendSubmissionCaptureResult }
        }
        if (captured.guarantee !== 'reliable') {
          throw new FrontendSubmissionGuaranteeUnsupportedError('Frontend submission journal accepts reliable submissions only')
        }
        const record = immutableRecord({ ...captured, state: 'captured', results: [] })
        return { value: { status: 'created', record } as FrontendSubmissionCaptureResult, record }
      }).catch(error => {
        if (error instanceof FrontendSubmissionJournalUnavailableError || error instanceof FrontendSubmissionGuaranteeUnsupportedError) throw error
        throw commitError('Could not durably capture frontend submission mapping', error)
      })
    },
    async markPossiblySubmitted(key) {
      const keyCopy = freezeKey(key)
      return transact(keyCopy, 'readwrite', current => {
        if (!current) return { value: { status: 'missing' } as FrontendSubmissionClaimResult }
        const record = immutableRecord(current)
        if (record.state === 'result-recorded') return { value: { status: 'result-recorded', record } as FrontendSubmissionClaimResult }
        if (record.state === 'possibly-submitted') return { value: { status: 'already-possibly-submitted', record } as FrontendSubmissionClaimResult }
        const claimed = immutableRecord({ ...record, state: 'possibly-submitted' })
        return { value: { status: 'dispatch-authorized', record: claimed } as FrontendSubmissionClaimResult, record: claimed }
      }).catch(error => {
        if (error instanceof FrontendSubmissionJournalUnavailableError) throw error
        throw commitError('Could not durably write possibly-submitted marker', error)
      })
    },
    async recordResult(key, result) {
      const keyCopy = freezeKey(key)
      const observation = freezeResult(result)
      return transact(keyCopy, 'readwrite', current => {
        if (!current) return { value: { status: 'missing' } as FrontendSubmissionResultWrite }
        const record = immutableRecord(current)
        if (record.state === 'captured') return { value: { status: 'not-dispatched', record } as FrontendSubmissionResultWrite }
        const results = Object.freeze([...record.results, observation])
        const state = observation.outcome === 'unknown' ? 'possibly-submitted' : 'result-recorded'
        const updated = immutableRecord({ ...record, state, results })
        return { value: { status: 'recorded', record: updated } as FrontendSubmissionResultWrite, record: updated }
      }).catch(error => {
        if (error instanceof FrontendSubmissionJournalUnavailableError) throw error
        throw commitError('Could not durably record submission observation', error)
      })
    },
    async get(key) {
      const keyCopy = freezeKey(key)
      return transact(keyCopy, 'readonly', current => ({ value: current ? immutableRecord(current) : undefined }))
    },
    async list(scope) {
      assertActive(active)
      const namespace = scope.namespace
      const principalScope = scope.principalScope
      requireNonEmpty(namespace, 'namespace')
      requireNonEmpty(principalScope, 'principal scope')
      const values = await storage.list({ namespace, principalScope })
      return Object.freeze(values.map(immutableRecord))
    },
    async dispose() {
      if (!active) return
      active = false
      await storage.close()
    },
  }
}

function freezeKey(key: FrontendSubmissionKey): FrontendSubmissionKey {
  requireNonEmpty(key?.namespace, 'namespace')
  requireNonEmpty(key.principalScope, 'principal scope')
  requireNonEmpty(key.requestId, 'request ID')
  return Object.freeze({ namespace: key.namespace, principalScope: key.principalScope, requestId: key.requestId })
}

function freezeResult(result: FrontendSubmissionResultObservation): FrontendSubmissionResultObservation {
  if (!result || !['accepted', 'known-rejected', 'unknown'].includes(result.outcome)) throw new TypeError('Invalid submission result outcome')
  const facts = result.facts === undefined ? undefined : freezeJson(result.facts)
  if (facts === INVALID) throw new TypeError('Submission result facts must be immutable JSON data')
  if (result.observedAt !== undefined && typeof result.observedAt !== 'string') throw new TypeError('Invalid observation time')
  return Object.freeze({ outcome: result.outcome, ...(facts === undefined ? {} : { facts }),
    ...(result.observedAt === undefined ? {} : { observedAt: result.observedAt }) })
}
