/**
 * Controlled ACP harness for the convergence tests.
 *
 * It speaks the same wire as `tests/harness_remote/fake_acp_peer.mjs` (ACP
 * method names and result shapes copied from there, i.e. from a real adapter's
 * contract) and adds only what the convergence boundaries need: a switch to
 * advertise fewer capabilities, a switch to refuse `session/load`/`session/resume`
 * exactly as an adapter that has no resume support does, and a record file so a
 * test can read what the **harness side** received instead of trusting the
 * bridge's account of it.
 *
 * Nothing here is a protocol invented for this test: every field is one an ACP
 * adapter really sends or really answers with.
 */
import readline from "node:readline"
import { appendFileSync, readdirSync } from "node:fs"
import { spawn } from "node:child_process"
import { FIXTURE_CHILD_MARKER as CHILD_MARKER } from "./fixture_child_marker.mjs"

const record = process.env.AGENTBOX_FIXTURE_RECORD ?? null
const caps = JSON.parse(process.env.AGENTBOX_FIXTURE_CAPABILITIES ?? "null") ?? {
  loadSession: false,
  promptCapabilities: { image: true, agentbox_custom: { maxBytes: 4096 } },
  sessionCapabilities: {},
}
const refuses = new Set((process.env.AGENTBOX_FIXTURE_REFUSES ?? "").split(",").map((v) => v.trim()).filter(Boolean))
const permissionOptions = JSON.parse(process.env.AGENTBOX_FIXTURE_PERMISSION_OPTIONS ?? "null") ?? [
  { kind: "allow_once", optionId: "grant-once" },
  { kind: "allow_always", optionId: "grant-always" },
  { kind: "reject_once", optionId: "reject-once" },
]
const ghost = process.env.AGENTBOX_FIXTURE_GHOST_SESSION ?? null
// A real Agent is allowed to ignore a graceful signal, and a relay that reported "released" on the
// strength of having *sent* one would be wrong exactly there. `ignore` traps `SIGTERM` and stays
// alive, so the release path has to escalate to be able to report a death at all; the default is
// Node's own behaviour (terminate), which every other case in this directory relies on.
const sigtermBehaviour = process.env.AGENTBOX_FIXTURE_SIGTERM ?? "default"
// `SIGTERM` handling is not the only way an Agent can outlive the pipe it was reached over: one with
// a reason to keep serving does not quit because its stdin closed. `HOLD_OPEN` gives the cleanup
// tests that process — an Agent that stays up until something *signals* it, so a relay that merely
// exits, or merely hangs up, demonstrably leaves it behind.
const holdOpen = process.env.AGENTBOX_FIXTURE_HOLD_OPEN === "1"

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity })
const send = (message) => process.stdout.write(`${JSON.stringify(message)}\n`)
function note(event, detail = {}) {
  if (record) appendFileSync(record, `${JSON.stringify({ event, pid: process.pid, ...detail })}\n`)
}

let homeEntries = null
try { homeEntries = process.env.HOME ? readdirSync(process.env.HOME) : null } catch { homeEntries = ["<unreadable>"] }
note("exec", {
  cwd: process.cwd(),
  argv: process.argv.slice(2),
  home: process.env.HOME ?? null,
  homeEntries,
  // Evidence that no installer or toolchain context was injected: the keys, never the values.
  // `npm_config_*` is what an `npm install`/`npx` launch leaves behind and `NODE_OPTIONS` is how a
  // launcher would quietly change how this process runs; both are names, so no secret is recorded.
  npmConfigKeys: Object.keys(process.env).filter((key) => /^npm_config/i.test(key)).sort(),
  nodeOptions: process.env.NODE_OPTIONS ?? null,
  isolationMarker: process.env.AGENTBOX_SIDECAR_ISOLATED ?? null,
  marker: process.env.AGENTBOX_FIXTURE_MARKER ?? null,
  sigterm: sigtermBehaviour,
  holdOpen,
})

