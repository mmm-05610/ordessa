/**
 * Category: 接入 ACP / native access — self-proof of the controlled ACP harness.
 *
 * The target tests in `acp_passthrough_target.test.mjs` fail today on purpose. A
 * failing test is only evidence if the thing that failed is the product and not the
 * fixture, so this file proves the harness the other files drive can, by itself:
 *
 *   1. receive a **success** answer to a request it raised, record it, and end the
 *      turn it was holding;
 *   2. receive an **error-only** answer (no `result`), record it, and end the turn
 *      just the same;
 *   3. hold several requests at once and end the turn only when the last one is
 *      answered, correlating each answer by its own id;
 *   4. exit cleanly with nothing on stderr, so "no leftover async failure" is a
 *      measured fact about this process and not an absence of looking.
 *
 * Everything is a temp directory, a fake record file and a child process this file
 * spawns and kills. No real Agent, no network, no credential.
 */
import assert from "node:assert/strict"
import { mkdtemp, readFile, rm } from "node:fs/promises"
import { spawn } from "node:child_process"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
const harnessPath = path.join(pluginRoot, "tests", "access", "controlled_harness.mjs")
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

class Harness {
  constructor(env) {
    this.env = env
  }

  async start() {
    this.state = await mkdtemp(path.join(tmpdir(), "agentbox-fixture-"))
    this.record = path.join(this.state, "record.jsonl")
    this.child = spawn(process.execPath, [harnessPath], {
      env: { ...process.env, AGENTBOX_FIXTURE_RECORD: this.record, ...this.env },
      stdio: ["pipe", "pipe", "pipe"],
    })
    this.frames = []
    this.stderrText = ""
    let buffer = ""
    this.child.stdout.setEncoding("utf8")
    this.child.stdout.on("data", (chunk) => {
      buffer += chunk
      let index
      while ((index = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, index).trim()
        buffer = buffer.slice(index + 1)
        if (line) this.frames.push(JSON.parse(line))
      }
    })
    this.child.stderr.setEncoding("utf8")
    this.child.stderr.on("data", (chunk) => { this.stderrText += chunk })
    this.exit = new Promise((resolve) => this.child.once("exit", (code, signal) => resolve({ code, signal })))
    this.nextId = 1
    await this.call("initialize", { protocolVersion: 1, clientCapabilities: {} })
    const created = await this.call("session/new", { cwd: this.state, mcpServers: [] })
    this.sessionId = created.result.sessionId
  }

  send(message) { this.child.stdin.write(`${JSON.stringify(message)}\n`) }

  async call(method, params) {
    const id = this.nextId++
    const sent = this.frames.length
    this.send({ jsonrpc: "2.0", id, method, params })
    return this.waitFor((frame) => frame.id === id && (frame.result !== undefined || frame.error !== undefined), sent)
  }

  /** A frame the harness pushed with no id of ours: a notification or its own request. */
  async raisedRequest(method, after = 0) {
    return this.waitFor((frame) => frame.method === method && frame.id !== undefined, after)
  }

  async waitFor(predicate, fromIndex = 0, timeoutMs = 5000) {
    const startedAt = Date.now()
    for (;;) {
      const match = this.frames.slice(fromIndex).find(predicate)
      if (match) return match
      if (Date.now() - startedAt > timeoutMs) {
        throw new Error(`no matching frame; the harness sent ${JSON.stringify(this.frames.slice(fromIndex).map((f) => f.method ?? `reply:${f.id}`))}`)
      }
      await sleep(10)
    }
  }

  async notes(event) {
    const startedAt = Date.now()
    for (;;) {
      let rows = []
      try {
        rows = (await readFile(this.record, "utf8")).split("\n").filter(Boolean).map((line) => JSON.parse(line))
      } catch { /* not written yet */ }
      const found = event ? rows.filter((row) => row.event === event) : rows
      if (found.length) return found
      if (Date.now() - startedAt > 5000) throw new Error(`no ${event ?? "any"} row in the record file`)
      await sleep(10)
    }
  }

  async allNotes() {
    try {
      return (await readFile(this.record, "utf8")).split("\n").filter(Boolean).map((line) => JSON.parse(line))
    } catch { return [] }
  }

  /** End the stream the way a closed connection does, and prove the process is done. */
  async stop() {
    this.child.stdin.end()
    const outcome = await Promise.race([this.exit, sleep(3000).then(() => "timeout")])
    if (outcome === "timeout") {
      this.child.kill()
      await this.exit
      await rm(this.state, { recursive: true, force: true })
      return { code: null, signal: "still-running" }
    }
    await rm(this.state, { recursive: true, force: true })
    return outcome
  }
}


