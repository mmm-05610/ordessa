import { spawn } from "node:child_process"
import { EventEmitter } from "node:events"

// An adapter launched through `npx` downloads itself on first use, which takes far longer
// than a warm start. Ten seconds failed on a cold PI adapter while npm was still fetching.
const START_TIMEOUT_MS = 90_000
const REQUEST_TIMEOUT_MS = 30_000
/** Kept so a failed handshake can report why the adapter died instead of just its exit code. */
const STDERR_KEPT_CHARS = 600

/**
 * JSON-RPC only promises a human-readable `message`, and adapters sometimes spend it on a bare
 * "Internal error", putting the actionable detail in `data.details` or `data.message`.
 * PATCH (Ordessa): also preserve the string `data.error` used by acp-adapter.
 */
function acpErrorMessage(error) {
  const message = error?.message ?? "ACP adapter request failed"
  const details = [error?.data?.details, error?.data?.message, error?.data?.error].find(
    (value) => typeof value === "string" && value
  )
  return details && !message.includes(details) ? `${message}: ${details}` : message
}

export class AcpClient extends EventEmitter {
  #command
  #args
  #spawn
  #permissionMode
  #permissionResolver
  #permissionTimeoutMs
  #preferredAuthMethod
  // PATCH (AgentBox HD-002): see `transportOnly` in the constructor.
  #transportOnly
  #cwd = null
  #child
  #buffer = ""
  #nextID = 1
  #pending = new Map()
  #starting
  #agentInfo
  #promptCapabilities = {}
  #sessionCapabilities = {}
  #stderr = ""
  #stderrPartial = ""

  /**
   * PATCH (AgentBox HD-002): `transportOnly` turns this client into a plain ACP transport.
   *
   * Three upstream behaviours are what a caller owning the ACP conversation cannot live with, and
   * all three are skipped only when the flag is set:
   *   · `#start()` sends `initialize` and then picks and sends `authenticate` itself;
   *   · `#consumeMessage()` matches a reply against the ids *this* client minted and would swallow
   *     one it does not recognise, and answers an agent-initiated request from the static
   *     `permissionMode` (`#respondPermission`) or with `-32601` (`#respondUnsupported`);
   *   · `request()` puts an id of its own on the wire and collapses an error reply into a JS
   *     `Error`, so neither the id nor the error object survives a round trip.
   * With the flag, nothing is sent that the caller did not write, and every frame the adapter
   * emits leaves on the `frame` event unchanged. Without it, this class behaves byte-for-byte as
   * before; the default path is the upstream path.
   */
  constructor({ command = "omp", args = ["acp"], permissionMode = "deny", permissionResolver = null, permissionTimeoutMs = 0, preferredAuthMethod, spawnProcess = spawn, transportOnly = false, cwd = null } = {}) {
    super()
    this.#command = command
    this.#args = args
    this.#permissionMode = permissionMode
    this.#permissionResolver = permissionResolver
    this.#permissionTimeoutMs = permissionTimeoutMs
    this.#preferredAuthMethod = preferredAuthMethod
    this.#transportOnly = transportOnly
    this.#cwd = cwd
    this.#spawn = spawnProcess
  }

  get agentInfo() {
    return this.#agentInfo
  }

  /**
   * What the agent says it accepts in a prompt. The bridge refuses an attachment the
   * agent never advertised rather than sending a block it would reject mid-turn.
   */
  get promptCapabilities() {
    return this.#promptCapabilities
  }

  /**
   * Which session operations the agent advertised in `initialize`.
   *
   * ACP lets an agent offer `session/resume` next to `session/load`, and the two are not
   * interchangeable: an agent that advertises `resume` opens a stored Session without replaying it.
   * The bridge only ever sends a method the running adapter said it has, so an older build of the
   * same harness keeps working on the method it does advertise.
   */
  get sessionCapabilities() {
    return this.#sessionCapabilities
  }