if (holdOpen) {
  // A ref'd timer is enough: the readline loop below ends with stdin, and this process then has no
  // reason to leave. Nothing else changes, so a signal is the only way it goes.
  setInterval(() => undefined, 1_000)
}

/**
 * Real children, so that "the tree this launch started" is something a test can count.
 *
 * An ACP bridge in production is a launcher: `npx … codex-acp` starts the Agent as its own child and
 * forwards to it, and killing the bridge alone leaves that child serving. These children therefore
 * inherit this process's group (the ordinary shape, reached by one group signal) or move out of it
 * (the shape that has to be handled one process at a time), and both outlive a parent that is
 * signalled first. Each carries a marker in its own argv so a test can find it in the process table
 * without trusting anything this fixture writes.
 */
const childCount = Number(process.env.AGENTBOX_FIXTURE_CHILDREN ?? "0")
const childEscapes = process.env.AGENTBOX_FIXTURE_CHILD_ESCAPES === "1"
const parentExitsAfterMs = Number(process.env.AGENTBOX_FIXTURE_PARENT_EXITS_AFTER_MS ?? "0")
/**
 * A child of *this* process that starts a child of its own, one level deeper and out of the group.
 *
 * The shape a launcher really produces — `npx` runs a wrapper that runs the Agent, and the Agent
 * forks a worker. It is also the shape that separates "I collected this process" from "I looked
 * inside it": the middle process stays in the launched group and is therefore found by the group
 * rule, while the last one left the group and is reachable only by continuing the parent-link walk
 * *through* a process already known to be a member. A tree walk that stops at what it has already
 * filed never sees it.
 */
const grandchildCount = Number(process.env.AGENTBOX_FIXTURE_GRANDCHILDREN ?? "0")
const childCode = `${grandchildCount ? `
{
  const { spawn } = require("node:child_process")
  for (let index = 0; index < ${grandchildCount}; index += 1) {
    spawn(process.execPath, ["-e", "setInterval(() => undefined, 1000)", ${JSON.stringify(CHILD_MARKER)}],
      { detached: true, stdio: "ignore" }).unref()
  }
}
` : ""}
setInterval(() => undefined, 1000)`
const childPids = []
for (let index = 0; index < childCount; index += 1) {
  const child = spawn(process.execPath, ["-e", childCode, CHILD_MARKER], {
    stdio: "ignore",
    // `detached` is the escape: a new group, so `kill(-rootPid)` cannot reach it and only a signal
    // aimed at its own pid can.
    ...(childEscapes ? { detached: true } : {}),
  })
  if (childEscapes) child.unref()
  childPids.push(child.pid)
}
// Only when a tree was actually started: a fixture that records a frame the tests never asked for
// would change the one record (`receivedByAgent`) that pins what reaches the Agent on the wire.
if (childPids.length) {
  note("children", { pids: childPids, escaped: childEscapes, grandchildren: grandchildCount, group: process.pid })
}
if (parentExitsAfterMs) setTimeout(() => process.exit(0), parentExitsAfterMs)

if (sigtermBehaviour === "ignore") {
  // The process keeps running and keeps its pipes open, which is the whole counterexample: a release
  // that only delivered `SIGTERM` would look exactly as successful from here as one that worked.
  process.on("SIGTERM", () => note("sigterm-ignored"))
}

const MODEL_OPTION = {
  id: "model", name: "Model", category: "model",
  currentValue: "controlled-model",
  // The candidate list is configurable because a model-id boundary test needs the
  // Agent to accept *both* spellings: then the only difference left is which value
  // the bridge actually put on the wire.
  options: (process.env.AGENTBOX_FIXTURE_MODEL_VALUES ?? "controlled-model")
    .split(",").map((value) => ({ value: value.trim(), name: value.trim() })),
}

let created = 0
const turns = new Map()
const heldPrompts = new Map()
const reverseRequests = new Map()
const outstanding = new Map()
const known = new Map()

let nextRequestId = 700

