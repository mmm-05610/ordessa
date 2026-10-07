/**
 * Category: 接入 ACP / native access — the executable spec of the transport entry.
 *
 * These ten cases were written as TARGET tests: each one failed against the old chain and named
 * the file and line that made it fail. They are the spec now, and the `worker-entry.mjs` /
 * `acp-client.js` / `acp-service.js` citations in the comments below are kept **as measured
 * history** rather than rewritten — they are the evidence for why each assertion exists, and the
 * chain they describe is retired (`REMOVALS.md`, `tests/RETIRED.md`).
 *
 * WHY THIS FILE DOES NOT USE register → start → create → prompt
 * -------------------------------------------------------------
 * The first draft of this file did, and the reviewer's objection was accepted: putting a
 * complete ACP frame inside the old envelope still does not make an ACP channel, because the
 * envelope's own `start`/`create`/`prompt` ops are the plugin doing `initialize`, `session/new`
 * and `session/prompt` on the caller's behalf. A test that drives the system that way can only
 * ever prove the envelope still works. So every case here starts at the production entry —
 * **the plugin establishes the connection and hands over the transport** — and then the *test
 * itself* is the ACP client: it sends `initialize`, `session/new`, `session/prompt` and
 * everything else, and asserts on the frames the Agent really received.
 *
 * What is not negotiable, and what each test pins, is that establishing the connection transmits
 * **no ACP frame** (T1), and that the only ACP frames the Agent sees afterwards are the ones the
 * client sent.
 *
 * The entry's own guarantees — how it refuses a malformed launch context, what it isolates per
 * connection, which process it releases — are in `access_entry_behavior.test.mjs`. This file
 * asks only what the *transport* must never do.
 *
 * THE COUNTEREXAMPLE EACH NEGATIVE ASSERTION GUARDS AGAINST
 * ---------------------------------------------------------
 * A "pure channel" can pass a happy-path test in three dishonest ways, and each is refused
 * below by proving the channel is alive *first* (the client's own `initialize` is answered)
 * and only then asserting the absence:
 *   1. answering nothing because there is no channel at all → every negative case is preceded
 *      by a round trip on the same connection;
 *   2. a client-bound request that is *answered* by the plugin (the old `permissionMode`
 *     auto-select and the old `-32601`) → refused by T6/T9, which read the Agent's own record
 *      for a `reverse-reply` row;
 *   3. turning "the client has not answered yet" into a decision — `{outcome:"cancelled"}`, a
 *      timeout, or a refusal — → refused by T9, for two different brands, and by refusing the
 *      timeout knob itself. The previous draft asked for a *uniform refusal* here; that
 *      requirement is **withdrawn**, because a uniform refusal is still the plugin deciding.
 *
 * Method names and result shapes are the real ACP ones, read offline from the vendored adapter
 * bundle `packaging/codex/vendor/agentclientprotocol-codex-acp-1.1.14.tgz` (`dist/index.js`:
 * `AGENT_METHODS`, `CLIENT_METHODS`, `PROTOCOL_VERSION === 1`) and cross-checked against the
 * controlled harness, which answers exactly those. No wrapper name invented in this repository
 * appears anywhere below: `grep` for `reverse_request` / `reverse_response` returns nothing in
 * the run chain or the Server, and this file does not add it.
 */
import assert from "node:assert/strict"
import test from "node:test"
import { controlledHarness, withSidecar } from "./sidecar_harness.mjs"

/**
 * Establish the transport and nothing else. Deliberately asserts nothing: an absent entry must
 * fail later, on the substantive claim, rather than here on a name.
 */
async function establish(sidecar, { harness = "codex", launch = {}, connect = {} } = {}) {
  return sidecar.request({
    op: "connect", harness,
    launch: { command: process.execPath, args: [controlledHarness], ...launch },
    directory: sidecar.cwd, ...connect,
  })
}

let sequence = 0
const nextId = () => `client-${(sequence += 1)}`

/** Write one ACP request of the client's own and return it with its id. */
function send(sidecar, method, params) {
  const id = nextId()
  const frame = { jsonrpc: "2.0", id, method, params }
  sidecar.writeRaw(frame)
  return { id, frame }
}

const isReply = (id) => (frame) => frame.id === id && (frame.result !== undefined || frame.error !== undefined)

/** Send a request and wait for the reply that carries its id. */
async function call(sidecar, method, params) {
  const sent = send(sidecar, method, params)
  sent.reply = await sidecar.waitForFrame(isReply(sent.id), `the reply to "${method}" (${sent.id})`)
  return sent
}

