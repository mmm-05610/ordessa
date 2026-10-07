/**
 * Shared harness for tests that drive the plugin's real access entry as a child process.
 *
 * `access-entry.mjs` is the one production entry, and every test in this directory that
 * speaks to a Harness goes through it: `acp_transport_behavior.test.mjs` pins the entry's
 * own guarantees (isolation, launch validation, ids, process release) and
 * `acp_passthrough_target.test.mjs` pins the transport guarantees (T1-T10). Neither uses
 * a `register`/`start`/`create`/`prompt` envelope — those ops are retired with the old
 * chain, see `REMOVALS.md` and `tests/RETIRED.md`.
 *
 * Everything is offline: temp HOME, temp project directory, a controlled ACP harness
 * process, and fake credentials only. No real Agent, no model request, no credential read,
 * no existing service started or stopped.
 */
import { mkdtemp, readFile, rm } from "node:fs/promises"
import { readdirSync, readFileSync, readlinkSync } from "node:fs"
import { spawn } from "node:child_process"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { FIXTURE_CHILD_MARKER } from "./fixture_child_marker.mjs"

export const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
export const entry = path.join(pluginRoot, "runtime", "access-entry.mjs")
export const controlledHarness = path.join(pluginRoot, "tests", "access", "controlled_harness.mjs")

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export class Sidecar {
  constructor(extraEnv = {}, { controlledPeer = true } = {}) {
    this.record = null
    this.#extraEnv = extraEnv
    this.controlledPeer = controlledPeer
  }

  #extraEnv

  /** Explicit native entry: no isolation marker, the user's own Agent environment. */
  async start({ home, cwd }) {
    this.home = home
    this.cwd = cwd
    const state = await mkdtemp(path.join(tmpdir(), "agentbox-conv-state-"))
    this.state = state
    this.record = path.join(state, "harness-record.jsonl")
    const env = {
      ...process.env, HOME: home, XDG_CONFIG_HOME: "", XDG_CACHE_HOME: "", XDG_DATA_HOME: "",
      AGENTBOX_FIXTURE_RECORD: this.record, ...this.#extraEnv,
    }
    if (this.controlledPeer) env.AGENTBOX_ACCESS_TEST_MODE = "controlled-peer-v1"
    delete env.AGENTBOX_SIDECAR_ISOLATED
    this.process = spawn(process.execPath,
      this.controlledPeer ? [entry, "--native", "--controlled-test-peer"] : [entry, "--native"],
      { env, cwd, stdio: ["pipe", "pipe", "pipe"] })
    this.events = []
    this.responses = []
    // Every line in arrival order, undivided. `events`/`responses` sort by what this
    // plugin's own envelope calls a message, which is exactly the question a transport
    // test must not beg: a frame relayed verbatim from the Agent is neither an "event"
    // nor an envelope "response", and reading it only through those two buckets would
    // hide that. `frames` is the raw stream.
    this.frames = []
    this.buffer = ""
    this.nextID = 1
    this.process.stdout.setEncoding("utf8")
    this.process.stdout.on("data", (chunk) => {
      this.buffer += chunk
      let index
      while ((index = this.buffer.indexOf("\n")) >= 0) {
        const line = this.buffer.slice(0, index).trim()
        this.buffer = this.buffer.slice(index + 1)
        if (!line) continue
        const message = JSON.parse(line)
        this.frames.push(message)
        if (message.event) this.events.push(message)
        else this.responses.push(message)
      }
    })
    this.process.stderr.setEncoding("utf8")
    this.process.stderr.on("data", (chunk) => { this.stderrText = (this.stderrText ?? "") + chunk })
  }

  request(payload) {
    const id = this.nextID++
    this.process.stdin.write(`${JSON.stringify({ ...payload, id })}\n`)
    const startedAt = Date.now()
    return new Promise((resolve, reject) => {
      const poll = setInterval(() => {
        const match = this.responses.find((item) => item.id === id)
        if (match) { clearInterval(poll); resolve(match); return }
        if (Date.now() - startedAt > 15000) {
          clearInterval(poll)
          reject(new Error(`sidecar timeout for op ${payload.op}`))
        }
      }, 5)
    })
  }

  async waitForEvent(kind, timeoutMs = 8000) {
    const startedAt = Date.now()
    for (;;) {
      const match = this.events.find((item) => item.event === kind)
      if (match) return match
      if (Date.now() - startedAt > timeoutMs) throw new Error(`timeout waiting for the "${kind}" event`)
      await sleep(10)
    }
  }

  /** Send exactly this object on the control stream, with nothing added to it. */
  writeRaw(message) {
    this.process.stdin.write(`${JSON.stringify(message)}\n`)
  }

  /**
   * Wait for the entry process to leave, and report its exit code.
   *
   * A cleanup test needs the entry's own death as a fact the way a Harness's death is one: the
   * alternative is sleeping and hoping. Rejects rather than resolving when the process is still
   * running, because "it never exited" is the failure being tested for, not a result to inspect.
   */
  waitForExit(timeoutMs = 15_000) {
    if (this.process.exitCode !== null) return Promise.resolve(this.process.exitCode)
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.process.kill()
        reject(new Error("the entry process is still running; it did not finish its own cleanup"))
      }, timeoutMs)
      this.process.once("close", (code) => { clearTimeout(timer); resolve(code) })
    })
  }

  /** Hang up the control stream, exactly as a caller that is done with the entry does. */
  endStdin() {
    this.process.stdin.end()
  }
  /**
   * Wait for a line of the raw output stream to satisfy `match`.
   *
   * Deliberately independent of the envelope's `event`/`ok` vocabulary: a transport that
   * relays ACP frames hands back the Agent's own object, so the predicate is written
   * against ACP fields (`method`, `id`, `result`, `error`, `params`).
   */
  async waitForFrame(match, describe, timeoutMs = 8000) {
    const startedAt = Date.now()
    for (;;) {
      const found = this.frames.find(match)
      if (found) return found
      if (Date.now() - startedAt > timeoutMs) {
        throw new Error(`no line on the output stream was ${describe}; the stream carried ${JSON.stringify(
          this.frames.map((frame) => ({ id: frame.id ?? null, ok: frame.ok ?? null, method: frame.method ?? null,
            code: frame.error?.code ?? null })))}`)
      }
      await sleep(10)
    }
  }

  /** Every raw output line seen so far, in order. */
  streamFrames() {
    return this.frames
  }

  /**
   * The first ACP request frame for `method` that reached the host, unchanged.
   *
   * Deliberately name-agnostic: what is being asserted is that a real ACP frame
   * arrived with its own `method`, `id` and `params`, not which envelope event
   * carried it. A wrapper that renames the method, drops a field or answers the
   * request itself makes this find nothing.
   */
  async requestFrameFor(method, timeoutMs = 8000) {
    const startedAt = Date.now()
    for (;;) {
      for (const event of this.events) {
        const found = findJsonRpcRequest(event, method)
        if (found) return { frame: found, event }
      }
      if (Date.now() - startedAt > timeoutMs) {
        throw new Error(`no ACP request frame for "${method}" reached the host; events were ${JSON.stringify(this.events.map((e) => e.event))}`)
      }
      await sleep(10)
    }
  }

  /** Every ACP request frame for `method` that has reached the host so far. */
  requestFramesFor(method) {
    const found = []
    for (const event of this.events) collectJsonRpcRequests(event, method, found)
    return found
  }

  /**
   * The reply the entry sent for a frame this test wrote with `writeRaw()`.
   *
   * Matched on the id the test chose, because that is the only correlation an ACP
   * pass-through may not break.
   */
  async waitForResponse(id, timeoutMs = 8000) {
    const startedAt = Date.now()
    for (;;) {
      const match = this.responses.find((item) => item.id === id || item.requestId === id)
      if (match) return match
      if (Date.now() - startedAt > timeoutMs) {
        throw new Error(`no reply for the frame with id ${JSON.stringify(id)}; replies were ${JSON.stringify(
          this.responses.map((item) => item.id))}`)
      }
      await sleep(10)
    }
  }

  /** Rows the harness itself wrote, optionally filtered by event name. */
  async notes(event) {
    const startedAt = Date.now()
    for (;;) {
      let text = ""
      try { text = await readFile(this.record, "utf8") } catch { /* not written yet */ }
      const rows = text.split("\n").filter(Boolean).map((line) => JSON.parse(line))
      const found = event ? rows.filter((row) => row.event === event) : rows
      if (found.length) return found
      if (Date.now() - startedAt > 8000) {
        throw new Error(`no ${event ?? "any"} note; the harness recorded ${JSON.stringify(rows.map((r) => r.event))}`)
      }
      await sleep(10)
    }
  }

  /** Every row, without waiting: a target test needs to see what did arrive. */
  async allNotes() {
    try {
      return (await readFile(this.record, "utf8")).split("\n").filter(Boolean).map((line) => JSON.parse(line))
    } catch { return [] }
  }

  /**
   * Establish the transport and nothing else — the production entry's own `connect` op.
   *
   * Deliberately asserts nothing: an entry that refuses to connect fails later, on the
   * substantive claim, rather than here on a name.
   */
  async connect(overrides = {}) {
    return this.request({
      op: "connect",
      harness: overrides.harness ?? "codex",
      launch: { command: process.execPath, args: [controlledHarness], ...(overrides.launch ?? {}) },
      directory: overrides.directory ?? this.cwd,
      ...overrides.connect,
    })
  }

  async closeProcess() {
    this.process.kill()
    await sleep(50)
  }
}

