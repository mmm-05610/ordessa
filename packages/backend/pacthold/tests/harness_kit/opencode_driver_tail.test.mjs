/**
 * Gates for the OpenCode leg of increment 1 (D-0011): the tail calibration's verdict becomes a fact
 * the caller receives, instead of a line in an audit file nobody is required to open.
 *
 * Two layers, because the two claims are different:
 *
 *   ①–⑤ the five verdicts, asserted on the pure decision function. Reaching `completed`/`mismatch`
 *         through `prompt()` would need a live SSE subscription, which only `start()` opens — and
 *         `start()` is the host-spawning path this probe must not take (same boundary the existing
 *         Python probe states: "the unit probe must not spawn").
 *   ⑥   the verdict's *delivery*: one real `prompt()` call against a stub HTTP layer, asserting the
 *         `tail` object arrives in the turn result and carries lengths, never text.
 *
 * Nothing is spawned and no credential, model or OpenCode build is touched; `globalThis.fetch` is
 * replaced for the duration of the last test only.
 */
import assert from "node:assert/strict"
import path from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const DRIVER = new URL(`file://${path.join(pluginRoot, "runtime", "drivers", "opencode-native.mjs")}`)
const { tailVerdict, tailSuffix, createDriver, auditPathFor } = await import(DRIVER.href)

test("① a stream that is not a prefix of the record is called a mismatch, and nothing is guessed", () => {
  const verdict = tailVerdict({ streamed: "hel", recorded: "axcd", deltas: 3 })
  assert.deepEqual(verdict, { outcome: "mismatch", supplement: "" })
})

test("② a stream that stopped short is completed with exactly the missing suffix", () => {
  assert.deepEqual(tailVerdict({ streamed: "ab", recorded: "abcd", deltas: 2 }),
    { outcome: "completed", supplement: "cd" })
  assert.equal(tailSuffix("ab", "abcd"), "cd", "the suffix still comes from the one authority for it")
})

test("③ stream and record agreeing is stated, not left as an absent fact", () => {
  assert.deepEqual(tailVerdict({ streamed: "abcd", recorded: "abcd", deltas: 4 }),
    { outcome: "matched", supplement: "" })
})

test("④ a record without assistant text is not counted as agreement", () => {
  assert.deepEqual(tailVerdict({ streamed: "abcd", recorded: "", deltas: 4 }),
    { outcome: "record-empty", supplement: "" })
})

test("⑤ no increments at all means the whole answer still has to be delivered once", () => {
  assert.deepEqual(tailVerdict({ streamed: "", recorded: "full answer", deltas: 0 }),
    { outcome: "record-only", supplement: "full answer" })
  assert.deepEqual(tailVerdict({ streamed: "", recorded: "", deltas: 0 }),
    { outcome: "record-only", supplement: "" }, "an empty answer is not turned into a fake one")
})

test("⑥ the verdict reaches the turn result, and carries lengths only", async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  const answer = (status, payload) => ({
    status, ok: status < 300, text: async () => JSON.stringify(payload),
  })
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url)
    calls.push([options.method ?? "GET", target.replace(/^http:\/\/127\.0\.0\.1:[^/]*\//, "/")])
    if (target.endsWith("/config/providers")) {
      return answer(200, { providers: [{ id: "deepseek", models: { "deepseek-flash": { id: "deepseek-flash" } } }] })
    }
    if (target.includes("/session/ses_1/message")) {
      return answer(200, { info: { id: "msg_1" }, parts: [{ type: "text", text: "the whole answer" }] })
    }
    if (target.includes("/session/ses_1")) return answer(200, { id: "ses_1", title: "stored" })
    return answer(200, {})
  }

  const emitted = []
  try {
    const driver = await createDriver({
      profileID: "opencode", command: "/runtime/bin/opencode", args: [],
      environment: {}, credentialEnvironment: null, hasCredential: false,
      directory: "/workspace", stateDirectory: null,
      emit: (message) => emitted.push(message),
      redact: (value, maximum) => String(value ?? "").slice(0, maximum),
      spawnProcess: () => { throw new Error("the tail probe must not spawn") },
    })
    await driver.open({ sessionId: "ses_1", model: "deepseek/deepseek-flash" })
    const result = await driver.prompt({
      sessionId: "ses_1", text: "hello", model: "deepseek/deepseek-flash",
    })

    // The premise: with no audit target configured, the verdict below is the only trace there is.
    assert.equal(auditPathFor({}, "/workspace"), null)
    assert.deepEqual(result.tail, {
      outcome: "record-only",
      emittedCharacters: "the whole answer".length,
      streamedCharacters: 0,
      recordedCharacters: "the whole answer".length,
    }, "the turn states what its tail calibration concluded")
    assert.equal(result.deltas, 0)
    assert.deepEqual(emitted, [{ event: "message_delta", data: { text: "the whole answer" } }],
      "the fallback delta is still delivered exactly once, as before")
    assert.equal(JSON.stringify(result.tail).includes("the whole answer"), false,
      "the fact is a length, not a copy of the answer")
  } finally {
    globalThis.fetch = originalFetch
  }
  assert.equal(calls.some(([method, target]) => method === "POST" && target.endsWith("/message")), true,
    "the probe really drove the prompt leg")
})