/**
 * A channel proven alive on the Agent's own account, plus a session the client opened.
 *
 * This is the prelude every negative assertion needs: if the Agent answered `initialize`, then
 * "the Agent received no further frame" is a fact about the channel, not about a channel that
 * never came up.
 */
async function liveChannel(sidecar, { harness = "codex", connect = {}, clientCapabilities = {} } = {}) {
  await establish(sidecar, { harness, connect })
  const initialize = await call(sidecar, "initialize", {
    protocolVersion: 1, clientCapabilities, clientInfo: { name: "acp-target-client", version: "test" },
  })
  assert.equal(initialize.reply.error, undefined, JSON.stringify(initialize.reply))
  const created = await call(sidecar, "session/new", { cwd: sidecar.cwd, mcpServers: [] })
  assert.equal(created.reply.error, undefined, JSON.stringify(created.reply))
  return { initialize, sessionId: created.reply.result.sessionId }
}

/** The frames the Agent itself says it was sent, oldest first, excluding process start-up. */
async function receivedByAgent(sidecar) {
  return (await sidecar.allNotes()).filter((row) => row.event !== "exec")
}

// ---------------------------------------------------------------------------
// establishing
// ---------------------------------------------------------------------------

test("T1: establishing the connection sends no ACP frame — initialize/session/new/prompt are the client's", async () => {
  // Today `sidecar.py:1328` + `worker-entry.mjs` reach the Agent only through
  // `start` → `AcpClient.#start()` (`acp-client.js:173-194`), which sends `initialize` with the
  // bridge's own `clientInfo` and then picks and sends `authenticate` itself; `create` →
  // `AcpService.createSession()` sends `session/new`. There is no entry that spawns the Agent and
  // stops, because `#child` is assigned only inside `#start()` (`acp-client.js:136`).
  await withSidecar(async ({ sidecar }) => {
    const connected = await establish(sidecar)
    // The handshake the client performs below is the proof the process is up; if establishing had
    // been refused outright this await is what reports it, with the frame list attached.
    const initialize = await call(sidecar, "initialize", {
      protocolVersion: 1, clientCapabilities: {}, clientInfo: { name: "acp-target-client", version: "test" },
    })
    assert.equal(initialize.reply.error, undefined, JSON.stringify(initialize.reply))
    assert.deepEqual(initialize.reply.result.agentInfo, { name: "controlled-harness", version: "test" },
      "the Agent's own answer to the client's own initialize")

    const rows = await receivedByAgent(sidecar)
    assert.deepEqual(rows.map((row) => row.event), ["initialize"],
      "establishing must not send initialize, authenticate, session/new or session/prompt")
    assert.equal(rows[0].params.clientInfo.name, "acp-target-client",
      "the client identity on the wire is the client's, not a bridge default filled in by the plugin")

    // Establishing hands over a transport, not a session the plugin already made.
    assert.equal(connected.result?.sessionId, undefined, "no session may exist before the client asks for one")
    assert.equal(connected.result?.agentInfo, undefined,
      "no handshake result may be reported by a plugin that must not have done the handshake")
  })
})

test("T2: every frame the client sends reaches the Agent verbatim, including fields the plugin does not know", async () => {
  // The whole point of the client driving the handshake: what the Agent is *sent* is decided by
  // the client. A capability the plugin has never heard of must survive the trip, because
  // shrinking the declared capability set is the failure this round exists to remove.
  await withSidecar(async ({ sidecar }) => {
    const { initialize, sessionId } = await liveChannel(sidecar, {
      clientCapabilities: { fs: { readTextFile: true }, agentbox_unheard_of: { depth: 3 } },
    })
    const [record] = await sidecar.notes("initialize")
    assert.deepEqual(record.params.clientCapabilities, { fs: { readTextFile: true }, agentbox_unheard_of: { depth: 3 } },
      "client capabilities pass through without a whitelist")
    assert.equal(initialize.reply.result.agentCapabilities.loadSession, false)

    const [created] = await sidecar.notes("session/new")
    assert.equal(created.cwd, sidecar.cwd, "the cwd the client named is the cwd the Agent got")
    assert.equal(sessionId, created.sessionId, "the session id is the Agent's own, not one the plugin minted")

    const prompt = await call(sidecar, "session/prompt", {
      sessionId, prompt: [{ type: "text", text: "hello" }, { type: "agentbox_custom_block", agentbox_custom: { maxBytes: 4096 } }],
    })
    assert.deepEqual(prompt.reply.result, { stopReason: "end_turn" })
    const [turn] = await sidecar.notes("prompt")
    assert.equal(turn.turn, 1, "exactly one turn, the one the client asked for")
    assert.equal(turn.sessionId, sessionId)
  })
})

