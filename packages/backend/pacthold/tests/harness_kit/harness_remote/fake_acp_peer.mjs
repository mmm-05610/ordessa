/**
 * Controlled ACP peer used as a fake native Harness for sidecar gates.
 * Speaks enough JSON-RPC/ACP for register/start/create/prompt/abort flows.
 */
import readline from "node:readline"
import { createHash } from "node:crypto"

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity })
const send = (message) => process.stdout.write(`${JSON.stringify(message)}\n`)

let sessions = 0
let pendingCancel = false
let pendingPrompt = null
let pendingPermission = null

// Optional silence for the explicit `silent-success` prompt: the deployment's
// adapter environment can raise it above the Worker's lease so a gate can prove
// that an attempt quiet for longer than the lease still finishes. The default
// is 0, and every existing prompt path is untouched.
const SILENCE_MS = Number.parseInt(process.env.AGENTBOX_FIXTURE_SILENCE_MS ?? "0", 10)
const promptSilenceMs = Number.isFinite(SILENCE_MS) && SILENCE_MS > 0 ? SILENCE_MS : 0
const PROMPT_SILENCE_DEFAULT_MS = 8_000

// LNX-002: the machine-readable stop reason this peer answers an ordinary prompt
// with. Defaults to `end_turn`, so every existing prompt path is byte-identical
// and no shared fixture default moves; the truncation pass-through test sets
// `AGENTBOX_FIXTURE_STOP_REASON=max_tokens` to drive the ACP result -> JS return
// -> Python completion leg with a non-clean reason. A comma-separated list is
// consumed one entry per ordinary prompt (`"max_tokens,end_turn"`), which is how
// two consecutive turns are given different terminal states; past the end of the
// list the default `end_turn` applies. Only the ordinary completion below honours
// it: the silent-success, permission, cancel and abort paths keep their own
// reasons on purpose.
const STOP_REASON = process.env.AGENTBOX_FIXTURE_STOP_REASON || "end_turn"
const STOP_REASON_SEQUENCE = STOP_REASON.split(",").map((item) => item.trim()).filter(Boolean)
let promptOrdinal = 0
const nextStopReason = () => STOP_REASON_SEQUENCE[promptOrdinal++] ?? "end_turn"

// The peer declares exactly the one model it accepts. A bridge that is asked for
// a model resolves it against the options the harness advertised and refuses
// anything not on the list, so a peer that advertises none is a harness that can
// run no configured model at all.
const MODEL_OPTION = {
  id: "model",
  name: "Model",
  category: "model",
  currentValue: "fixture-model",
  options: [{ value: "fixture-model", name: "Fixture model" }],
}

