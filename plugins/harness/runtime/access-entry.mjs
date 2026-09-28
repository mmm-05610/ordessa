/**
 * AgentBox Harness access entry — the plugin's one production entry for connecting to a Harness.
 *
 * It owns the five responsibilities the access layer has and no others:
 *
 *   1. **discovery** — `harnesses` lists the brands this plugin can connect to, and a connect
 *      reports the launch context discovery derived for that brand next to the one actually used;
 *   2. **connect** — `connect` starts the Harness with a verified brand route for managed ACP brands
 *      transmits **no ACP frame** while doing it; one establishment at a time, reserved before the
 *      launch is awaited, because "one connection per process" has to be enforced rather than hoped
 *      for;
 *   3. **transport** — every other line on stdin is an ACP frame and goes to the Harness as
 *      written; every line the Harness writes comes back as written, including requests it raises
 *      itself and errors it answers with. Which lines are "other" is decided by shape, not by one
 *      field: a frame that declares itself JSON-RPC is relayed even if it carries an `op` of its own;
 *   4. **state** — `status` reports the connection and process, and the end of the transport is
 *      reported as its own event when the process exits;
 *   5. **close** — `close` releases the process this entry started and nothing else, and says so only
 *      once the OS has stopped answering for that pid. A Harness that ignores the graceful signal is
 *      escalated; a release that still cannot be confirmed is reported as a failure with the process
 *      identity kept, never as `released: true`.
 *
 * What is deliberately absent: no session, turn, snapshot or model-catalog management; no
 * `permissionRoundTrip`, `permissionTimeoutMs` or brand `permissionMode`, because those are how the
 * old chain answered the Harness on the caller's behalf; no product model-id aliasing on the way
 * out, because that rewrites an ACP parameter. The old envelope and the native-driver branch that
 * served it are retired — see `REMOVALS.md` for what went and where it is recoverable from.
 *
 * **One connection per process.** A byte-transparent relay cannot multiplex two Harnesses over one
 * pair of stdin/stdout lines without stamping each frame with a discriminator, and a stamp is
 * exactly the envelope this entry exists to stop using. A caller that needs two connections starts
 * two entries; Workcore already owns one channel run per execution.
 *
 * Security posture carried over from the retired entry: the Worker must say it is isolated
 * (`AGENTBOX_SIDECAR_ISOLATED=1`) or the caller must ask for native mode explicitly, never both;
 * the reused snapshot is hash-verified before anything runs; adapter environment names are validated
 * and refused when they look like credentials; and a credential value read from the Worker's secret
 * path is redacted out of every diagnostic this process emits.
 */
import { createHash } from "node:crypto"
import { readFileSync, realpathSync } from "node:fs"
import { spawn } from "node:child_process"
import path from "node:path"
import { fileURLToPath } from "node:url"
import readline from "node:readline"
import { harnessLaunchContext, isKnownHarness } from "../harnesses/index.mjs"
import { openAcpConnection, PROCESS_GROUP_OWNERSHIP } from "./access-transport.mjs"
import { resolveManagedLaunch, resolveLegacyLaunch, allowsPythonPath, launchDiscovery } from "./access-launch.mjs"

const here = path.dirname(fileURLToPath(import.meta.url))
const snapshotRoot = path.resolve(here, "..", "third_party", "harness_remote")
const CREDENTIAL_PATH = "/runtime/secret/credential"
const ENVIRONMENT_KEY = /^[A-Z][A-Z0-9_]{0,63}$/
const SENSITIVE_ENVIRONMENT_KEY = /(TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL|AUTH)/i
const LAUNCH_OVERRIDE_KEY = /^(?:NODE_OPTIONS|NODE_PATH|PATH|LD_PRELOAD|LD_LIBRARY_PATH|DYLD_.*|PYTHONHOME|PYTHONSTARTUP|PYTHONINSPECT)$/

/** The whole control vocabulary. Anything else on stdin is an ACP frame, not a request. */
const CONTROL_FIELDS = new Set(["op", "id"])
const CONNECT_FIELDS = new Set(["harness", "launch", "directory", "credentialEnvironment"])
const LAUNCH_FIELDS = new Set(["command", "args", "environment"])
/**
 * The two fields that mark a message as belonging to the JSON-RPC conversation rather than to this
 * entry's own control envelope. `jsonrpc` is what a conforming peer declares; `method` is what a
 * request carries. A reply is covered too, because a message with a `result` or `error` is an answer
 * to a frame the caller sent, and an entry that swallowed it would strand the caller's own turn.
 */