test("T3: an agent-bound method the client names reaches the Agent unchanged and the Agent's answer comes back as the Agent sent it", async () => {
  // `session/set_config_option` is in the adapter's `AGENT_METHODS` table. Today the host may only
  // say `create`/`open`/`prompt`/`abort`/`status`/`close`, and the model id inside `create` is
  // rewritten by `resolveNativeModel()` (`profile_extensions.mjs:239`) before it reaches the Agent
  // — which is how a product alias table ended up owning an ACP parameter.
  // Counterexample refused: the value or `_meta` being re-encoded on the way out.
  await withSidecar(async ({ sidecar }) => {
    const { sessionId } = await liveChannel(sidecar)
    const option = await call(sidecar, "session/set_config_option", {
      sessionId, configId: "model", value: "vendor-native/model-x", _meta: { reason: "user-picked" },
    })
    const [record] = await sidecar.notes("set_config_option")
    assert.equal(record.value, "vendor-native/model-x", "the id the client sent is what the Agent receives")
    assert.deepEqual(record.meta, { reason: "user-picked" },
      "an extension field the access layer does not understand still reaches the Agent")
    assert.equal(option.reply.error, undefined, JSON.stringify(option.reply))
    assert.equal(option.reply.result.configOptions[0].currentValue, "controlled-model",
      "the Agent's own response object is returned as the Agent sent it")
  })
})

test("T4: an error the Agent answers with reaches the client unchanged", async () => {
  // The same claim in the other direction: `-32601` and its message must not be rewritten into
  // this plugin's own error vocabulary on the way out. `session/fork` is a real agent-bound method
  // that the controlled harness refuses itself; the access layer has no business answering for it.
  await withSidecar(async ({ sidecar }) => {
    const { sessionId } = await liveChannel(sidecar)
    const failed = await call(sidecar, "session/fork", { sessionId })
    assert.equal(failed.reply.error.code, -32_601, JSON.stringify(failed.reply))
    assert.match(failed.reply.error.message, /method not found: session\/fork/,
      "the Agent's own wording, not a code this plugin chose for it")
  }, { AGENTBOX_FIXTURE_REFUSES: "session/fork" })
})

// ---------------------------------------------------------------------------
// Agent → client
// ---------------------------------------------------------------------------

test("T5: a client-bound request arrives as the Agent's own frame and the client's own reply is what the Agent receives", async () => {
  // Today `acp-client.js:316` does emit the frame verbatim on `agent-request`, and `runtime/*.mjs`
  // has no subscriber for it; what reaches the host instead is a `permission_request` event with
  // four keys of this plugin's own choosing and a minted `randomUUID()` in place of the Agent's id
  // (pinned by `sidecar_boundary_behavior` test 3), and the Agent's answer is then rebuilt as
  // `{outcome:"selected",optionId}` by the bridge (`:371-375`).
  await withSidecar(async ({ sidecar }) => {
    const { sessionId } = await liveChannel(sidecar)
    const prompt = send(sidecar, "session/prompt", { sessionId, prompt: [{ type: "text", text: "ask-permission" }] })

    const request = await sidecar.waitForFrame(
      (frame) => frame.method === "session/request_permission", "the Agent's permission request frame")
    assert.equal(request.jsonrpc, "2.0", "the protocol version is not stripped")
    assert.equal(request.params.sessionId, sessionId, "the request says which session it belongs to")
    assert.equal(request.params.toolCall.toolCallId, "call-1")
    assert.deepEqual(request.params.options.map((option) => option.optionId),
      ["grant-once", "grant-always", "reject-once"], "the Agent's own options, in the Agent's own order")

    sidecar.writeRaw({ jsonrpc: "2.0", id: request.id, result: { outcome: { outcome: "selected", optionId: "grant-always" } } })
    const done = await sidecar.waitForFrame(isReply(prompt.id), `the reply to the client's prompt (${prompt.id})`)
    assert.deepEqual(done.result, { stopReason: "end_turn" })

    const [answer] = await sidecar.notes("reverse-reply")
    assert.deepEqual(answer.result, { outcome: { outcome: "selected", optionId: "grant-always" } },
      "byte for byte what the client wrote, including an option the plugin never offered")
  })
})

