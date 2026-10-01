import test from "node:test"
import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const here = path.dirname(fileURLToPath(import.meta.url))
const script = path.join(here, "model-validation-42d.mjs")
// Both targets are inside this Harness package. These two lines carried the pre-monorepo
// workspace layout (`../../plugins/agent-box-harness/...` from here resolved to
// `plugins/harness/plugins/agent-box-harness/...`, which never existed here), so the
// continuation test below could only ever fail on a missing import — and it did, silently,
// for as long as no aggregate ran these files.
const fakePeer = path.resolve(here, "../../tests/harness_remote/fake_acp_peer.mjs")
const bridge = path.resolve(here, "../../third_party/harness_remote/bridge/src/acp-client.js")

function dryRun(family) {
  const dir = mkdtempSync(path.join(tmpdir(), "agentbox-42d-test-"))
  const secret = path.join(dir, "fake-token")
  writeFileSync(secret, "fake-token-for-local-test", { mode: 0o600 })
  try {
    const child = spawnSync(process.execPath, [script, "--family", family, "--secret-file", secret, "--dry-run"], {
      encoding: "utf8", env: { PATH: "/usr/bin:/bin", HOME: dir, TMPDIR: tmpdir(), NODE_NO_WARNINGS: "1" },
    })
    assert.equal(child.status, 0, child.stderr)
    return JSON.parse(child.stdout)
  } finally { rmSync(dir, { recursive: true, force: true }) }
}

// Deliberately no provider process or network: this checks the three native config shapes and
// catches accidental credential materialization while still exercising the real entrypoint.
import { spawnSync } from "node:child_process"
for (const family of ["pi", "hermes", "opencode"]) {
  test(`${family} preparation is bounded and secret-free`, () => {
    const result = dryRun(family)
    assert.equal(result.outcome, "PREPARED")
    assert.equal(result.promptRequests, 2)
    assert.equal(result.maxProviderAttempts, family === "opencode" ? 12 : 2)
    assert.equal(result.outputLimitTokens, 64)
    assert.equal(result.continuation, true)
    assert.equal(JSON.stringify(result).includes("fake-token"), false)
    // Two different numbers, and conflating them is what made this file red from birth.
    // `outputLimitTokens` above is the probe's RUNTIME ceiling — the value the coordinator
    // passes to the child as HERMES_MAX_TOKENS / OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX and
    // what it reports back. The value in the native config is the model's own DECLARED cap,
    // which is what DeepSeek Flash actually publishes. Asserting the declared cap down to the
    // runtime ceiling would declare a model that cannot emit a real answer; the cost bound is
    // enforced by the environment, not by under-declaring the model.
    if (family === "pi") {
      assert.equal(result.model, "deepseek/deepseek-flash")
      assert.equal(result.config.providers.deepseek.models[0].maxTokens, 8192)
      assert.deepEqual(result.config.providers.deepseek.models[0].samplingParams,
        { thinking: { type: "disabled" } })
      assert.deepEqual(result.settings.retry, { enabled: false, maxRetries: 0,
        provider: { maxRetries: 0, maxRetryDelayMs: 1_000 } })
    }
    if (family === "hermes") assert.deepEqual(result.config.model, {
      // `custom` is the user-defined-provider kind that resolves the providers.custom block and
      // leaves the model id unchanged; the built-in `deepseek` provider would fold
      // `deepseek-flash` to `deepseek-chat` before the provider request.
      provider: "custom", default: "deepseek-flash", max_tokens: 8192, base_url: "https://api.deepseek.com",
    })
    if (family === "hermes") {
      assert.equal(result.config.agent.api_max_retries, 1)
      // The declared block is keyed by Hermes' user-defined-provider kind, which is also what
      // model.provider resolves and what a resumed ACP session persists.
      assert.equal(result.config.model.provider, "custom")
      assert.equal(result.config.providers.custom.api, "https://api.deepseek.com")
      assert.equal(result.config.providers.custom.key_env, "DEEPSEEK_API_KEY")
      assert.equal(result.config.providers.custom.transport, "chat_completions")
      assert.equal(result.config.providers.custom.default_model, "deepseek-flash")
      assert.deepEqual(result.config.providers.custom.models, { "deepseek-flash": {} })
      assert.deepEqual(result.config.providers.custom.extra_body, { thinking: { type: "disabled" } })
    }
    if (family === "opencode") {
      assert.equal(result.model, "deepseek/deepseek-flash")
      assert.equal(result.config.provider.deepseek.models["deepseek-flash"].limit.output, 64)
      assert.deepEqual(result.config.provider.deepseek.models["deepseek-flash"].options,
        { thinking: { type: "disabled" } })
    }
  })
}

test("ACP continuation and reopen use only a local fake peer", async () => {
  const { AcpClient } = await import(`file://${bridge}`)
  const env = { PATH: "/usr/bin:/bin", HOME: mkdtempSync(path.join(tmpdir(), "agentbox-acp-home-")) }
  const make = () => new AcpClient({ command: process.execPath, args: [fakePeer], permissionMode: "deny",
    spawnProcess: (cmd, args, options) => spawn(cmd, args, { ...options, env }) })
  const client = make()
  try {
    await client.start(5_000)
    const created = await client.request("session/new", { cwd: env.HOME, mcpServers: [] }, 5_000)
    const first = await client.request("session/prompt", { sessionId: created.sessionId, prompt: [{ type: "text", text: "OK" }] }, 5_000)
    const second = await client.request("session/prompt", { sessionId: created.sessionId, prompt: [{ type: "text", text: "TWO" }] }, 5_000)
    assert.equal(first.stopReason, "end_turn")
    assert.equal(second.stopReason, "end_turn")
    client.close()
    const reopened = make()
    try { await reopened.start(5_000); const loaded = await reopened.request("session/load", { sessionId: created.sessionId, cwd: env.HOME, mcpServers: [] }, 5_000); assert.equal(loaded.sessionId, created.sessionId) }
    finally { reopened.close() }
  } finally { client.close(); rmSync(env.HOME, { recursive: true, force: true }) }
})