  /** PID identifies extension runtime state published by this exact ACP process. */
  get processID() {
    return Number.isInteger(this.#child?.pid) ? this.#child.pid : undefined
  }

  diagnostics() {
    const now = Date.now()
    const pendingRequests = [...this.#pending.values()].map((pending) => ({
      method: pending.method,
      ...(pending.sessionID ? { sessionID: pending.sessionID } : {}),
      ...(pending.configID ? { configID: pending.configID } : {}),
      ageMs: Math.max(0, now - pending.startedAt),
      idleMs: Math.max(0, now - pending.lastActivityAt),
      timeoutMs: pending.timeoutMs
    }))
    const listenerCounts = Object.fromEntries(
      this.eventNames().map((eventName) => [String(eventName), this.listenerCount(eventName)])
    )
    return {
      state: this.#starting ? "starting" : this.processID ? "running" : "stopped",
      processID: this.processID,
      startInFlight: Boolean(this.#starting),
      pendingRequestCount: pendingRequests.length,
      oldestPendingMs: pendingRequests.length ? Math.max(...pendingRequests.map((request) => request.ageMs)) : 0,
      pendingRequests,
      listenerCount: Object.values(listenerCounts).reduce((total, count) => total + count, 0),
      listenerCounts
    }
  }

  async start(timeoutMs = START_TIMEOUT_MS) {
    if (this.#child) return
    if (this.#starting) return this.#starting
    this.#starting = this.#start(timeoutMs)
    try {
      await this.#starting
    } finally {
      this.#starting = undefined
    }
  }

  async #start(timeoutMs) {
    const deadline = Date.now() + Math.max(1, timeoutMs)
    const remaining = (phase) => {
      const value = deadline - Date.now()
      if (value <= 0) throw new Error(`ACP adapter startup timed out during ${phase}`)
      return value
    }
    const windowsCommand = process.platform === "win32" && this.#spawn === spawn && /\.(cmd|bat)$/i.test(this.#command)
      ? process.env.ComSpec ?? "cmd.exe"
      : this.#command
    const windowsArgs = windowsCommand === this.#command
      ? this.#args
      : ["/d", "/s", "/c", this.#command, ...this.#args]
    const child = this.#spawn(windowsCommand, windowsArgs, {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      // PATCH (AgentBox HD-002): a transport-only caller names the directory the Harness runs in,
      // which is the product's project directory rather than whatever the launching process
      // inherited. Unset, the spawn options are exactly what they were.
      ...(this.#cwd ? { cwd: this.#cwd } : {})
    })
    this.#child = child
    // Each attempt reports its own stderr. Carrying the buffer across restarts made every exit
    // message repeat the previous ones, so a single "pi-acp: not found" arrived three times over.
    this.#stderr = ""
    this.#stderrPartial = ""
    // PATCH (AgentBox 增量1b): the same carry-over existed one side over. A half stdout frame from
    // the previous process was prepended to this process's first message, which ate the response to
    // `initialize` and wedged restart until the startup timeout.
    this.#buffer = ""
    child.stdout.setEncoding("utf8")
    child.stderr.setEncoding("utf8")
    child.stdout.on("data", (chunk) => this.#consume(chunk))
    child.stderr.on("data", (chunk) => {
      this.#stderr = `${this.#stderr}${chunk}`.slice(-STDERR_KEPT_CHARS)
      // Emit whole lines. A chunk boundary falls wherever the pipe happens to flush, so a listener
      // that prefixes what it receives would otherwise print `[pi] sh: 1: [pi] pi-acp: not found`.
      const pending = `${this.#stderrPartial}${chunk}`.split(/\r?\n/)
      this.#stderrPartial = pending.pop() ?? ""
      for (const line of pending) this.emit("stderr", line)
    })
    child.on("error", (error) => this.#handleExit(error))
    child.on("exit", (code, signal) => {
      if (this.#stderrPartial) {
        this.emit("stderr", this.#stderrPartial)
        this.#stderrPartial = ""
      }
      // PATCH (AgentBox 增量1b): a final frame without a trailing newline never reached
      // `#consumeMessage`, so the turn's own response could vanish in silence. Flush it while the
      // child identity is still this one, before the exit is reported and pending work is rejected.
      this.#flushBuffer()
      const reason = this.#stderrSummary()
      this.#handleExit(new Error(
        `ACP adapter exited (${code ?? "unknown"}${signal ? `, ${signal}` : ""})${reason ? `: ${reason}` : ""}`
      ))
    })

    // PATCH (AgentBox HD-002): transport-only stops here. The process is spawned and its three
    // pipes are wired, so `processID`, `stderr` reporting, `exit` reporting and `write()` all work;
    // everything below is the handshake this client used to perform on the caller's behalf, and a
    // caller that owns the ACP conversation must be the one to send it.
    if (this.#transportOnly) return

    try {
      const initialized = await this.request("initialize", {
        protocolVersion: 1,
        clientCapabilities: {},
        clientInfo: { name: "harness-remote-bridge", version: "0.1.7" }
      }, remaining("initialize"))
      this.#agentInfo = initialized.agentInfo
      this.#promptCapabilities = initialized.agentCapabilities?.promptCapabilities ?? {}
      this.#sessionCapabilities = initialized.agentCapabilities?.sessionCapabilities ?? {}
      // The bridge always runs beside a harness the user already configured, so prefer a method
      // that uses those credentials. PI's adapter offers `anthropic-api-key` first and
      // `pi-stored-credentials` last: picking the first would claim an API key from an
      // environment variable that is usually unset, and fail later at inference rather than here.
      // Codex's adapter lists `api-key` first too, but its ChatGPT login method is what reads a
      // `codex login` from disk, so a profile may name the method its harness expects.
      const authMethods = Array.isArray(initialized.authMethods) ? initialized.authMethods : []
      let authMethod = this.#preferredAuthMethod
        ? authMethods.find((method) => method?.id === this.#preferredAuthMethod)
        : undefined
      authMethod ??= authMethods.find((method) => method?.id === "agent")
        ?? authMethods.find((method) => method?.id && method.type !== "env_var")
        ?? authMethods.find((method) => method?.id)
      if (authMethod) await this.request("authenticate", { methodId: authMethod.id }, remaining("authenticate"))
    } catch (error) {
      this.close()
      throw error
    }
  }

  request(method, params, timeoutMs = REQUEST_TIMEOUT_MS) {
    if (!this.#child || this.#child.killed || !this.#child.stdin.writable) {
      return Promise.reject(new Error("ACP adapter is not running"))
    }
    const id = this.#nextID++
    const message = JSON.stringify({ jsonrpc: "2.0", id, method, params })
    return new Promise((resolve, reject) => {
      const startedAt = Date.now()
      const pending = {
        resolve,
        reject,
        timer: undefined,
        method,
        // Every session-scoped RPC reports which Session it is waiting on, not just prompts. A stuck
        // `session/load` or `session/set_config_option` was previously indistinguishable from any
        // other pending request, which is what made a wedged model change impossible to attribute.
        sessionID: typeof params?.sessionId === "string" ? params.sessionId : undefined,
        configID: typeof params?.configId === "string" ? params.configId : undefined,
        startedAt,
        lastActivityAt: startedAt,
        timeoutMs,
        resetTimeout: undefined
      }
      const expire = () => {
        this.#pending.delete(id)
        reject(new Error(`ACP adapter request timed out: ${method}`))
      }
      pending.resetTimeout = () => {
        pending.lastActivityAt = Date.now()
        clearTimeout(pending.timer)
        pending.timer = setTimeout(expire, timeoutMs)
      }
      pending.resetTimeout()
      this.#pending.set(id, pending)
      this.#child.stdin.write(`${message}\n`, (error) => {
        if (error) {
          clearTimeout(pending.timer)
          this.#pending.delete(id)
          reject(error)
        }
      })
    })
  }

  /**
   * PATCH (AgentBox HD-002): send one frame the *caller* composed, with its id and fields intact.
   *
   * `request()` cannot serve this: it mints `#nextID` over the top of whatever it is given and
   * returns a promise for a parsed result, which is how a real ACP id and a real ACP error object
   * both disappear. `notify()` is the same write without the transport claim; this is the entry a
   * transport-only client uses for every frame direction it is asked to forward.
   */
  write(message) {
    if (!this.#child || this.#child.killed || !this.#child.stdin.writable) {
      throw new Error("ACP adapter is not running")
    }
    this.#child.stdin.write(`${JSON.stringify(message)}\n`)
  }

  /**
   * PATCH (AgentBox HD-002): the byte-transparent twin of `write()` — send this exact text as one
   * frame. A relay that re-serialises the peer's message has decided something about it (number
   * formatting, key representation); a relay that forwards the line it was given has decided
   * nothing, which is what an access layer that must not project ACP into its own vocabulary is for.
   */
  writeLine(line) {
    if (!this.#child || this.#child.killed || !this.#child.stdin.writable) {
      throw new Error("ACP adapter is not running")
    }
    this.#child.stdin.write(`${line}\n`)
  }

  notify(method, params) {
    if (!this.#child || this.#child.killed || !this.#child.stdin.writable) {
      throw new Error("ACP adapter is not running")
    }
    this.#child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`)
  }

  async listSessionPage(cursor) {
    await this.start()
    const result = await this.request("session/list", cursor ? { cursor } : {})
    return {
      sessions: result.sessions ?? [],
      ...(typeof result.nextCursor === "string" && result.nextCursor ? { nextCursor: result.nextCursor } : {})
    }
  }

  async listSessions() {
    return (await this.listSessionPage()).sessions
  }

  close() {
    const child = this.#child
    // PATCH (AgentBox 增量1b): see the `exit` flush. Flushing before the child is dropped keeps a
    // residue that is a valid response from being lost when the bridge closes on purpose.
    this.#flushBuffer()
    this.#child = undefined
    if (child && !child.killed) child.kill()
    this.#rejectPending(new Error("ACP adapter closed"))
  }

  #consume(chunk) {
    this.#buffer += chunk
    let boundary = this.#buffer.indexOf("\n")
    while (boundary !== -1) {
      const line = this.#buffer.slice(0, boundary).trim()
      this.#buffer = this.#buffer.slice(boundary + 1)
      if (line) this.#consumeMessage(line)
      boundary = this.#buffer.indexOf("\n")
    }
  }

  /**
   * PATCH (AgentBox 增量1b): give whatever is left in the line buffer the same treatment as a
   * complete line. `#consume` only ever leaves a residue without a newline in it, so this is at most
   * one frame. Unparseable residue takes the existing `protocol-error` channel rather than
   * introducing a new event type.
   */
  #flushBuffer() {
    const residue = this.#buffer
    this.#buffer = ""
    const line = residue.trim()
    if (line) this.#consumeMessage(line)
  }

