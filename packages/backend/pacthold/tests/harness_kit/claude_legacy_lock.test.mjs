import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"

function packageMap(name) {
  return JSON.parse(readFileSync(new URL(`../packaging/${name}/package-lock.json`, import.meta.url), "utf8")).packages
}

test("Claude upstream alias has an independent 0.75.1 closure beside canonical 0.81.2", () => {
  const legacy = packageMap("claude-legacy")
  const canonical = packageMap("claude")
  assert.equal(legacy["node_modules/@agentclientprotocol/claude-agent-acp"].version, "0.75.1")
  assert.equal(legacy["node_modules/@agentclientprotocol/sdk"].version, "1.4.0")
  assert.equal(legacy["node_modules/@anthropic-ai/claude-agent-sdk"].version, "0.3.257")
  assert.equal(canonical["node_modules/@agentclientprotocol/claude-agent-acp"].version, "0.81.2")
  assert.equal(canonical["node_modules/@agentclientprotocol/sdk"].version, "1.5.0")
  assert.equal(canonical["node_modules/@anthropic-ai/claude-agent-sdk"].version, "0.3.280")
  assert.equal(legacy[""].dependencies["@agentclientprotocol/claude-agent-acp"], "0.75.1")
})