/** Raise one client-bound ACP request on behalf of a held prompt turn. */
function raise(promptId, sessionId, method, params) {
  const id = nextRequestId++
  reverseRequests.set(id, { promptId, sessionId, method })
  outstanding.set(promptId, (outstanding.get(promptId) ?? new Set()).add(id))
  send({ jsonrpc: "2.0", id, method, params })
  note("reverse-sent", { id, method, params })
  return id
}

/** End the prompt turn once every request it raised has been answered. */
function settleIfDone(promptId, detail) {
  const pending = outstanding.get(promptId)
  if (pending && pending.size) return
  outstanding.delete(promptId)
  heldPrompts.delete(promptId)
  note("prompt-settled", { promptId, ...detail })
  send({ jsonrpc: "2.0", id: promptId, result: { stopReason: "end_turn" } })
}

function refused(message) {
  send({ jsonrpc: "2.0", id: message.id, error: {
    code: -32_601, message: `method not found: ${message.method}`,
  } })
}

for await (const line of rl) {
  if (!line.trim()) continue
  const message = JSON.parse(line)
  const { id, method, params } = message

  // A reply to a request this harness raised. Both shapes a host can send back are
  // handled: a `result`, and an `error` with no result. The harness records what it
  // received verbatim and ends the turn it was holding, so a test can tell
  // "answered with an error" apart from "never answered" — the second would leave
  // the turn hanging, which is the failure the fixture must not be able to fake.
  if (id !== undefined && method === undefined) {
    const waiting = reverseRequests.get(id)
    note("reverse-reply", {
      id, waiting: waiting?.method ?? null,
      // `outcome` is the ACP `RequestPermissionResult` field the permission tests read;
      // `result`/`error` are the whole frames, so an error-only answer is recorded too.
      outcome: message.result?.outcome ?? null,
      result: message.result ?? null, error: message.error ?? null,
    })
    if (!waiting) continue
    reverseRequests.delete(id)
    outstanding.get(waiting.promptId)?.delete(id)
    const text = message.error !== undefined
      ? `answer-error:${message.error.code}`
      : `answer-result:${JSON.stringify(message.result ?? null)}`
    send({ jsonrpc: "2.0", method: "session/update", params: {
      sessionId: waiting.sessionId,
      update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text } },
    } })
    settleIfDone(waiting.promptId, { promptId: waiting.promptId, settledAfter: "reverse-reply" })
    continue
  }

  if (method === "initialize") {
    note("initialize", { params })
    send({ jsonrpc: "2.0", id, result: {
      agentInfo: { name: "controlled-harness", version: "test" },
      agentCapabilities: caps,
      authMethods: [{ id: "none", name: "none" }],
    } })
  } else if (method === "authenticate") {
    note("authenticate", { params })
    send({ jsonrpc: "2.0", id, result: {} })
  } else if (method === "session/new") {
    created += 1
    const sessionId = `controlled-${process.pid}-${created}`
    known.set(sessionId, params?.cwd ?? null)
    note("session/new", { cwd: params?.cwd ?? null, sessionId })
    send({ jsonrpc: "2.0", id, result: { sessionId, configOptions: [MODEL_OPTION] } })
  } else if (method === "session/list") {
    const sessions = [...known.keys()].map((sessionId) => ({ sessionId, cwd: known.get(sessionId) ?? "/controlled" }))
    if (ghost) sessions.push({ sessionId: ghost, cwd: "/controlled" })
    note("session/list", { count: sessions.length })
    send({ jsonrpc: "2.0", id, result: { sessions } })
  } else if (method === "session/load" || method === "session/resume") {
    note(method, { sessionId: params?.sessionId ?? null })
    if (refuses.has(method)) { refused(message); continue }
    send({ jsonrpc: "2.0", id, result: { sessionId: params?.sessionId, configOptions: [MODEL_OPTION] } })
  } else if (method === "session/set_config_option") {
    // Recorded verbatim: whether a model id reached this Agent unchanged is a
    // boundary fact, and only the Agent's own account can prove it.
    note("set_config_option", { sessionId: params?.sessionId ?? null, configId: params?.configId ?? null, value: params?.value ?? null, meta: params?._meta ?? null })
    send({ jsonrpc: "2.0", id, result: { configOptions: [MODEL_OPTION] } })
  } else if (method === "session/prompt") {
    const sessionId = params.sessionId
    const turn = (turns.get(sessionId) ?? 0) + 1
    turns.set(sessionId, turn)
    const text = params.prompt.find((item) => item.type === "text")?.text ?? ""
    // `op` and friends are legal extension members of an ACP frame, so a relay that keyed its own
    // control plane on the name alone would eat such a frame here — the Agent would never see it.
    // Recording the top-level fields that arrived, by name and value, is what lets a test tell a
    // frame that passed through from one that never did.
    const extensionKeys = Object.keys(message).filter((key) => !["jsonrpc", "id", "method", "params"].includes(key)).sort()
    note("prompt", {
      sessionId, turn, text, cwd: process.cwd(),
      extensionKeys, extension: Object.fromEntries(extensionKeys.map((key) => [key, message[key]])),
    })
    const chunk = (value) => send({ jsonrpc: "2.0", method: "session/update", params: {
      sessionId, update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text: value } },
    } })
    if (text.includes("boom")) {
      send({ jsonrpc: "2.0", id, error: { code: -32_001, message: "Internal error",
        data: { error: "controlled harness refused the turn" } } })
    } else if (text.includes("ask-permission")) {
      heldPrompts.set(id, sessionId)
      // A real ACP client method, with the real params shape: `toolCall` and
      // `options`, so the answer is a `RequestPermissionResult`, not a fixture word.
      raise(id, sessionId, "session/request_permission", {
        sessionId, toolCall: { toolCallId: "call-1", name: "shell", title: "Run a bounded command" },
        options: permissionOptions,
      })
    } else if (text.includes("ask-file")) {
      heldPrompts.set(id, sessionId)
      raise(id, sessionId, "fs/read_text_file", { sessionId, path: params?.path ?? "notes.txt" })
    } else if (text.includes("ask-many")) {
      // Concurrency: N distinct client requests at once, all for the same held turn.
      heldPrompts.set(id, sessionId)
      const count = Number(process.env.AGENTBOX_FIXTURE_REVERSE_COUNT ?? 3)
      for (let index = 0; index < count; index += 1) {
        const fileMethod = index % 2 === 1
        raise(id, sessionId, fileMethod ? "fs/read_text_file" : "session/request_permission", fileMethod
          ? { sessionId, path: `notes-${index}.txt` }
          : { sessionId, toolCall: { toolCallId: `call-${index}`, name: "shell", title: `Command ${index}` },
              options: permissionOptions })
      }
    } else if (text.includes("hold")) {
      heldPrompts.set(id, sessionId)
    } else {
      chunk(`turn-${turn}`)
      send({ jsonrpc: "2.0", id, result: { stopReason: "end_turn" } })
    }
  } else if (method === "session/cancel") {
    note("cancel", { sessionId: params?.sessionId ?? null, hasId: id !== undefined })
    if (id !== undefined) heldPrompts.set(id, params?.sessionId)
    for (const [promptId, sessionId] of [...heldPrompts.entries()]) {
      if (params?.sessionId !== undefined && sessionId !== params.sessionId) continue
      heldPrompts.delete(promptId)
      note("prompt-settled", { promptId, sessionId, stopReason: "cancelled" })
      send({ jsonrpc: "2.0", id: promptId, result: { stopReason: "cancelled" } })
    }
  } else if (method === undefined && id === undefined) {
    note("unframed-message", { message })
  } else if (method !== undefined) {
    note("unknown-method", { method })
    if (refuses.has(method)) { refused(message); continue }
    send({ jsonrpc: "2.0", id, result: {} })
  }
}
