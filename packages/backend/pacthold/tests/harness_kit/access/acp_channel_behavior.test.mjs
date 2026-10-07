/**
 * Convergence Phase 1 — behaviour baseline of the reused ACP channel.
 *
 * Everything asserted here is measured against the real client the plugin reuses
 * (`third_party/harness_remote/bridge/src/acp-client.js`), driven through the
 * same controlled-child seam `tests/harness_remote/snapshot_seams.test.mjs`
 * already uses. The frames are the ones a real adapter speaks — method names,
 * result shapes and `_meta`/`sessionUpdate` usage copied from
 * `tests/harness_remote/fake_acp_peer.mjs`, which itself mirrors a real ACP
 * adapter — so the channel is proven against the protocol instead of against a
 * protocol invented for this file.
 *
 * Each test states the counterexample that would make it fail: an assertion that
 * no change of behaviour could break is not a boundary, and would let a
 * "pass-through that executes anything" or a "resume that pretends to succeed"
 * through as green.
 */
import assert from "node:assert/strict"
import { EventEmitter } from "node:events"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import test from "node:test"

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
const bridgeSrc = path.join(pluginRoot, "third_party", "harness_remote", "bridge", "src")
const { AcpClient } = await import(`${pathToFileURL(path.join(bridgeSrc, "acp-client.js")).href}`)

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** A controlled adapter process: stdio in-process, so no real Agent is involved. */
class Child extends EventEmitter {
  constructor(handler) {
    super()
    this.pid = 4811
    this.killed = false
    this.writes = []
    this.stdout = new EventEmitter()
    this.stderr = new EventEmitter()
    this.stdout.setEncoding = () => undefined
    this.stderr.setEncoding = () => undefined
    this.stdin = { writable: true, write: (line, callback) => {
      const message = JSON.parse(line)
      this.writes.push(message)
      handler(this, message)
      callback?.()
      return true
    } }
  }
  respond(message) { this.stdout.emit("data", `${JSON.stringify(message)}\n`) }
  exit(code = 1) { this.emit("exit", code, null) }
  kill() { this.killed = true; this.stdin.writable = false; return true }
}

function attach(handler) {
  const box = { child: null }
  const client = new AcpClient({ spawnProcess: () => {
    box.child = new Child(handler)
    return box.child
  } })
  return { client, box }
}

/** The handshake every real adapter answers before it accepts a session. */
function handshake(child, message, agentCapabilities = {}) {
  if (message.method !== "initialize") return false
  child.respond({ jsonrpc: "2.0", id: message.id, result: {
    agentInfo: { name: "controlled-harness", version: "test" },
    agentCapabilities,
    authMethods: [],
  } })
  return true
}

test("baseline: a reply resolves exactly the request its id belongs to, out of order", async () => {
  // Counterexample: resolving "the oldest pending request" instead of `id` would
  // hand second's result to first and second's error to nothing at all.
  const ids = new Map()
  const { client, box } = attach((child, message) => {
    handshake(child, message)
    if (message.method === "session/prompt") ids.set(message.params.tag, message.id)
  })
  await client.start()
  const first = client.request("session/prompt", { sessionId: "S", tag: "first", prompt: [] })
  const second = client.request("session/prompt", { sessionId: "S", tag: "second", prompt: [] })
  const secondRejection = assert.rejects(second, { message: "second failed: native cause" })
  box.child.respond({ jsonrpc: "2.0", id: ids.get("second"), error: {
    code: -32603, message: "second failed", data: { error: "native cause" },
  } })
  box.child.respond({ jsonrpc: "2.0", id: ids.get("first"), result: { stopReason: "end_turn" } })
  assert.deepEqual(await first, { stopReason: "end_turn" })
  await secondRejection
  client.close()
})

