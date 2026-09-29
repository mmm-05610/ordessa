/**
 * Controlled bidirectional ACP peer for the acp-orchestration target tests
 * (tests/acp_orchestration).  It speaks the ACP surface the production bridge
 * (plugins/agent-box-harness/third_party/harness_remote/bridge) actually uses:
 * initialize / authenticate / session/new / session/load / session/prompt /
 * session/cancel, plus the reverse session/request_permission round-trip.
 *
 * It is not a model and touches no network and no credential.  Every frame in
 * and out is appended as one JSON line to `${HD003_LOG}.${pid}` so tests can
 * read per-process evidence even when several peers share one log base.
 *
 * Scenario triggers (substring of the prompt text):
 *   scenario:rpc-error        answer the prompt with a JSON-RPC error carrying
 *                             code -32603 and a data payload
 *   scenario:permission       reverse request id 7777 with allow_once/reject_once
 *   scenario:permission + custom-options
 *                             reverse request whose only option has a
 *                             non-standard kind ("advance") and optionId
 *                             "client-pick-<peerId>"
 *   scenario:hang             never answer until session/cancel arrives
 *   scenario:die              stream one chunk, then exit(3) mid-prompt
 *   scenario:rich             timed thought chunks, a tool_call plus
 *                             tool_call_update completion, and split message
 *                             chunks on one messageId, then end_turn
 *   scenario:custom-update    an agent-chunk plus an unknown sessionUpdate kind
 *   scenario:meta             an agent-chunk carrying update-level _meta
 * otherwise                     echo "got:<text>" and end_turn
 */
import readline from "node:readline"
import { appendFileSync, writeSync } from "node:fs"

const base = process.env.HD003_LOG
if (!base) { writeSync(2, "HD003_LOG_REQUIRED\n"); process.exit(2) }
const peerId = process.env.HD003_PEER_ID || String(process.pid)
const logFile = `${base}.${process.pid}.${peerId}`
const forcedSessionId = process.env.HD003_FORCE_SESSION_ID || null
const PERMISSION_ID = 7777

function record(event) {
  appendFileSync(logFile, `${JSON.stringify({ peer: peerId, pid: process.pid, ...event })}\n`)
}
function send(value) {
  record({ dir: "send", frame: value })
  writeSync(1, `${JSON.stringify(value)}\n`)
}

const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity })
let nextSession = 0
let held = null        // {id, sessionId} of a prompt awaiting an external event
record({ event: "peer-start", cwd: process.cwd() })

function chunk(sessionId, text, extra = {}) {
  send({ jsonrpc: "2.0", method: "session/update", params: {
    sessionId,
    update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text }, ...extra },
  } })
}