test("fixture self-proof: a success answer is received, recorded, and ends the held turn", async () => {
  const harness = new Harness({})
  await harness.start()
  try {
    const before = harness.frames.length
    const prompt = harness.call("session/prompt", { sessionId: harness.sessionId, prompt: [{ type: "text", text: "ask-file" }] })
    const raised = await harness.raisedRequest("fs/read_text_file", before)
    assert.equal(raised.params.path, "notes.txt")

    harness.send({ jsonrpc: "2.0", id: raised.id, result: { content: "host body\n" } })
    const settled = await prompt
    assert.deepEqual(settled.result, { stopReason: "end_turn" }, "the turn ends once the request is answered")

    const [reply] = await harness.notes("reverse-reply")
    assert.deepEqual(reply.result, { content: "host body\n" }, "the record is what the harness really received")
    assert.equal(reply.error, null)
    assert.equal(reply.waiting, "fs/read_text_file")
  } finally {
    assert.deepEqual((await harness.stop()).code, 0, "a cleanly finished session exits 0")
    assert.equal(harness.stderrText, "", "and leaves nothing on stderr")
  }
})

test("fixture self-proof: an error-only answer is received, recorded, and ends the held turn", async () => {
  // The shape a refusing host sends: `error` and no `result`. If the harness treated
  // that as "nothing yet", the turn would hang and the target tests would time out
  // for the wrong reason.
  const harness = new Harness({})
  await harness.start()
  try {
    const before = harness.frames.length
    const prompt = harness.call("session/prompt", { sessionId: harness.sessionId, prompt: [{ type: "text", text: "ask-file" }] })
    const raised = await harness.raisedRequest("fs/read_text_file", before)
    harness.send({ jsonrpc: "2.0", id: raised.id, error: { code: -32_001, message: "not readable" } })

    const settled = await prompt
    assert.deepEqual(settled.result, { stopReason: "end_turn" })
    const [reply] = await harness.notes("reverse-reply")
    assert.equal(reply.result, null)
    assert.deepEqual(reply.error, { code: -32_001, message: "not readable" })
    const chunk = harness.frames.filter((frame) => frame.method === "session/update").at(-1)
    assert.equal(chunk.params.update.content.text, "answer-error:-32001",
      "the harness reports the error it was given, not a success it invented")
  } finally {
    assert.deepEqual((await harness.stop()).code, 0)
    assert.equal(harness.stderrText, "")
  }
})

test("fixture self-proof: several requests stay separate, and the turn ends once, after the last answer", async () => {
  const harness = new Harness({ AGENTBOX_FIXTURE_REVERSE_COUNT: "4" })
  await harness.start()
  try {
    const before = harness.frames.length
    const prompt = harness.call("session/prompt", { sessionId: harness.sessionId, prompt: [{ type: "text", text: "ask-many" }] })
    await harness.raisedRequest("fs/read_text_file", before)
    await sleep(50)

    const raised = harness.frames.slice(before).filter((frame) => frame.id !== undefined && frame.method)
    assert.equal(raised.length, 4, `the harness raised ${raised.length} of 4 requests`)
    assert.equal(new Set(raised.map((frame) => frame.id)).size, 4, "the ids collide, so answers could not be correlated")
    assert.equal(harness.frames.slice(before).some((frame) => frame.result?.stopReason), false,
      "the turn must not settle while any request is unanswered")

    // Answer out of order, and mix the two reply shapes, so a wrong correlation or a
    // settle-on-first-answer bug is both visible.
    const [third, first, second, fourth] = raised
    harness.send({ jsonrpc: "2.0", id: third.id, error: { code: -32_001, message: "refused" } })
    await sleep(20)
    assert.equal(harness.frames.slice(before).some((frame) => frame.result?.stopReason), false,
      "the third answer must not end a turn that still owes two")
    harness.send({ jsonrpc: "2.0", id: first.id, result: { outcome: { outcome: "selected", optionId: "grant-once" } } })
    harness.send({ jsonrpc: "2.0", id: second.id, result: { content: "b\n" } })
    harness.send({ jsonrpc: "2.0", id: fourth.id, result: { outcome: { outcome: "cancelled" } } })

    const settled = await prompt
    assert.deepEqual(settled.result, { stopReason: "end_turn" })
    const settles = harness.frames.slice(before).filter((frame) => frame.result?.stopReason !== undefined)
    assert.equal(settles.length, 1, "one held prompt, one settlement")

    const replies = await harness.notes("reverse-reply")
    assert.deepEqual(replies.map((row) => row.id).sort((a, b) => a - b), [third.id, first.id, second.id, fourth.id].sort((a, b) => a - b))
    for (const row of replies) {
      const origin = raised.find((frame) => frame.id === row.id)
      assert.equal(row.waiting, origin.method, `answer ${row.id} is recorded against the wrong request`)
    }
  } finally {
    assert.deepEqual((await harness.stop()).code, 0)
    assert.equal(harness.stderrText, "")
  }
})