test("baseline: notifications reach the host verbatim, including unknown methods and custom fields", async () => {
  // Counterexample: any re-encoding or field filtering in the channel (a shrunken
  // business protocol) drops the unknown method or the custom key.
  const inbound = [
    { jsonrpc: "2.0", method: "session/update", params: {
      sessionId: "S", update: { sessionUpdate: "agent_message_chunk",
        content: { type: "text", text: "stream" }, _meta: { nativeSequence: 7 } },
    } },
    { jsonrpc: "2.0", method: "session/update", params: {
      sessionId: "S", update: { sessionUpdate: "vendor_native_progress", percent: 40 },
    } },
    { jsonrpc: "2.0", method: "agentbox/x_custom_notification", params: {
      sessionId: "S", payload: { nested: [1, 2, { three: true }] },
    } },
  ]
  const received = []
  const { client, box } = attach((child, message) => { handshake(child, message) })
  client.on("notification", (message) => received.push(message))
  await client.start()
  for (const frame of inbound) box.child.respond(frame)
  assert.deepEqual(received, inbound)
  client.close()
})

test("baseline: advertised capabilities are reported as advertised, unknown keys included", async () => {
  // Counterexample: a channel that whitelists known capability keys would drop
  // `agentbox_custom` and the product would report a real ability as absent.
  const advertised = {
    loadSession: true,
    promptCapabilities: { image: true, embeddedContext: false, agentbox_custom: { maxBytes: 4096 } },
    sessionCapabilities: { list: {} },
  }
  const { client } = attach((child, message) => { handshake(child, message, advertised) })
  await client.start()
  assert.deepEqual(client.promptCapabilities, advertised.promptCapabilities)
  assert.deepEqual(client.sessionCapabilities, { list: {} })
  client.close()
})

test("baseline: a reverse permission request is answered, an unknown reverse request is refused, and neither is executed", async () => {
  // Two counterexamples: (1) a channel that answered an unknown agent request by
  // running it, and (2) a "pass-through" that leaves it unanswered — the adapter
  // would stall until the prompt timeout either way.
  const answers = new Map()
  const executed = []
  const { client, box } = attach((child, message) => {
    handshake(child, message)
    if (message.method === "session/prompt") executed.push(message.params)
    if (message.id === 501 || message.id === 502) answers.set(message.id, message)
  })
  const agentRequests = []
  client.on("agent-request", (message) => agentRequests.push(message.method))
  await client.start()
  box.child.respond({ jsonrpc: "2.0", id: 501, method: "session/request_permission", params: {
    sessionId: "S", toolCall: { name: "shell", title: "Run a bounded command" },
    options: [{ kind: "allow_once", optionId: "grant-once" }, { kind: "reject_once", optionId: "reject-once" }],
  } })
  box.child.respond({ jsonrpc: "2.0", id: 502, method: "session/x_unrecognized", params: { sessionId: "S" } })
  const permission = answers.get(501)
  // ACP `RequestPermissionResponse.outcome` is the discriminated outcome object.
  assert.deepEqual(permission.result, { outcome: { outcome: "cancelled" } },
    "with no host consumer wired, the default must be an explicit refusal")
  const unsupported = answers.get(502)
  assert.equal(unsupported.error.code, -32_601)
  assert.match(unsupported.error.message, /does not implement session\/x_unrecognized/)
  assert.deepEqual(executed, [], "an unrecognized reverse request must never be executed")
  assert.deepEqual(agentRequests, ["session/request_permission", "session/x_unrecognized"],
    "the request is still observable to the host even though the channel refuses it")
  client.close()
})

test("baseline: cancel is a notification, not a response, and is not a disconnect", async () => {
  // Counterexample: sending cancel as a request (id) makes the adapter wait for an
  // answer that never comes; emitting `exit` on cancel conflates the two events.
  const { client, box } = attach((child, message) => {
    handshake(child, message)
    if (message.method === "session/prompt") box.held = message.id
  })
  const exits = []
  client.on("exit", () => exits.push(1))
  await client.start()
  const prompt = client.request("session/prompt", { sessionId: "S", prompt: [] })
  await sleep(0)
  client.notify("session/cancel", { sessionId: "S" })
  const cancel = box.child.writes.at(-1)
  assert.equal(cancel.method, "session/cancel")
  assert.ok(!("id" in cancel), "a cancel with an id would make the adapter expect a reply")
  box.child.respond({ jsonrpc: "2.0", id: box.held, result: { stopReason: "cancelled" } })
  assert.deepEqual(await prompt, { stopReason: "cancelled" })
  assert.deepEqual(exits, [], "a cancel must not look like a disconnect")
  client.close()
})