  #consumeMessage(line) {
    let message
    try {
      message = JSON.parse(line)
    } catch {
      this.emit("protocol-error", new Error("ACP adapter emitted invalid JSON"))
      return
    }

    // PATCH (AgentBox HD-002): in transport-only mode every parsed frame is the caller's, in both
    // directions, so it goes out unchanged and none of the routing below happens: no id is matched
    // against requests this client minted (it minted none, and an unrecognised id would otherwise
    // be dropped), no inactivity watchdog is reset, and no agent-initiated request is answered from
    // `permissionMode` or refused with `-32601`. A frame the caller has not answered yet is simply
    // a frame the caller has not answered yet.
    if (this.#transportOnly) {
      // The second argument is the line as the adapter wrote it. A transport that re-serialised
      // what it parsed would be transparent only as far as `JSON.stringify` agrees with the peer,
      // so callers that relay get the original text; the parsed object is there for anyone who
      // needs to look at a field.
      this.emit("frame", message, line)
      return
    }

    // A long ACP prompt is alive as long as that same Session keeps producing protocol traffic.
    // Treat its timeout as an inactivity watchdog, not a wall-clock cap on legitimate long turns.
    if (typeof message.params?.sessionId === "string") this.#touchSessionActivity(message.params.sessionId)

    // A JSON-RPC message carrying both an id and a method is an agent-initiated
    // request. An unanswered request would stall the agent until the prompt
    // timeout, so always reply.
    if (message.id !== undefined && message.method) {
      this.emit("agent-request", message)
      if (message.method === "session/request_permission") this.#respondPermission(message.id, message.params)
      else this.#respondUnsupported(message.id, message.method)
      return
    }
    if (message.id !== undefined) {
      const pending = this.#pending.get(message.id)
      if (!pending) return
      clearTimeout(pending.timer)
      this.#pending.delete(message.id)
      if (message.error) pending.reject(new Error(acpErrorMessage(message.error)))
      else pending.resolve(message.result)
      return
    }
    if (message.method) this.emit("notification", message)
  }

  #touchSessionActivity(sessionID) {
    for (const pending of this.#pending.values()) {
      if (pending.method !== "session/prompt" || pending.sessionID !== sessionID) continue
      pending.resetTimeout?.()
    }
  }

  /**
   * A tool call stalls without an answer, and answering with an error silently stops the agent
   * from doing any work. PI reported success while touching no file. Granting matches OMP,
   * whose agent approves its own tool calls and never asks, and there is no way to prompt the
   * user mid-turn on a phone. `allow_once` is preferred over `allow_always` so the grant covers
   * this call rather than writing a lasting permission into the harness's own state.
   *
   * PATCH (AgentBox Work Order 40-A): when a `permissionResolver` was injected, its awaited
   * decision owns the answer instead of the static `permissionMode` shortcut. The resolver
   * receives `{ toolCall, options }` and returns the `optionId` of one of `options`, or
   * `null`/`undefined`/a thrown error to deny. An unanswered decision, a timeout, or a child
   * disconnect defaults to deny (`cancelled`); a stale answer after a reconnect can never be
   * written because the child identity is re-checked after the await. Without a resolver the
   * original static selection below is byte-for-byte unchanged.
   */
  async #respondPermission(id, params) {
    if (!this.#child?.stdin.writable) return
    const child = this.#child
    const options = Array.isArray(params?.options) ? params.options : []
    let optionId
    if (this.#permissionResolver) {
      optionId = await this.#resolvePermission(params, options)
      if (this.#child !== child || !child.stdin.writable) return
    } else {
      const allowed = this.#permissionMode === "allow"
        ? options.find((option) => option.kind === "allow_once")
          ?? options.find((option) => option.kind === "allow_always")
          ?? options.find((option) => typeof option.kind === "string" && option.kind.startsWith("allow"))
        : undefined
      optionId = allowed?.optionId
    }
    const outcome = optionId
      ? { outcome: "selected", optionId }
      : { outcome: "cancelled" }
    this.emit("permission", { optionId })
    child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, result: { outcome } })}\n`)
  }

  async #resolvePermission(params, options) {
    try {
      const decision = this.#permissionTimeoutMs > 0
        ? await Promise.race([
            Promise.resolve(this.#permissionResolver({ toolCall: params?.toolCall, options })),
            new Promise((_, reject) => setTimeout(
              () => reject(new Error("permission decision timed out")), this.#permissionTimeoutMs,
            )),
          ])
        : await this.#permissionResolver({ toolCall: params?.toolCall, options })
      return options.find((option) => option.optionId === decision)?.optionId
    } catch {
      return undefined
    }
  }

  #respondUnsupported(id, method) {
    if (!this.#child?.stdin.writable) return
    const error = { code: -32_601, message: `Harness Remote bridge does not implement ${method}` }
    this.#child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, error })}\n`)
  }

  /**
   * The adapter explains a missing prerequisite on stderr; without this the caller only sees an
   * exit code. Several lines are kept because a Windows shell error wraps the useful part:
   * "'bun' is not recognized..." arrives split from the sentence that follows it.
   */
  #stderrSummary() {
    const lines = this.#stderr.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    return lines.slice(-3).join(" ")
  }

  #handleExit(error) {
    if (!this.#child) return
    this.#child = undefined
    this.#rejectPending(error)
    this.emit("exit", error)
  }

  #rejectPending(error) {
    for (const pending of this.#pending.values()) {
      clearTimeout(pending.timer)
      pending.reject(error)
    }
    this.#pending.clear()
  }
}