export const alive = (pid) => { try { process.kill(pid, 0); return true } catch { return false } }

/**
 * The process ids running `controlledHarness` with `cwd` as their working directory.
 *
 * A cleanup test has to ask the OS something a pipe cannot answer: is a process still running that
 * nobody owns any more? Its pid may never have reached this test at all — a Harness killed while it
 * was still booting never gets to write its own record — so the two facts that do identify it, the
 * command line it was launched with and the directory it was launched in, are read back from
 * `/proc`. Matching the directory is what keeps the answer about *this* run: sibling test files
 * launch the same fixture concurrently. Throws rather than returning nothing where `/proc` is not
 * there to read, because "unmeasurable" must not be reportable as "clean".
 */
export function harnessPidsIn(cwd) {
  const found = []
  for (const entry of readdirSync("/proc")) {
    if (!/^\d+$/.test(entry)) continue
    let commandLine
    try { commandLine = readFileSync(`/proc/${entry}/cmdline`, "utf8") } catch { continue }
    if (!commandLine.includes(controlledHarness)) continue
    let directory
    try { directory = readlinkSync(`/proc/${entry}/cwd`) } catch { continue }
    if (directory === cwd) found.push(Number(entry))
  }
  return found
}

/**
 * The fixture-child processes launched from `cwd`, read from the process table.
 *
 * The marker is in the child's own argv, and the directory is the one it inherited, so a test can
 * ask "is anything from this launch still running" without taking the fixture's word for it — which
 * is the only way a release that fires before the child ever records anything can be measured at all.
 */