test("T6: a client method the access layer does not implement is routed, not refused on the client's behalf", async () => {
  // `fs/read_text_file` is in the adapter's `CLIENT_METHODS` table. Today `acp-client.js:318`
  // routes everything that is not `session/request_permission` to `#respondUnsupported` (`:394`),
  // which tells the Agent "Harness Remote bridge does not implement fs/read_text_file" — the
  // plugin declaring, in a real ACP capability's own words, that a capability is absent.
  await withSidecar(async ({ sidecar }) => {
    const { sessionId } = await liveChannel(sidecar)
    send(sidecar, "session/prompt", { sessionId, prompt: [{ type: "text", text: "ask-file" }] })

    const request = await sidecar.waitForFrame((frame) => frame.method === "fs/read_text_file",
      "the Agent's file request frame")
    assert.equal(request.params.path, "notes.txt")
    sidecar.writeRaw({ jsonrpc: "2.0", id: request.id, result: { content: "from the client\n" } })

    const [answer] = await sidecar.notes("reverse-reply")
    assert.equal(answer.error, null, "the Agent must not be answered with this plugin's own refusal")
    assert.deepEqual(answer.result, { content: "from the client\n" })
  })
})

test("T7: concurrent client-bound requests keep their own ids and their own answers", async () => {
  // Five requests in flight on one connection, answered out of order. Today the frames never reach
  // the host at all (T5), so per-request correlation cannot be proven through the current channel;
  // `pendingPermissions` being a Map is not enough, because the key it hands out is a minted uuid
  // rather than the Agent's request id.
  // Counterexample refused: answering request N with the answer meant for N+1, or answering one and
  // swallowing the rest.
  const count = 5
  await withSidecar(async ({ sidecar }) => {
    const { sessionId } = await liveChannel(sidecar)
    const prompt = send(sidecar, "session/prompt", { sessionId, prompt: [{ type: "text", text: "ask-many" }] })

    const seen = new Map()
    const startedAt = Date.now()
    for (;;) {
      // A request frame from the Agent is a line with both an `id` and a `method`; the client's
      // own frames are never echoed back, and a `session/update` notification has no `id`.
      for (const frame of sidecar.streamFrames()) {
        if (frame.id !== undefined && frame.method && !seen.has(frame.id)) seen.set(frame.id, frame)
      }
      if (seen.size >= count) break
      if (Date.now() - startedAt > 8000) {
        throw new Error(`only ${seen.size} of ${count} client-bound requests arrived; seen: ${JSON.stringify(
          [...seen.values()].map((frame) => [frame.id, frame.method]))}`)
      }
      await new Promise((resolve) => setTimeout(resolve, 10))
    }
    const requests = [...seen.values()]
    assert.equal(new Set(requests.map((frame) => frame.id)).size, count, "no two requests share an id")

    for (const frame of [...requests].reverse()) {
      const result = frame.method === "fs/read_text_file"
        ? { content: `body of ${frame.params.path}\n` }
        : { outcome: { outcome: "selected", optionId: "grant-once" } }
      sidecar.writeRaw({ jsonrpc: "2.0", id: frame.id, result })
    }
    const done = await sidecar.waitForFrame(isReply(prompt.id), `the reply to the client's prompt (${prompt.id})`)
    assert.equal(done.result.stopReason, "end_turn")

    const replies = (await sidecar.allNotes()).filter((row) => row.event === "reverse-reply")
    assert.equal(replies.length, count, "one answer per request, none merged")
    const methods = new Map(requests.map((frame) => [frame.id, frame.method]))
    for (const reply of replies) {
      assert.equal(reply.waiting, methods.get(reply.id),
        `the answer recorded for ${reply.id} claims a different method than the client saw`)
      assert.notEqual(reply.result, null, `request ${reply.id} was never answered`)
    }
  }, { AGENTBOX_FIXTURE_REVERSE_COUNT: String(count) })
})

test("T8: an error-only reply from the client is delivered and the turn still ends", async () => {
  // A client that refuses answers with `error` and no `result`. The channel must not turn that
  // into a hang, and must not launder it into a success the client never gave.
  await withSidecar(async ({ sidecar }) => {
    const { sessionId } = await liveChannel(sidecar)
    const prompt = send(sidecar, "session/prompt", { sessionId, prompt: [{ type: "text", text: "ask-file" }] })
    const request = await sidecar.waitForFrame((frame) => frame.method === "fs/read_text_file",
      "the Agent's file request frame")

    sidecar.writeRaw({ jsonrpc: "2.0", id: request.id, error: {
      code: -32_001, message: "file is not readable", data: { path: "notes.txt" },
    } })
    const done = await sidecar.waitForFrame(isReply(prompt.id), `the reply to the client's prompt (${prompt.id})`)
    assert.equal(done.result.stopReason, "end_turn", "the turn ends: an error answer is an answer")
    const [answer] = await sidecar.notes("reverse-reply")
    assert.equal(answer.result, null)
    assert.deepEqual(answer.error, { code: -32_001, message: "file is not readable", data: { path: "notes.txt" } },
      "code, message and data all survive to the Agent")
  })
})