const JSON_RPC_MARKERS = ["jsonrpc", "method", "result", "error"]

/**
 * Control or data? Decided by the shape of the message, never by one field of it.
 *
 * A top-level string `op` on its own is not enough: `op` is a legal extension member of an ACP frame,
 * and an entry that treated such a frame as its own would hijack traffic it was asked to relay — the
 * caller would see its frame vanish and a `UNKNOWN_OP` back instead of the Harness's answer. So a
 * message that declares itself part of the JSON-RPC conversation goes to the Harness unchanged, and
 * only a bare control object (this entry's own envelope, which carries no `jsonrpc` and no `method`)
 * is handled here. The rule is one-directional on purpose: it can only ever move a message from
 * control to the data channel, never the other way.
 */
function isControlRequest(message) {
  return typeof message.op === "string"
    && !JSON_RPC_MARKERS.some((field) => message[field] !== undefined)
}
/**
 * Names the retired envelope used for one job or another. They are refused by name rather than
 * ignored: a caller that still sends `permissionTimeoutMs` believes it configured a timeout that
 * decides, and the honest answer to that belief is that this entry has no such knob.
 */
const RETIRED_CONNECT_FIELDS = [
  "profile", "stateDirectory", "permissionRoundTrip", "permissionTimeoutMs", "preferredAuthMethod",
  "driver", "title", "sessionId", "text", "model", "attachments", "requestId", "decision", "scope",
]

function verifyProvenance() {
  const source = JSON.parse(readFileSync(path.join(snapshotRoot, "SOURCE.json"), "utf8"))
  for (const file of source.files) {
    const expected = file.patched_sha256 ?? file.current_sha256 ?? file.upstream_sha256
    const actual = createHash("sha256").update(readFileSync(path.join(snapshotRoot, file.path))).digest("hex")
    if (actual !== expected) throw new Error(`PROVENANCE_MISMATCH: ${file.path}`)
  }
  return source
}

class Refused extends Error {
  constructor(code, detail) {
    super(detail ? `${code}: ${detail}` : code)
    this.code = code
  }
}

