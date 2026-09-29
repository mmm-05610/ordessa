/**
 * C-02 §5 — the Server's process lifecycle, owned entirely by the party that
 * spawned it.
 *
 * The state machine is the contract's own: idle → spawning → probing → ready,
 * with `failed`, `stopping`, `stopped` and `crashed` reachable. Three
 * properties are enforced here rather than documented:
 *
 * 1. **The port is observed, never assumed.** The child writes one handshake
 *    line to the stdout this process owns; the origin comes from that line.
 *    There is no port scan, no "try 8732 and see", no temp-file guess.
 * 2. **Only our own child is ever signalled.** `stop()` targets the pid this
 *    object spawned, and the process group it was given (`detached: true`),
 *    so a Server that forked helpers takes them with it — and a process the
 *    host did not spawn is unreachable from here by construction.
 * 3. **A failure is never a fake success.** Every exit path throws a typed
 *    `LaunchError` carrying the exit code, the signal and the log tail. There
 *    is no branch that returns a "ready" instance whose probe never ran.
 */
import { spawn, type ChildProcessByStdio } from 'node:child_process'
import { existsSync, readFileSync, statSync } from 'node:fs'
import type { Readable } from 'node:stream'

import {
  assertNoSymlink,
  launchEnv,
  layout,
  resolveDataRoot,
  serverLogFileOf,
  tokenFileOf,
} from './data-root.js'
import {
  ServerCrashed,
  ServerExitedEarly,
  ServerHandshakeMalformed,
  ServerStartTimeout,
} from './errors.js'
import { resolveBundledRuntime, serverCommand } from './runtime.js'

/** The exact shape of the child this bridge spawns: no stdin, piped output. */
export type ServerChild = ChildProcessByStdio<null, Readable, Readable>

export type ServerState =
  | 'idle'
  | 'spawning'
  | 'probing'
  | 'ready'
  | 'failed'
  | 'stopping'
  | 'stopped'
  | 'crashed'

export interface ServerInstance {
  /** The bound loopback origin the Server reported. Changes every start. */
  readonly origin: string
  /** The persistent identity derived from the data root. Never changes. */
  readonly serverId: string
  /** The pid THIS host spawned. */
  readonly pid: number
  /** `origin|serverId` — the stable project-selection scope (C-02 §3.2). */
  readonly scope: string
  readonly startedAt: string
  readonly state: ServerState
}

export interface HandshakeLine {
  readonly event: string
  readonly origin: string
  readonly serverId: string
  readonly pid: number
}

/** A holder rather than a `let`: a closure-assigned `let` is narrowed to its
 * initial value, which would make the child's exit code permanently unreadable
 * — and that code is the whole evidence for `SERVER_EXITED_EARLY`. */
interface ExitRecord {
  value: { code: number | null; signal: string | null } | null
}

export interface ServerBridgeOptions {
  readonly env?: Readonly<Record<string, string | undefined>>
  /** Overrides the resolved data root; otherwise C-01's order applies. */
  readonly dataRoot?: string
  /** Readiness budget. C-02's default is 15 s. */
  readonly readyTimeoutMs?: number
  /** Injected for tests: the readiness probe. Defaults to `GET /live`. */
  readonly probe?: (origin: string) => Promise<boolean>
  /** Injected for tests: a stand-in for the real child process. */
  readonly spawnProcess?: typeof spawn
}

/** C-02 §3.2: `serverInstanceId(origin, serverId)`, unchanged in shape. */
export function serverInstanceId(origin: string, serverId: string): string {
  return `${origin}|${serverId}`
}

/**
 * Read a handshake line, strictly.
 *
 * Anything that is not exactly the documented object is refused, and the
 * caller turns that into a malformed-handshake error. Guessing at a near-miss
 * would be how a host ends up talking to the wrong process.
 */
export function parseHandshake(line: string): HandshakeLine | null {
  let payload: unknown
  try {
    payload = JSON.parse(line)
  } catch {
    return null
  }
  if (typeof payload !== 'object' || payload === null) return null
  const candidate = payload as Record<string, unknown>
  if (candidate['event'] !== layout().launch.handshakeEvent) return null
  if (Object.keys(candidate).sort().join(',') !== 'event,origin,pid,serverId') return null
  const { origin, serverId, pid } = candidate
  if (typeof origin !== 'string' || !/^http:\/\/127\.0\.0\.1:\d+$/.test(origin)) return null
  if (typeof serverId !== 'string' || serverId.length === 0) return null
  if (typeof pid !== 'number' || !Number.isInteger(pid) || pid <= 0) return null
  return { event: candidate['event'] as string, origin, serverId, pid }
}