test("baseline: a disconnect is not a cancel — the in-flight request is rejected with the exit cause", async () => {
  // Counterexample: reporting `stopReason: "cancelled"` (or `end_turn`) after the
  // child died would claim a terminal statement the harness never sent.
  const { client, box } = attach((child, message) => {
    handshake(child, message)
    if (message.method === "session/prompt") box.held = message.id
  })
  const exits = []
  client.on("exit", (error) => exits.push(String(error.message)))
  await client.start()
  childStderr(box)
  const prompt = client.request("session/prompt", { sessionId: "S", prompt: [] })
  await sleep(0)
  box.child.stderr.emit("data", "controlled harness: fatal, cannot continue\n")
  box.child.exit(7)
  await assert.rejects(prompt, /ACP adapter exited \(7\): controlled harness: fatal, cannot continue/)
  assert.equal(exits.length, 1)
  client.close()
})

test("baseline: close() releases only this connection's child and its own pending work", async () => {
  // Counterexample: a cleanup that kills the other client's child, or that leaves
  // this client's request pending forever after close.
  const made = []
  function clientFor(handler) {
    const client = new AcpClient({ spawnProcess: () => {
      const child = new Child(handler)
      made.push(child)
      return child
    } })
    return client
  }
  const held = new Map()
  const one = clientFor((child, message) => {
    handshake(child, message)
    if (message.method === "session/prompt") held.set("one", message.id)
  })
  const two = clientFor((child, message) => {
    handshake(child, message)
    if (message.method === "session/prompt") held.set("two", message.id)
  })
  await one.start()
  await two.start()
  const mine = one.request("session/prompt", { sessionId: "S", prompt: [] })
  const theirs = two.request("session/prompt", { sessionId: "S", prompt: [] })
  await sleep(0)
  one.close()
  await assert.rejects(mine, { message: "ACP adapter closed" })
  assert.equal(made[0].killed, true, "this connection's child must go away")
  assert.equal(made[1].killed, false, "closing one connection may not touch another's")
  boxRespond(made[1], held.get("two"), { stopReason: "end_turn" })
  assert.deepEqual(await theirs, { stopReason: "end_turn" })
  two.close()
})

test("baseline: the prompt watchdog is per session — one live session does not keep another alive", async () => {
  // Counterexample: a watchdog keyed only on "some session/prompt is pending"
  // lets a wedged session ride another session's traffic forever, so a stuck
  // turn is never reported.
  let child
  const prompts = new Map()
  const client = new AcpClient({ spawnProcess: () => {
    child = new Child((target, message) => {
      handshake(target, message)
      if (message.method === "session/prompt") prompts.set(message.params.sessionId, message.id)
    })
    return child
  } })
  await client.start()
  const live = client.request("session/prompt", { sessionId: "ALIVE", prompt: [] }, 200)
  const wedged = client.request("session/prompt", { sessionId: "WEDGED", prompt: [] }, 200)
  await sleep(0)
  const keepAlive = setInterval(() => child.respond({ jsonrpc: "2.0", method: "session/update", params: {
    sessionId: "ALIVE", update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "still going" } },
  } }), 60)
  await sleep(140)
  child.respond({ jsonrpc: "2.0", id: prompts.get("ALIVE"), result: { stopReason: "end_turn" } })
  assert.deepEqual(await live, { stopReason: "end_turn" }, "the busy session keeps its turn")
  await assert.rejects(wedged, /ACP adapter request timed out: session\/prompt/)
  clearInterval(keepAlive)
  client.close()
})

