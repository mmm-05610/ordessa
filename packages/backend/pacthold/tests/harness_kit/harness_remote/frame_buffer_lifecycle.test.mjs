/**
 * Gates for PATCHES.md §5: the stdout line buffer belongs to one adapter process, and any residue
 * is flushed on the way out instead of being lost.
 *
 * The six rows are the same inputs measured against the unpatched snapshot in
 * `worktrees/backend-loop/harness/tests/acp-defect-evidence.test.mjs` (instrument X14), and each row
 * states which side of the approved change it sits on:
 *
 *   ① CRLF framing                        unchanged — accepted before and after
 *   ② invalid JSON line                   unchanged — `protocol-error` before and after
 *   ③ JSON with neither `id` nor `method`  unchanged — still silent (central ruling: not this round)
 *   ④ orphan response                     unchanged — still silent (central ruling: not this round)
 *   ⑤ final frame without a newline       changed — now dispatched, on both `exit` and `close`
 *   ⑥ restart after a stale frame         changed — handshake completes instead of wedging
 *
 * Every peer is a fake driven through the constructor's own `spawnProcess` seam. No process is
 * spawned, and no real Harness, credential, or model is touched.
 */
import assert from "node:assert/strict"
import { EventEmitter } from "node:events"
import path from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"

const snapshot = process.env.HARNESS_REMOTE_SNAPSHOT
  ?? path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "third_party", "harness_remote")
const src = (...parts) => path.join(snapshot, "bridge", "src", ...parts)
const { AcpClient } = await import(`file://${src("acp-client.js")}`)

const tick = () => new Promise((resolve) => setImmediate(() => setImmediate(resolve)))
const notification = { jsonrpc: "2.0", method: "session/update", params: { sessionId: "s1" } }

function createPeer() {
  const children = []
  const spawnProcess = () => {
    const child = new EventEmitter()
    child.pid = 4900 + children.length
    child.killed = false
    child.kill = () => { child.killed = true }
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.stdout.setEncoding = () => undefined
    child.stderr.setEncoding = () => undefined
    child.stdin = { writable: true, write: (line, callback) => {
      const request = JSON.parse(line)
      if (request.method === "initialize") {
        setImmediate(() => child.stdout.emit("data", `${JSON.stringify({
          jsonrpc: "2.0",
          id: request.id,
          result: { agentInfo: { name: "fake", version: "0" }, agentCapabilities: {} },
        })}\n`))
      }
      callback?.()
      return true
    } }
    children.push(child)
    return child
  }
  const client = new AcpClient({ spawnProcess, permissionMode: "deny" })
  const seen = { notification: 0, protocolError: 0, agentRequest: 0 }
  client.on("notification", () => { seen.notification += 1 })
  client.on("protocol-error", () => { seen.protocolError += 1 })
  client.on("agent-request", () => { seen.agentRequest += 1 })
  const feed = (text) => children[children.length - 1].stdout.emit("data", text)
  return { client, children, seen, feed }
}

/** Rows ①-⑤ share this shape: start, feed one frame body, let the loop turn, report the counts. */
async function probeOneFrame(frame) {
  const peer = createPeer()
  await peer.client.start()
  peer.feed(frame)
  await tick()
  return peer.seen
}

test("① CRLF framing is accepted (unchanged by the patch)", async () => {
  assert.deepEqual(await probeOneFrame(`${JSON.stringify(notification)}\r\n`), {
    notification: 1, protocolError: 0, agentRequest: 0,
  })
})

test("② an invalid JSON line is reported on the existing protocol-error channel", async () => {
  assert.deepEqual(await probeOneFrame("this is not json\n"), {
    notification: 0, protocolError: 1, agentRequest: 0,
  })
})

test("③ JSON carrying neither id nor method stays silent this round", async () => {
  // Approved as *not* part of this increment: emitting a new event here would add an observable on
  // the bridge's internal event bus, which belongs to the frame-layer replacement (PATCHES.md §5).
  assert.deepEqual(await probeOneFrame('{"jsonrpc":"2.0","params":{}}\n'), {
    notification: 0, protocolError: 0, agentRequest: 0,
  })
})

test("④ an orphan response stays silent this round", async () => {
  assert.deepEqual(await probeOneFrame('{"jsonrpc":"2.0","id":424242,"result":{}}\n'), {
    notification: 0, protocolError: 0, agentRequest: 0,
  })
})

test("⑤ a final frame without a trailing newline is dispatched when the adapter exits", async () => {
  const peer = createPeer()
  await peer.client.start()
  peer.feed(JSON.stringify(notification))
  await tick()
  assert.equal(peer.seen.notification, 0, "the newline-less residue is still buffered while alive")
  peer.children[peer.children.length - 1].emit("exit", 0, null)
  await tick()
  assert.equal(peer.seen.notification, 1, "exit flushes the last frame instead of dropping it")
})

test("⑤b the same residue is dispatched when the bridge closes deliberately", async () => {
  const peer = createPeer()
  await peer.client.start()
  peer.feed(JSON.stringify(notification))
  await tick()
  peer.client.close()
  await tick()
  assert.equal(peer.seen.notification, 1, "close flushes as well, so a shutdown cannot lose the frame")
})

test("⑤c unparseable residue on exit uses protocol-error, not a new event type", async () => {
  const peer = createPeer()
  await peer.client.start()
  peer.feed("{ truncated")
  await tick()
  peer.children[peer.children.length - 1].emit("exit", 0, null)
  await tick()
  assert.deepEqual(peer.seen, { notification: 0, protocolError: 1, agentRequest: 0 })
})

test("⑥ a restart after a stale frame completes its own handshake", async () => {
  const peer = createPeer()
  await peer.client.start()
  peer.feed('{"stale_from_previous_process":1} ')
  await tick()
  peer.children[peer.children.length - 1].emit("exit", 1, null)
  await tick()
  peer.client.close()

  // Before the patch the leftover bytes were prepended to the new process's first message, so this
  // never resolved and ended in `ACP adapter request timed out: initialize`.
  await peer.client.start(1_000)
  assert.equal(peer.children.length, 2, "the second adapter process really did start")
  assert.equal(peer.seen.protocolError, 0, "the new process's frames are its own, start to finish")
  assert.ok(peer.client.agentInfo, "the restart answered its own initialize")
})