/** The readiness probe of C-02 §4. No auth: it returns no data. */
async function defaultProbe(origin: string): Promise<boolean> {
  const response = await fetch(`${origin}${layout().launch.livePath}`, {
    signal: AbortSignal.timeout(2000),
  })
  if (!response.ok) return false
  const body = (await response.json()) as { status?: string }
  return body.status === 'alive'
}

/** The last few lines of the Server log, for a failure that needs evidence. */
function logTail(logFile: string, lines = 20): string | null {
  try {
    if (!existsSync(logFile) || !statSync(logFile).isFile()) return null
    const all = readFileSync(logFile, 'utf8').split('\n').filter((line) => line.length > 0)
    return all.slice(-lines).join('\n')
  } catch {
    return null
  }
}

export class ServerBridge {
  #state: ServerState = 'idle'
  #child: ServerChild | null = null
  #instance: ServerInstance | null = null
  #stopping = false
  #lastCrash: ServerCrashed | null = null
  readonly #options: ServerBridgeOptions

  constructor(options: ServerBridgeOptions = {}) {
    this.#options = options
  }

  get state(): ServerState {
    return this.#state
  }

  get instance(): ServerInstance | null {
    return this.#instance
  }

  get origin(): string | null {
    return this.#instance?.origin ?? null
  }

  get scope(): string | null {
    return this.#instance?.scope ?? null
  }

  /** The crash that moved the bridge to `crashed`, if that is how it got there. */
  get lastCrash(): ServerCrashed | null {
    return this.#lastCrash
  }