export function fixtureChildrenIn(cwd) {
  const found = []
  for (const entry of readdirSync("/proc")) {
    if (!/^\d+$/.test(entry)) continue
    let commandLine
    try { commandLine = readFileSync(`/proc/${entry}/cmdline`, "utf8") } catch { continue }
    if (!commandLine.includes(FIXTURE_CHILD_MARKER)) continue
    let directory
    try { directory = readlinkSync(`/proc/${entry}/cwd`) } catch { continue }
    if (directory === cwd) found.push(Number(entry))
  }
  return found.sort((one, two) => one - two)
}

/**
 * Collect JSON-RPC *request* frames (a `method` plus an `id`) buried anywhere in a
 * message, without assuming which field the wrapper chose to put them in.
 *
 * This is what lets a target test assert "the Agent's frame reached the host"
 * instead of "the host received the event name this repository invented".
 */
function collectJsonRpcRequests(node, method, found, depth = 0) {
  if (node === null || typeof node !== "object" || depth > 6) return
  if (!Array.isArray(node)) {
    if (node.method === method && node.id !== undefined) found.push(node)
    for (const value of Object.values(node)) collectJsonRpcRequests(value, method, found, depth + 1)
    return
  }
  for (const item of node) collectJsonRpcRequests(item, method, found, depth + 1)
}

function findJsonRpcRequest(node, method) {
  const found = []
  collectJsonRpcRequests(node, method, found)
  return found[0] ?? null
}

export async function waitGone(pid, limitMs = 5000) {
  const startedAt = Date.now()
  while (alive(pid)) {
    if (Date.now() - startedAt > limitMs) return false
    await sleep(20)
  }
  return true
}

/**
 * Wait until the process table stops answering for every one of these pids, and report the ones that
 * did not. `released: true` only means something if a test can independently reach the same verdict,
 * and a reparented orphan takes an unknown moment to stop answering `kill(pid,0)`.
 */
export async function waitAllGone(pids, limitMs = 5_000) {
  const startedAt = Date.now()
  const stillLiving = () => pids.filter((pid) => alive(pid))
  while (stillLiving().length) {
    if (Date.now() - startedAt > limitMs) return stillLiving()
    await sleep(10)
  }
  return []
}

export async function withSidecar(run, extraEnv = {}, options = {}) {
  const home = await mkdtemp(path.join(tmpdir(), "agentbox-conv-home-"))
  const project = await mkdtemp(path.join(tmpdir(), "agentbox-conv-project-"))
  const sidecar = new Sidecar(extraEnv, options)
  await sidecar.start({ home, cwd: project })
  try {
    return await run({ sidecar, home, project })
  } finally {
    await sidecar.closeProcess()
    await sleep(50)
    // A red tree test must not leak the children it started: whatever is still running under this
    // temp project directory belongs to this run, so it is stopped here rather than left for the
    // next reader of `/proc` to mistake for a live case.
    for (const pid of [...harnessPidsIn(project), ...fixtureChildrenIn(project)]) {
      try { process.kill(pid, "SIGKILL") } catch { /* already gone */ }
    }
    await sleep(50)
    for (const directory of [home, project, sidecar.state]) {
      await rm(directory, { recursive: true, force: true }).catch(() => undefined)
    }
  }
}
