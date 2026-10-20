// Order 65 C: the delegation bridge - a minimal stdio MCP server.
//
// A parent Harness starts this process per its MCP configuration. It carries
// an *attempt-scoped* token (never the user's token), forwards exactly two
// operations to the Server's loopback delegation surface, and returns bounded
// results. It holds no state, reads no credentials, and knows nothing about
// Profiles: the Server resolves the roster and runs the child execution.
//
// Env: AGENTBOX_BRIDGE_URL (loopback base), AGENTBOX_BRIDGE_TOKEN (this attempt).
import readline from "node:readline"

const base = process.env.AGENTBOX_BRIDGE_URL ?? ""
const token = process.env.AGENTBOX_BRIDGE_TOKEN ?? ""
const calls = { count: 0 }

async function call(op, argumentsValue) {
  const response = await fetch(`${base}/internal/delegation/${token}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ op, arguments: argumentsValue, callsThisTurn: calls.count }),
  })
  const body = await response.json()
  if (body.error) {
    const error = new Error(body.message ?? body.error)
    error.code = body.error
    error.available = body.available ?? []
    throw error
  }
  return body.result
}

function text(value) {
  return { content: [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value) }] }
}

const tools = [
  { name: "list_subagents", description: "List the subagents this role may call.",
    inputSchema: { type: "object", properties: { query: { type: "string" } },
                   additionalProperties: false } },
  { name: "run_subagent", description: "Run one authorized subagent and return its bounded summary.",
    inputSchema: { type: "object", properties: {
      subagent: { type: "string" }, description: { type: "string" }, prompt: { type: "string" },
      task_id: { type: "string" }, model: { type: "string" },
      permission: { type: "string", enum: ["default", "plan"] },
      timeout: { type: "integer" }, max_turns: { type: "integer" } },
      required: ["subagent", "description", "prompt"], additionalProperties: false } },
]

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity })
const send = (message) => process.stdout.write(`${JSON.stringify(message)}\n`)

for await (const line of rl) {
  if (!line.trim()) continue
  const { id, method, params = {} } = JSON.parse(line)
  try {
    if (method === "initialize") {
      send({ jsonrpc: "2.0", id, result: {
        protocolVersion: params.protocolVersion ?? "2024-11-05",
        serverInfo: { name: "agentbox-subagents", version: "1" },
        capabilities: { tools: {} },
      } })
    } else if (method === "notifications/initialized") {
      continue
    } else if (method === "tools/list") {
      // The roster is resolved live by the Server, so the description never
      // carries a name this role may not see.
      const live = await call("list", null)
      const merged = live.tools?.length ? live.tools : tools
      send({ jsonrpc: "2.0", id, result: { tools: merged } })
    } else if (method === "tools/call") {
      const name = params.name
      if (name !== "list_subagents" && name !== "run_subagent") {
        send({ jsonrpc: "2.0", id, error: { code: -32601, message: `unknown tool ${name}` } })
        continue
      }
      calls.count += 1
      const result = await call(name === "list_subagents" ? "list" : "run",
                                name === "list_subagents" ? null : (params.arguments ?? {}))
      send({ jsonrpc: "2.0", id, result: text(
        name === "list_subagents" ? result.roster : {
          subagent: result.subagent, state: result.state, summary: result.summary,
          task_id: result.task_id, errorCode: result.errorCode ?? undefined,
        }) })
    } else {
      send({ jsonrpc: "2.0", id, error: { code: -32601, message: `unknown method ${method}` } })
    }
  } catch (error) {
    // Typed refusals travel as tool errors with the available names inlined.
    send({ jsonrpc: "2.0", id, error: {
      code: -32000, message: error.message ?? String(error),
      data: { code: error.code ?? "SUBAGENT_BRIDGE_FAILED", available: error.available ?? [] },
    } })
  }
}
