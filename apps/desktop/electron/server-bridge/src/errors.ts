/**
 * C-02 §7 — the five launch failures, each with a reason, a remedy and a log
 * locator.
 *
 * The shape mirrors the Python side deliberately: same code, same two
 * human-readable halves, no token bytes and no full locator in any of them.
 * A host that renders `reason` next to a "copy diagnostics" button must not
 * be able to leak a secret through the error text, so the message is built
 * from basenames only.
 */

export type LaunchErrorCode =
  | 'PORT_ALLOCATION_FAILED'
  | 'SERVER_START_TIMEOUT'
  | 'SERVER_EXITED_EARLY'
  | 'BUNDLED_RUNTIME_MISSING'
  | 'SERVER_CRASHED'

export class LaunchError extends Error {
  readonly code: LaunchErrorCode
  /** What was observed, in a form a person can act on. */
  readonly reason: string
  /** The next step that a person (not a developer) can take. */
  readonly remedy: string
  /** Where the evidence is: a log path, or the fact that there is none. */
  readonly logRef: string | null
  /** The tail of the Server log, for a failure that happened off-handshake. */
  readonly logTail: string | null

  constructor(
    code: LaunchErrorCode,
    reason: string,
    remedy: string,
    options: { readonly logRef?: string | null; readonly logTail?: string | null } = {},
  ) {
    super(`${code}: ${reason}; ${remedy}`)
    this.name = 'LaunchError'
    this.code = code
    this.reason = reason
    this.remedy = remedy
    this.logRef = options.logRef ?? null
    this.logTail = options.logTail ?? null
  }
}

/** C-02 §7 case 1. Never retried against a different fixed port. */
export class PortAllocationFailed extends LaunchError {
  constructor(reason: string, remedy = 'free the loopback port and start again') {
    super('PORT_ALLOCATION_FAILED', reason, remedy)
    this.name = 'PortAllocationFailed'
  }
}

/** C-02 §4: the readiness probe did not answer in time. */
export class ServerStartTimeout extends LaunchError {
  constructor(
    readonly waitedMs: number,
    options: { readonly logRef?: string | null; readonly logTail?: string | null } = {},
  ) {
    super(
      'SERVER_START_TIMEOUT',
      `the Server did not become ready within ${String(waitedMs)} ms`,
      'open the logs for the reason, then start again',
      options,
    )
    this.name = 'ServerStartTimeout'
  }
}

/** C-02 §7 case 3: the child died before it was ever ready. */
export class ServerExitedEarly extends LaunchError {
  constructor(
    readonly exitCode: number | null,
    readonly signal: string | null,
    options: { readonly logRef?: string | null; readonly logTail?: string | null } = {},
  ) {
    const how =
      signal !== null
        ? `on signal ${signal}`
        : `with exit code ${exitCode === null ? 'unknown' : String(exitCode)}`
    super(
      'SERVER_EXITED_EARLY',
      `the Server process exited before it was ready, ${how}`,
      'open the Server log for the failure, then start again',
      options,
    )
    this.name = 'ServerExitedEarly'
  }
}

/**
 * C-02 §6: the bundled runtime is incomplete. This is refused EARLY, before
 * a half-usable state exists — a host that started the Server and then
 * discovered the ACP bridge was missing has already put the user in a state
 * the contract forbids.
 */
export class BundledRuntimeMissing extends LaunchError {
  constructor(readonly missing: readonly string[]) {
    super(
      'BUNDLED_RUNTIME_MISSING',
      `the bundled runtime is incomplete: ${missing.join(', ')}`,
      'reinstall the application; the bundled runtime is part of the package',
    )
    this.name = 'BundledRuntimeMissing'
  }
}

/** C-02 §7 case 5: a Server that was ready and then died. */
export class ServerCrashed extends LaunchError {
  constructor(
    readonly exitCode: number | null,
    readonly signal: string | null,
    options: { readonly logRef?: string | null; readonly logTail?: string | null } = {},
  ) {
    super(
      'SERVER_CRASHED',
      `the Server stopped unexpectedly (${signal ?? `exit code ${String(exitCode)}`})`,
      'open the Server log for the failure, then restart the application',
      options,
    )
    this.name = 'ServerCrashed'
  }
}

/**
 * C-02 §3.1: the handshake line was not one. Distinct from a timeout on
 * purpose — "the Server said something incomprehensible" and "the Server said
 * nothing" lead the reader to different places.
 */
export class ServerHandshakeMalformed extends LaunchError {
  constructor(readonly line: string) {
    super(
      'SERVER_EXITED_EARLY',
      'the Server wrote a handshake line that is not one',
      'open the Server log; the startup handshake is not a supported format',
      { logTail: line.slice(0, 200) },
    )
    this.name = 'ServerHandshakeMalformed'
  }
}