for await (const line of rl) {
  if (!line.trim()) continue
  const request = JSON.parse(line)
  const { id, method, params } = request
  if (method === "initialize") {
    send({ jsonrpc: "2.0", id, result: {
      agentInfo: { name: "controlled-peer", version: "test" },
      // `sessionCapabilities: { resume: {} }`——ACP 用**空对象**表示"已播发该能力"
      // （真实 Hermes / Pi 播发的就是这种形状）。客户端的 `acp-client.js` 只从
      // `agentCapabilities.sessionCapabilities` 取会话能力，所以这里少了它，这条受控
      // peer 的 `native_continuation` 观测就永远是 not-observed，与 native driver
      // fixture（播发 `sessionCapabilities: { resume: {} }`）不对等。
      agentCapabilities: { loadSession: true, sessionCapabilities: { resume: {} },
                           promptCapabilities: { image: true } },
      authMethods: [{ id: "none", name: "none" }],
    } })
  } else if (method === "authenticate") {
    send({ jsonrpc: "2.0", id, result: {} })
  } else if (method === "session/new") {
    sessions += 1
    // Each room gets its own PID namespace, so `process.pid` alone repeats
    // across concurrent rooms (both children can be pid 13). A random token
    // keeps two live native identities distinct, as a real Harness's
    // generated ids are; the `fake-native-` prefix stays the assertion anchor.
    const token = createHash("sha256")
      .update(`${Math.random()}-${Date.now()}`).digest("hex").slice(0, 8)
    send({ jsonrpc: "2.0", id, result: {
      sessionId: `fake-native-${process.pid}-${sessions}-${token}`,
      configOptions: [MODEL_OPTION],
    } })
  } else if (method === "session/load") {
    send({ jsonrpc: "2.0", id, result: {
      sessionId: params.sessionId,
      configOptions: [MODEL_OPTION],
    } })
  } else if (method === "session/prompt") {
    const image = params.prompt.find((item) => item.type === "image")
    const text = params.prompt.find((item) => item.type === "text")?.text ?? ""
    const streamed = image
      ? `image:${image.mimeType}:${createHash("sha256").update(Buffer.from(image.data, "base64")).digest("hex")}`
      : "controlled stream"
    const streamUpdate = () => send({ jsonrpc: "2.0", method: "session/update", params: {
      sessionId: params.sessionId,
      update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text: streamed } },
    } })
    if (text.includes("silent-success")) {
      // Write nothing at all for the declared silence, then answer: an attempt
      // that is quiet past the Worker lease must still finish, and the only
      // thing keeping the lease alive is the client's own traffic.
      setTimeout(() => {
        streamUpdate()
        send({ jsonrpc: "2.0", id, result: { stopReason: "end_turn" } })
      }, promptSilenceMs > 0 ? promptSilenceMs : PROMPT_SILENCE_DEFAULT_MS)
      continue
    }
    // A live chunk must be observable before the terminal response arrives.
    streamUpdate()
    if (text.includes("needs-permission")) {
      pendingPermission = { promptId: id, sessionId: params.sessionId }
      send({ jsonrpc: "2.0", id: 900, method: "session/request_permission", params: {
        sessionId: params.sessionId,
        toolCall: { name: "shell", title: "Run a bounded command" },
        options: [
          { kind: "allow_once", optionId: "grant-once" },
          { kind: "reject_once", optionId: "reject-once" },
        ],
      } })
      continue
    }
    if (text.includes("wait-for-cancel")) {
      pendingPrompt = id
      continue
    }
    if (text.includes("process-facts")) {
      // Order 52: exercise every neutral fact class through the real ACP wire:
      // the harness's reasoning, a tool call and its completion, a plan
      // snapshot and the selected mode.
      const sid = params.sessionId
      const update = (u) => send({ jsonrpc: "2.0", method: "session/update", params: {
        sessionId: sid, update: u,
      } })
      update({ sessionUpdate: "agent_thought_chunk",
               content: { type: "text", text: "reasoning through the steps" } })
      update({ sessionUpdate: "tool_call", toolCallId: "call-52",
               _meta: { toolName: "shell" }, title: "list the files",
               rawInput: { command: "ls" } })
      update({ sessionUpdate: "tool_call_update", toolCallId: "call-52",
               status: "completed" })
      update({ sessionUpdate: "plan", entries: [
        { content: "step one", status: "completed", priority: "high" },
        { content: "step two", status: "pending" },
      ] })
      update({ sessionUpdate: "current_mode_update", currentModeId: "code" })
      send({ jsonrpc: "2.0", id, result: { stopReason: "end_turn" } })
      continue
    }
    if (text.includes("delay-success")) {
      setTimeout(() => send({ jsonrpc: "2.0", id, result: { stopReason: "end_turn" } }), 500)
      continue
    }
    if (text.includes("delay-failure")) {
      setTimeout(() => send({ jsonrpc: "2.0", id, error: { code: -32001, message: "controlled failure" } }), 500)
      continue
    }
    send({ jsonrpc: "2.0", id, result: { stopReason: pendingCancel ? "cancelled" : nextStopReason() } })
    pendingCancel = false
  } else if (method === "session/cancel") {
    pendingCancel = true
    if (pendingPrompt !== null) {
      send({ jsonrpc: "2.0", id: pendingPrompt, result: { stopReason: "cancelled" } })
      pendingPrompt = null
    }
  } else if (id === 900 && request.result !== undefined && pendingPermission !== null) {
    const selected = request.result?.outcome?.optionId ?? "cancelled"
    send({ jsonrpc: "2.0", method: "session/update", params: {
      sessionId: pendingPermission.sessionId,
      update: {
        sessionUpdate: "agent_message_chunk",
        content: { type: "text", text: `permission:${selected}` },
      },
    } })
    send({ jsonrpc: "2.0", id: pendingPermission.promptId, result: { stopReason: "end_turn" } })
    pendingPermission = null
  } else if (method === "session/set_config_option") {
    send({ jsonrpc: "2.0", id, result: {
      configOptions: [{ ...MODEL_OPTION, currentValue: params.value }],
    } })
  } else if (id !== undefined) {
    send({ jsonrpc: "2.0", id, result: {} })
  }
}