async function main() {
  const argv = process.argv.slice(2)
  const controlledPeer = argv.length === 2 && argv[0] === "--native" && argv[1] === "--controlled-test-peer"
  const native = argv[0] === "--native"
  if ((!controlledPeer && argv.length !== (native ? 1 : 0)) ||
      (controlledPeer && process.env.AGENTBOX_ACCESS_TEST_MODE !== "controlled-peer-v1")) {
    fail({ code: "SIDECAR_MODE_INVALID" })
    return
  }
  if (native && process.env.AGENTBOX_SIDECAR_ISOLATED === "1") {
    fail({ code: "SIDECAR_MODE_CONFLICT" })
    return
  }
  if (!native && process.env.AGENTBOX_SIDECAR_ISOLATED !== "1") {
    fail({ code: "SIDECAR_ISOLATION_REQUIRED" })
    return
  }
  let source
  try {
    source = verifyProvenance()
  } catch (error) {
    fail({ code: "PROVENANCE_UNREADABLE", message: String(error?.message ?? error) })
    return
  }

  let connection = null
  let credentialValue = null
  /**
   * Every Harness process this entry started and has not confirmed gone.
   *
   * `connection` is only the handle the transport is currently routed to, so it cannot be the
   * bookkeeping for releases: a handle produced by a connect that then failed, or one whose release
   * was refused by the process, would otherwise belong to nobody while its process kept running.
   */
  const owned = new Set()
  /**
   * The establishment in flight, or `null`. Checking `connection` and then awaiting the launch is not
   * enough on its own: `connection` is assigned after the launch, so a second connect arriving during
   * that window would pass the check and start a second Harness whose handle the first then
   * overwrites. One reservation, taken before the first await, is what makes "one connection per
   * process" true rather than merely intended.
   */
  let opening = null

  function reserveOpening() {
    let settle
    const settled = new Promise((resolve) => { settle = resolve })
    // `done` clears the reservation before it wakes anyone waiting on it, so a waiter re-reading
    // `opening` sees either nothing or a genuinely later establishment.
    const reservation = { settled, done: () => { if (opening === reservation) opening = null; settle() } }
    opening = reservation
    return reservation
  }

  /** Wait for the establishment in flight to reach its outcome; a no-op when there is none. */
  async function settleOpening() {
    while (opening) await opening.settled
  }

  /**
   * Release every Harness process tree still owned, and report it.
   *
   * `released` is true only when every process in every one of those trees was confirmed gone by the
   * OS — `ESRCH` for each pid the release could account for (see `releaseProcessTree`); a survivor or
   * a probe the OS answered any other way keeps its entry in `owned` and its identity and per-process
   * receipt in the report, so the caller is never handed `released: true` without evidence.
   */
  async function releaseOwned() {
    const serving = connection
    const reports = []
    for (const handle of [...owned]) {
      const report = await handle.close()
      if (report.released) owned.delete(handle)
      if (handle === serving && report.released) {
        connection = null
        credentialValue = null
      }
      reports.push(report)
    }
    const unreleased = reports.filter((report) => !report.released)
    const primary = reports.find((report) => report.connectionId === serving?.connectionId) ?? reports[0]
    return {
      connectionId: primary?.connectionId ?? null,
      released: unreleased.length === 0,
      processId: primary?.processId ?? null,
      signalUsed: primary?.signalUsed ?? null,
      // The reclaiming is what round 5 asks a report to prove, so it travels with the verdict rather
      // than staying inside the handle that wrote it.
      tree: primary?.tree ?? null,
      ...(unreleased.length
        ? {
            unreleased: unreleased.map((r) => ({
              connectionId: r.connectionId, processId: r.processId, tree: r.tree ?? null,
            })),
          }
        : {}),
    }
  }

  function safeText(value, maximum) {
    let text = String(value ?? "")
    if (credentialValue) text = text.replaceAll(credentialValue, "[REDACTED]")
    return text.slice(0, maximum)
  }
  function emit(message) {
    process.stdout.write(`${JSON.stringify(message)}\n`)
  }
  function fail({ id = null, code, message }) {
    emit({ id, ok: false, error: { code, message: message ?? code } })
  }
  function refusedError(error, id) {
    emit({
      id: id ?? null,
      ok: false,
      error: { code: error?.code ?? "SIDECAR_OP_FAILED", message: safeText(error?.message ?? error, 500) },
    })
  }

  async function connect(request) {
    if (connection) throw new Refused("ACP_ALREADY_CONNECTED", String(connection.connectionId))
    if (opening) throw new Refused("ACP_CONNECT_IN_PROGRESS")
    const unknown = Object.keys(request).filter((key) =>
      !CONTROL_FIELDS.has(key) && !CONNECT_FIELDS.has(key) && !key.startsWith("_"))
    if (unknown.length) {
      const retired = RETIRED_CONNECT_FIELDS.filter((name) => unknown.includes(name))
      throw new Refused(retired.length ? "ACP_CONNECT_FIELD_RETIRED" : "ACP_CONNECT_FIELD_UNKNOWN", retired.join(", "))
    }
    const harness = request.harness
    if (typeof harness !== "string" || !harness) throw new Refused("HARNESS_REQUIRED")
    if (!isKnownHarness(harness)) throw new Refused("HARNESS_UNDISCOVERED", harness)
    const launch = request.launch
    if (launch === null || typeof launch !== "object" || Array.isArray(launch)) {
      throw new Refused("ADAPTER_LAUNCH_REQUIRED")
    }
    const extraLaunchFields = Object.keys(launch).filter((key) => !LAUNCH_FIELDS.has(key) && !key.startsWith("_"))
    if (extraLaunchFields.length) throw new Refused("ADAPTER_LAUNCH_FIELD_UNKNOWN", extraLaunchFields.join(", "))
    if (typeof launch.command !== "string" || !launch.command) throw new Refused("ADAPTER_LAUNCH_REQUIRED")
    if (launch.args !== undefined && (!Array.isArray(launch.args)
        || launch.args.some((arg) => typeof arg !== "string"))) {
      throw new Refused("ADAPTER_ARGS_INVALID")
    }
    const environment = launch.environment ?? {}
    if (environment === null || typeof environment !== "object" || Array.isArray(environment)) {
      throw new Refused("ADAPTER_ENVIRONMENT_INVALID")
    }
    for (const [key, value] of Object.entries(environment)) {
      if (!ENVIRONMENT_KEY.test(key) || SENSITIVE_ENVIRONMENT_KEY.test(key) || LAUNCH_OVERRIDE_KEY.test(key)
          || !allowsPythonPath(harness, key)
          || typeof value !== "string" || value.length > 8192 || /[\0]/.test(value)
          || /^sk-[A-Za-z0-9_-]+$/.test(value)) {
        throw new Refused("ADAPTER_ENVIRONMENT_INVALID", key)
      }
    }
    let selectedLaunch
    if (controlledPeer) {
      // This fixture is absent from staged production artifacts. A renderer can only send control
      // frames; it cannot turn on this startup mode or choose a different executable through it.
      const fixtures = [
        { file: path.resolve(here, "..", "tests", "access", "controlled_harness.mjs") },
        { file: path.resolve(here, "..", "..", "..", "tests", "integration", "acp_orchestration", "fixtures",
          "bidirectional_acp_peer.mjs"), harness: "pi", exactPath: true },
      ]
      // The second path exists only in a source checkout. Neither path is a renderer-provided
      // executable, and the production entry cannot enter this mode through a connect frame.
      let exactFixture = false
      let fixture = null
      try {
        const requested = launch.args?.length === 1 ? realpathSync(launch.args[0]) : null
        fixture = fixtures.find((candidate) => {
          try {
            return (candidate.harness === undefined || harness === candidate.harness)
              && (!candidate.exactPath || launch.args[0] === candidate.file)
              && realpathSync(candidate.file) === candidate.file
              && requested === candidate.file
          }
          catch { return false }
        }) ?? null
        exactFixture = realpathSync(launch.command) === realpathSync(process.execPath)
          && fixture !== null
      } catch { /* an absent or stale path cannot select the controlled peer */ }
      if (!exactFixture) {
        throw new Refused("CONTROLLED_PEER_MISMATCH")
      }
      selectedLaunch = { command: process.execPath, args: [fixture.file], source: "controlled-test-peer" }
    } else {
      selectedLaunch = resolveManagedLaunch(harness, launch)
        ?? resolveLegacyLaunch(harness, launch, environment)
    }
    const credentialEnvironment = request.credentialEnvironment
    if (credentialEnvironment != null) {
      if (typeof credentialEnvironment !== "string" || !ENVIRONMENT_KEY.test(credentialEnvironment)) {
        throw new Refused("CREDENTIAL_ENVIRONMENT_INVALID")
      }
      credentialValue = readFileSync(CREDENTIAL_PATH, "utf8").trim()
      if (!credentialValue || credentialValue.length > 4096 || /[\r\n\0]/.test(credentialValue)) {
        credentialValue = null
        throw new Refused("CREDENTIAL_MATERIAL_INVALID")
      }
    }
    // The launch is put in a process group of its own (`detached` on POSIX, which makes the child a
    // session and group leader) so that "what this connection started" is a fact the OS can answer
    // rather than a list this process has to keep: a bridge that exits ahead of the Agent it started
    // leaves that Agent running, and `kill(-rootPid, …)` is the only thing that reaches it.
    //
    // On Windows the reused client keeps its own default `spawn` — it special-cases `.cmd` entries
    // there, and replacing it would quietly turn that handling off — so no group is claimed and the
    // release reports the single process it can account for instead. The two halves read one
    // constant, so the claim and the launch cannot drift apart.
    const groupLeadership = PROCESS_GROUP_OWNERSHIP ? { detached: true } : {}
    const needsEnvironment = Object.keys(environment).length > 0 || Boolean(credentialValue)
    let spawnProcess
    if (process.platform !== "win32" || needsEnvironment) {
      spawnProcess = (command, args, options = {}) => spawn(command, args, {
        ...options,
        ...groupLeadership,
        ...(needsEnvironment ? {
          env: {
            ...process.env, ...environment,
            ...(credentialValue ? { [credentialEnvironment]: credentialValue } : {}),
          },
        } : {}),
      })
    }

    // The reservation is taken here, in the same synchronous step as the launch: from the moment this
    // await yields, another connect can be handled, and it must find the establishment already
    // claimed rather than an empty `connection`.
    const reservation = reserveOpening()
    let opened
    try {
      opened = await openAcpConnection({
        harness,
        launch: { command: selectedLaunch.command, args: selectedLaunch.args },
        directory: request.directory ?? process.cwd(),
        spawnProcess,
        redact: safeText,
      })
      // Claimed before anything else can fail or be assigned: from here there is a real Harness
      // process whose release this entry is responsible for, whether or not the setup below succeeds.
      owned.add(opened)
      connection = opened
      opened.onFrame((_message, line) => {
        if (line === undefined) emit(_message)
        else process.stdout.write(`${line}\n`)
      })
      opened.onStderr((line) => emit({ event: "stderr", data: { line }, connectionId: opened.connectionId }))
      opened.onMalformed((message) => {
        emit({ event: "transport_malformed", data: { message }, connectionId: opened.connectionId })
      })
      opened.onEnd((end) => {
        // Reported as it happened: no process is claimed to be alive after its exit, and
        // no `cancelled`/`refused` outcome is invented for requests still in flight.
        emit({ event: "transport_end", data: end, connectionId: opened.connectionId, harness })
      })
      return {
        connectionId: opened.connectionId,
        harness,
        transport: opened.transport,
        // What was actually launched, next to what discovery derived for this brand.
        launch: { ...opened.launch, source: selectedLaunch.source,
          ...(selectedLaunch.version ? { version: selectedLaunch.version } : {}) },
        discovered: harnessLaunchContext(harness),
        state: opened.status(),
        provenance: { commit: source.commit, ref: source.ref },
      }
    } finally {
      reservation.done()
    }
  }

  async function handle(request) {
    const { op, id } = request
    if (op === "harnesses") {
      return {
        provenance: { commit: source.commit, ref: source.ref },
        ...launchDiscovery(),
        transport: connection?.transport ?? null,
      }
    }
    if (op === "connect") return connect(request)
    if (op === "status") {
      if (!connection) {
        if (opening) throw new Refused("ACP_CONNECT_IN_PROGRESS")
        throw new Refused("ACP_NOT_CONNECTED")
      }
      return connection.status()
    }
    if (op === "close") {
      // A close that arrives while an establishment is in flight waits for it and releases what it
      // produced. The alternative — refusing because there is no connection yet — would be answerable
      // only while a freshly spawned Harness stayed owned by nobody, and this entry's last
      // responsibility is that it never leaves one running.
      await settleOpening()
      if (!connection && !owned.size) throw new Refused("ACP_NOT_CONNECTED")
      return releaseOwned()
    }
    throw new Refused("UNKNOWN_OP", op)
  }

  const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity })
  for await (const line of rl) {
    const trimmed = line.trim()
    if (!trimmed) continue
    let message
    try {
      message = JSON.parse(trimmed)
    } catch {
      fail({ code: "ENVELOPE_MALFORMED" })
      continue
    }
    if (message === null || typeof message !== "object" || Array.isArray(message)) {
      fail({ code: "ENVELOPE_MALFORMED" })
      continue
    }
    if (isControlRequest(message)) {
      // Control and transport share this stream without a wrapper, so the one ordering rule is that
      // a control op never waits for the transport: `close` must still be answerable after the
      // Harness has died, and a caller may ask for `status` while a turn is open.
      void Promise.resolve().then(() => handle(message)).then(
        (result) => emit({ id: message.id ?? null, ok: true, result }),
        (error) => refusedError(error, message.id),
      )
      continue
    }
    // Not a control op: an ACP frame for the Harness, forwarded as written. No id is minted, no
    // field is added, and a frame nobody answers stays unanswered — the entry has no branch that
    // writes a result or a refusal on the Harness's behalf.
    if (!connection) {
      emit({ id: message.id ?? null, ok: false, error: { code: "ACP_NOT_CONNECTED", message: "no connection; send op:\"connect\" first" } })
      continue
    }
    try {
      connection.writeLine(trimmed)
    } catch (error) {
      emit({
        id: message.id ?? null,
        ok: false,
        error: { code: "ACP_CHANNEL_DEAD", message: safeText(error?.message ?? error, 500) },
      })
    }
  }
  // The host hung up. Release every process this entry owns before leaving, so an exiting caller
  // cannot strand a Harness — which includes an establishment that is still in flight when the host
  // stops talking, because its process appears a moment after the decision to exit is made. A release
  // the OS will not confirm is reported with its pid rather than called `released`: this process has
  // no stronger signal left than `SIGKILL`, and leaving is the only move that does not hang the
  // caller forever.
  try {
    await settleOpening()
    if (connection || owned.size) {
      const report = await releaseOwned()
      if (!report.released) emit({ event: "process_release_unconfirmed", data: report })
    }
  } catch (error) {
    emit({ event: "process_release_unconfirmed", data: { message: safeText(error?.message ?? error, 500) } })
  }
  process.exit(0)
}

function fail({ code, message }) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: { code, message: message ?? code } })}\n`)
}

main().catch((error) => {
  fail({ code: "SIDECAR_FATAL", message: String(error?.stack ?? error).slice(0, 2000) })
  process.exit(1)
})