  get #env(): Readonly<Record<string, string | undefined>> {
    return this.#options.env ?? process.env
  }

  #dataRoot(): string {
    return this.#options.dataRoot ?? resolveDataRoot(this.#env).path
  }

  /**
   * Start the Server and return only once it is genuinely ready.
   *
   * The order is the contract's: resolve the data root, resolve the bundled
   * runtime (refusing early), spawn, read the handshake, probe. A refusal at
   * any step leaves nothing running — a half-started Server would be exactly
   * the "half-usable state" C-02 §6 forbids.
   */
  async start(): Promise<ServerInstance> {
    if (this.#state !== 'idle' && this.#state !== 'stopped' && this.#state !== 'failed') {
      throw new Error(`the bridge is ${this.#state}; it cannot start from here`)
    }
    const env = this.#env
    const dataRoot = this.#dataRoot()
    // Asked BEFORE the child exists, so a symlinked root is refused without
    // a process ever having touched the link's target.
    assertNoSymlink(dataRoot)
    // C-02 §6: a missing bridge is refused here, before any spawn.
    const runtime = resolveBundledRuntime(env)

    this.#state = 'spawning'
    this.#stopping = false
    this.#lastCrash = null
    const logFile = serverLogFileOf(dataRoot)
    const timeoutMs = this.#options.readyTimeoutMs ?? layout().launch.readyTimeoutMs
    const spawnFn = this.#options.spawnProcess ?? spawn
    const [executable, ...args] = serverCommand(runtime)

    let child: ServerChild
    try {
      child = spawnFn(executable, args, {
        env: {
          ...(process.env as Record<string, string>),
          ...(env as Record<string, string>),
          // Only the data root crosses at spawn time: the origin does not
          // exist yet. C-02 §2's other two variables are handed to the
          // extension host once the handshake has been read.
          [layout().launch.dataRootEnv]: dataRoot,
        },
        stdio: ['ignore', 'pipe', 'pipe'],
        // Its own process group: stopping the Server takes its children with
        // it, and a pid that is not ours is never a target.
        detached: true,
      }) as ServerChild
    } catch {
      this.#state = 'failed'
      throw new ServerExitedEarly(null, null, { logRef: logFile, logTail: logTail(logFile) })
    }
    this.#child = child

    const exited: ExitRecord = { value: null }
    child.once('exit', (code, signal) => {
      exited.value = { code, signal }
    })

    const line = await this.#readHandshake(child, timeoutMs, exited)
    if (line === null) {
      this.#state = 'failed'
      if (exited.value !== null) {
        this.#killChild()
        throw new ServerExitedEarly(exited.value.code, exited.value.signal, {
          logRef: logFile,
          logTail: logTail(logFile),
        })
      }
      // Silence, not a wrong line: the child is alive but never spoke, so
      // the honest failure is a start timeout.
      this.#killChild()
      throw new ServerStartTimeout(timeoutMs, { logRef: logFile, logTail: logTail(logFile) })
    }

    const handshake = parseHandshake(line)
    if (handshake === null) {
      this.#state = 'failed'
      this.#killChild()
      throw new ServerHandshakeMalformed(line)
    }

    this.#state = 'probing'
    const probe = this.#options.probe ?? defaultProbe
    const ready = await this.#withDeadline(probe(handshake.origin), timeoutMs)
    if (!ready) {
      this.#state = 'failed'
      this.#killChild()
      throw new ServerStartTimeout(timeoutMs, { logRef: logFile, logTail: logTail(logFile) })
    }

    this.#instance = {
      origin: handshake.origin,
      serverId: handshake.serverId,
      pid: child.pid ?? handshake.pid,
      scope: serverInstanceId(handshake.origin, handshake.serverId),
      startedAt: new Date().toISOString(),
      state: 'ready',
    }
    this.#state = 'ready'
    this.#watchForCrash(logFile)
    return this.#instance
  }

  /** C-02 §2's three variables, for the host to hand the extension host. */
  launchEnvironment(): Readonly<Record<string, string>> {
    if (this.#instance === null) {
      throw new Error('the bridge is not ready; there is no origin to hand over')
    }
    return launchEnv(this.#dataRoot(), this.#instance.origin)
  }

  /** The locator a connector is given. Never the token behind it. */
  get tokenFile(): string {
    return tokenFileOf(this.#dataRoot())
  }

  /**
   * Stop the Server this object started, and nothing else.
   *
   * SIGTERM first, SIGKILL after the grace period. A pid this host did not
   * spawn cannot appear here: `#child` is the only source of a target, so
   * "only kill what I spawned" is a property of the code, not a promise.
   */
  async stop(graceMs = 5000): Promise<void> {
    const child = this.#child
    if (child === null) return
    this.#stopping = true
    this.#state = 'stopping'
    const pid = child.pid
    if (pid === undefined) {
      this.#finishStop()
      return
    }
    const gone = new Promise<void>((resolve) => child.once('exit', () => resolve()))
    // The NEGATIVE pid addresses the whole process group this spawn created.
    // A positive pid alone would leave an orphaned helper holding the port.
    if (!signalGroup(pid, 'SIGTERM')) {
      this.#finishStop()
      return
    }
    const timer = setTimeout(() => {
      signalGroup(pid, 'SIGKILL')
    }, graceMs)
    await gone
    clearTimeout(timer)
    this.#finishStop()
  }

  /** The C-02 §2 environment for a data root, for a host that starts no child. */
  static launchEnvironmentFor(dataRoot: string, origin: string): Readonly<Record<string, string>> {
    return launchEnv(dataRoot, origin)
  }

  #finishStop(): void {
    this.#child = null
    this.#instance = null
    this.#state = 'stopped'
  }

  #killChild(): void {
    const pid = this.#child?.pid
    if (pid !== undefined) signalGroup(pid, 'SIGKILL')
  }

  /** A child that dies after readiness is a CRASH, not a quiet stop. */
  #watchForCrash(logFile: string): void {
    const child = this.#child
    if (child === null) return
    child.once('exit', (code, signal) => {
      if (this.#stopping) return
      this.#state = 'crashed'
      this.#lastCrash = new ServerCrashed(code, signal, {
        logRef: logFile,
        logTail: logTail(logFile),
      })
    })
  }

  /**
   * Read the first line of stdout, or answer null.
   *
   * `null` means only "nothing arrived". A line that arrived but is not a
   * handshake is returned to the caller, which refuses it as malformed —
   * conflating the two sends a reader to the wrong place.
   */
  #readHandshake(
    child: ServerChild,
    timeoutMs: number,
    exited: ExitRecord,
  ): Promise<string | null> {
    return new Promise<string | null>((resolve) => {
      let settled = false
      let timer: NodeJS.Timeout
      const finish = (value: string | null): void => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        child.stdout.off('data', onData)
        child.off('exit', onExit)
        resolve(value)
      }
      const onData = (chunk: Buffer): void => {
        const first = (chunk.toString('utf8').split('\n')[0] ?? '').trim()
        if (first.length > 0) finish(first)
      }
      const onExit = (): void => {
        if (exited.value !== null) finish(null)
      }
      timer = setTimeout(() => finish(null), timeoutMs)
      child.stdout.on('data', onData)
      child.once('exit', onExit)
    })
  }

  async #withDeadline(work: Promise<boolean>, timeoutMs: number): Promise<boolean> {
    let timer: NodeJS.Timeout | undefined
    const expiry = new Promise<boolean>((resolve) => {
      timer = setTimeout(() => resolve(false), timeoutMs)
    })
    try {
      return await Promise.race([work, expiry])
    } catch {
      return false
    } finally {
      if (timer !== undefined) clearTimeout(timer)
    }
  }
}

/** Signal the whole group, falling back to the single pid. Never throws. */
function signalGroup(pid: number, signal: NodeJS.Signals): boolean {
  try {
    process.kill(-pid, signal)
    return true
  } catch {
    try {
      process.kill(pid, signal)
      return true
    } catch {
      return false
    }
  }
}