lines.on("line", (line) => {
  if (!line.trim()) return
  let frame
  try { frame = JSON.parse(line) } catch { return }
  const { id, method, params } = frame
  record({ dir: "recv", frame })
  if (method === "initialize") {
    send({ jsonrpc: "2.0", id, result: {
      agentInfo: { name: "hd003-peer", version: "test", vendorExtensions: { hd003: true } },
      agentCapabilities: {
        loadSession: true,
        sessionCapabilities: { resume: {} },
        hd003_custom_capability: { level: 3 },
      },
      promptCapabilities: { image: {} },
      authMethods: [{ id: "none", name: "none" }],
    } })
  } else if (method === "authenticate") {
    send({ jsonrpc: "2.0", id, result: {} })
  } else if (method === "session/new") {
    nextSession += 1
    const sessionId = forcedSessionId ?? `hd003-${peerId}-${nextSession}`
    record({ event: "session-new", sessionId, cwdParam: params?.cwd ?? null, cwd: process.cwd(), params })
    send({ jsonrpc: "2.0", id, result: { sessionId, configOptions: [] } })
  } else if (method === "session/load") {
    record({ event: "session-load", params })
    send({ jsonrpc: "2.0", id, result: { sessionId: params.sessionId, configOptions: [] } })
  } else if (method === "session/prompt") {
    const text = (params.prompt ?? []).filter((p) => p?.type === "text").map((p) => p.text).join(" ")
    const sessionId = params.sessionId
    if (text.includes("scenario:rpc-error")) {
      send({ jsonrpc: "2.0", id, error: {
        code: -32603, message: "hd003 peer internal failure", data: { vendorDetail: "keep-me" },
      } })
    } else if (text.includes("scenario:permission")) {
      held = { id, sessionId }
      const custom = text.includes("custom-options")
      const twin = text.includes("twin-options")
      let options
      if (twin) {
        // Two options share the kind; only the optionId distinguishes them, so
        // a middle layer that guesses by kind is observable on the wire.
        options = [
          { kind: "allow_once", optionId: `pick-1-${peerId}`, name: "Pick one" },
          { kind: "allow_once", optionId: `pick-2-${peerId}`, name: "Pick two" },
          { kind: "reject_once", optionId: `reject-${peerId}`, name: "Reject" },
        ]
      } else if (custom) {
        options = [{ kind: "advance", optionId: `client-pick-${peerId}`, name: "Client pick" }]
      } else {
        options = [
          { kind: "allow_once", optionId: `grant-${peerId}`, name: "Grant" },
          { kind: "reject_once", optionId: `reject-${peerId}`, name: "Reject" },
        ]
      }
      send({ jsonrpc: "2.0", id: PERMISSION_ID, method: "session/request_permission", params: {
        sessionId,
        toolCall: { toolCallId: `hd003-tool-${peerId}`, name: "shell", title: "hd003 approval" },
        options,
      } })
    } else if (text.includes("scenario:die")) {
      chunk(sessionId, "pre-death-chunk")
      process.exit(3)
    } else if (text.includes("scenario:hang")) {
      held = { id, sessionId }
    } else if (text.includes("scenario:rich")) {
      held = { id, sessionId }
      const steps = [
        { sessionUpdate: "agent_thought_chunk", messageId: "hd004-m1", content: { type: "text", text: "planning the answer… " } },
        { sessionUpdate: "agent_thought_chunk", messageId: "hd004-m1", content: { type: "text", text: "then running a tool." } },
        { sessionUpdate: "tool_call", toolCallId: "hd004-tool-1", title: "echo tool", status: "pending" },
        { sessionUpdate: "tool_call_update", toolCallId: "hd004-tool-1", status: "in_progress" },
        { sessionUpdate: "tool_call_update", toolCallId: "hd004-tool-1", status: "completed",
          content: [{ type: "content", content: { type: "text", text: "tool result: 3 passed" } }] },
        { sessionUpdate: "agent_message_chunk", messageId: "hd004-m1", content: { type: "text", text: "rich " } },
        { sessionUpdate: "agent_message_chunk", messageId: "hd004-m1", content: { type: "text", text: "streaming " } },
        { sessionUpdate: "agent_message_chunk", messageId: "hd004-m1", content: { type: "text", text: "answer" } },
      ]
      steps.forEach((update, index) => setTimeout(() => {
        send({ jsonrpc: "2.0", method: "session/update", params: { sessionId, update } })
        if (index === steps.length - 1) {
          held = null
          send({ jsonrpc: "2.0", id, result: { stopReason: "end_turn" } })
        }
      }, 400 * (index + 1)))
    } else if (text.includes("scenario:custom-update")) {
      send({ jsonrpc: "2.0", method: "session/update", params: {
        sessionId, update: { sessionUpdate: "hd003_extension", payload: { keep: "me" } },
      } })
      chunk(sessionId, `got:${text}`)
      send({ jsonrpc: "2.0", id, result: { stopReason: "end_turn" } })
    } else if (text.includes("scenario:meta")) {
      chunk(sessionId, "meta-payload", { _meta: { vendor: "hd003", keep: "me" } })
      send({ jsonrpc: "2.0", id, result: { stopReason: "end_turn" } })
    } else {
      chunk(sessionId, `got:${text}`)
      send({ jsonrpc: "2.0", id, result: { stopReason: "end_turn" } })
    }
  } else if (method === "session/cancel") {
    if (held !== null) {
      send({ jsonrpc: "2.0", id: held.id, result: { stopReason: "cancelled" } })
      held = null
    }
    if (id !== undefined) send({ jsonrpc: "2.0", id, result: {} })
  } else if (id === PERMISSION_ID && held !== null) {
    record({ event: "permission-answer", frame })
    send({ jsonrpc: "2.0", id: held.id, result: { stopReason: "end_turn" } })
    held = null
  } else if (id !== undefined) {
    send({ jsonrpc: "2.0", id, result: {} })
  }
})
lines.on("close", () => {
  record({ event: "stdin-eof" })
  process.exit(0)
})