/**
 * Records anything the process reports as an async failure while a test runs.
 *
 * This is the self-proof the reviewer asked for: "the fixture receives a response
 * correctly" has to mean *and finishes doing it*, because a channel that resolves
 * the caller while leaving a rejected promise behind looks healthy until the next
 * request inherits the wreckage. `settleAndUninstall()` waits past the last
 * assertion so a rejection queued by the code under test is observed before the
 * listeners come off, and checks that it leaked no listener of its own.
 */
class AsyncFailureRecorder {
  constructor() {
    this.seen = []
    this.onRejection = (reason) => this.seen.push(`unhandledRejection: ${reason?.message ?? String(reason)}`)
    this.onException = (error) => this.seen.push(`uncaughtException: ${error.message}`)
  }
  install() {
    this.before = process.listenerCount("unhandledRejection")
    process.on("unhandledRejection", this.onRejection)
    process.on("uncaughtException", this.onException)
    return this
  }
  async settleAndUninstall() {
    await sleep(30)
    process.off("unhandledRejection", this.onRejection)
    process.off("uncaughtException", this.onException)
    assert.equal(process.listenerCount("unhandledRejection"), this.before, "the recorder must not leak a listener")
    return this.seen
  }
}

test("fixture self-proof: the async-failure recorder notices a failure and uninstalls itself", async () => {
  // The recorder is itself a fixture, so it gets the same treatment as the code it
  // watches: called directly, it must record; uninstalled, it must leave no listener
  // behind for the rest of the suite.
  const recorder = new AsyncFailureRecorder().install()
  recorder.onRejection(new Error("planted"))
  recorder.onException(new Error("planted"))
  assert.deepEqual(recorder.seen, ["unhandledRejection: planted", "uncaughtException: planted"])
  assert.deepEqual(await recorder.settleAndUninstall(), recorder.seen)
})

test("fixture self-proof: a success reply resolves, is recorded on the wire, and leaves nothing pending", async () => {
  const recorder = new AsyncFailureRecorder().install()
  const held = []
  const { client, box } = attach((child, message) => {
    handshake(child, message)
    if (message.method === "session/prompt") held.push(message)
  })
  await client.start()
  const prompt = client.request("session/prompt", { sessionId: "S", prompt: [{ type: "text", text: "hi" }] })
  await sleep(0)
  box.child.respond({ jsonrpc: "2.0", id: held[0].id, result: { stopReason: "end_turn", usage: { totalTokens: 7 } } })
  assert.deepEqual(await prompt, { stopReason: "end_turn", usage: { totalTokens: 7 } })
  assert.equal(box.child.writes.filter((frame) => frame.method === "session/prompt").length, 1,
    "the request went out exactly once, so a second reply has nothing to resolve")
  assert.deepEqual(await recorder.settleAndUninstall(), [], "a clean success must not leave an async failure behind")
  client.close()
})

test("fixture self-proof: an error-only reply rejects with its cause, and leaves nothing pending", async () => {
  // Counterexample this proves absent: a channel that resolves `undefined` on an
  // error reply, or that rejects the caller and then re-rejects into the void.
  const recorder = new AsyncFailureRecorder().install()
  const held = []
  const { client, box } = attach((child, message) => {
    handshake(child, message)
    if (message.method === "session/prompt") held.push(message)
  })
  await client.start()
  const prompt = client.request("session/prompt", { sessionId: "S", prompt: [] })
  await sleep(0)
  box.child.respond({ jsonrpc: "2.0", id: held[0].id, error: {
    code: -32_001, message: "Internal error", data: { error: "the Agent refused" },
  } })
  const failure = await prompt.then(() => null, (error) => error)
  assert.ok(failure, "an error-only reply must not look like a success")
  assert.match(failure.message, /Internal error: the Agent refused/)
  assert.deepEqual(await recorder.settleAndUninstall(), [], "the rejection was consumed, not left floating")
  client.close()
})

function childStderr(box) {
  assert.ok(box.child, "the adapter process must be attached before stderr is written")
}

function boxRespond(child, id, result) {
  child.respond({ jsonrpc: "2.0", id, result })
}