// ---------------------------------------------------------------------------
// what a pure channel must NOT do
// ---------------------------------------------------------------------------

test("T9: an unanswered request stays unanswered — no refusal, no timeout decision, no brand policy", async () => {
  // Three counterexamples in one place, because they are the same mistake in three costumes, and
  // each was once the bridge's own behaviour:
  //   · no resolver registered → `#respondPermission` selected the Agent's own `allow_once` for a
  //     brand whose `permissionMode` is `allow` and emitted `{outcome:"cancelled"}` otherwise, so
  //     the answer depended on the brand string;
  //   · a resolver that timed out → `#resolvePermission` swallowed the timeout and the bridge wrote
  //     `cancelled`, so a wall clock was reported as the user's decision;
  //   · a caller that still believes the second knob exists → refused by name at connect, because
  //     accepting it silently would let a timeout look configured.
  // The requirement is not "refuse consistently". It is: the channel writes nothing.
  const unanswered = async (harness, connect) => withSidecar(async ({ sidecar }) => {
    const { sessionId } = await liveChannel(sidecar, { harness, connect })
    send(sidecar, "session/prompt", { sessionId, prompt: [{ type: "text", text: "ask-permission" }] })
    const request = await sidecar.waitForFrame((frame) => frame.method === "session/request_permission",
      `the Agent's permission request frame (${harness})`)
    // Give any in-bridge default, timeout or watchdog its chance to fire, then read the Agent's
    // own account. A `reverse-reply` row is written for *any* frame with an id and no method, so
    // "no row" means the Agent received no answer of either kind.
    await new Promise((resolve) => setTimeout(resolve, 2500))
    const rows = await sidecar.allNotes()
    assert.deepEqual(rows.filter((row) => row.event === "reverse-reply"), [],
      `${harness}: the plugin answered the Agent on the client's behalf`)
    assert(rows.some((row) => row.event === "prompt"), `${harness}: the turn was never even started`)
    return request.id
  })
  // Two brands that the retired chain routed differently (one allowed, one denied by default):
  // the transport must not reproduce that difference, because it does not answer at all.
  const allowed = await unanswered("codex", {})
  const denied = await unanswered("claude-code", {})
  assert(typeof allowed === "number" && typeof denied === "number", "both cases must still be waiting")

  await withSidecar(async ({ sidecar }) => {
    const refused = await establish(sidecar, { connect: { permissionTimeoutMs: 500 } })
    assert.equal(refused.ok, false)
    assert.match(refused.error.code, /RETIRED|UNKNOWN/, "a timeout knob is not accepted by a relay that never decides")
    assert.match(refused.error.message, /permissionTimeoutMs/, "the refusal names the field it refused")
  })
})

test("T10: a connection that dies is reported as the transport ending, not as an answer", async () => {
  // Today the Agent's exit becomes an `adapter_exit` *event* on the envelope
  // (`worker-entry.mjs:444`), and `AcpClient.#handleExit` rejects the bridge's own pending
  // requests with a JS `Error`, while the client-bound requests the Agent is still waiting on get
  // no report at all — they were answered synchronously at emit time. On a raw transport the
  // honest facts are two: the client's own outstanding requests must not be quietly swallowed, and
  // the Agent's outstanding requests must not be answered as if the client had decided.
  await withSidecar(async ({ sidecar }) => {
    const { sessionId } = await liveChannel(sidecar)
    const prompt = send(sidecar, "session/prompt", { sessionId, prompt: [{ type: "text", text: "hold" }] })
    const beforeDeath = sidecar.streamFrames().length

    const [{ pid }] = await sidecar.notes("session/new")
    process.kill(pid)
    await new Promise((resolve) => setTimeout(resolve, 500))

    const rows = await sidecar.allNotes()
    assert.deepEqual(rows.filter((row) => row.event === "reverse-reply"), [],
      "a dead peer must not be answered on the client's behalf")
    const after = sidecar.streamFrames().slice(beforeDeath)
    assert.ok(after.length > 0, "the end of the transport must be reported to the client, not swallowed")
    const forged = after.find((frame) => frame.id === prompt.id && frame.result !== undefined)
    assert.equal(forged, undefined,
      `the client's turn must not be closed with a result the Agent never sent: ${JSON.stringify(forged)}`)
  })
})
