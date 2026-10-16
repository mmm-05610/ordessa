import { mkdirSync,writeFileSync } from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'
export function openCodeModelConfig() {
  return {
    $schema: "https://opencode.ai/config.json",
    provider: { deepseek: {
      npm: "@ai-sdk/openai-compatible", name: "DeepSeek official",
      options: { baseURL: "https://api.deepseek.com", apiKey: "{env:DEEPSEEK_API_KEY}" },
      models: { "deepseek-flash": { name: "DeepSeek Flash (bounded acceptance)", reasoning: false,
        options: { thinking: { type: "disabled" } },
        limit: { context: 1_000_000, output: 64 } } },
    } },
  }
}

export function parseOpenCode(output, textFrom) {
  const events = output.split(/\r?\n/).filter(Boolean).flatMap((line) => {
    try { return [JSON.parse(line)] } catch { return [] }
  })
  const sessionId = events.map((item) => item.sessionID ?? item.sessionId ?? item.part?.sessionID).find(Boolean)
  return { events, sessionId, text: textFrom(events) }
}

async function run({scratch,workspace,isolatedEnvironment,resolveToolchain,acpRoundTrip,runChild,textFrom}) {
  const toolchain = resolveToolchain("opencode")
  const env = {
    ...isolatedEnvironment({ binDirectories: toolchain.binDirectories }),
    OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX: "64",
    OPENCODE_DISABLE_AUTOUPDATE: "1",
    OPENCODE_DISABLE_LSP_DOWNLOAD: "1",
    OPENCODE_DISABLE_MODELS_FETCH: "1",
  }
  const config = openCodeModelConfig()
  const configDir = path.join(env.XDG_CONFIG_HOME, "opencode")
  mkdirSync(configDir, { recursive: true })
  writeFileSync(path.join(configDir, "opencode.json"), JSON.stringify(config))
  const started = Date.now()
  const first = await runChild(toolchain.OPENCODE_BIN, [
    "run", "--pure", "--model", "deepseek/deepseek-flash", "--format", "json",
    "--title", `agentbox-42d-${randomUUID()}`, "--dir", workspace,
    "Reply with exactly OK. Do not use tools.",
  ], env, 90_000)
  const parsedFirst = parseOpenCode(first.stdout,textFrom)
  if (!parsedFirst.sessionId || !/\bOK\b/i.test(parsedFirst.text)) throw new Error("OPENCODE_FIRST_OUTPUT_MISSING")
  const second = await runChild(toolchain.OPENCODE_BIN, [
    "run", "--pure", "--session", parsedFirst.sessionId, "--model", "deepseek/deepseek-flash",
    "--format", "json", "--dir", workspace,
    "Reply with exactly TWO. Do not use tools.",
  ], env, 90_000)
  const parsedSecond = parseOpenCode(second.stdout,textFrom)
  if (!/\bTWO\b/i.test(parsedSecond.text)) throw new Error("OPENCODE_CONTINUATION_OUTPUT_MISSING")
  return {
    family: "opencode",
    outcome: "MODEL_VERIFIED",
    model: "deepseek/deepseek-flash",
    promptRequests: 2,
    maxProviderAttempts: 12,
    outputLimitTokens: 64,
    continuation: true,
    reopened: true,
    elapsedMs: Date.now() - started,
  }
}

export function modelValidationDeclaration() { const family="opencode"; return Object.freeze({ownerId:family,requirements:Object.freeze([{"name": "OPENCODE_BIN", "what": "the OpenCode executable this family drives", "onPath": true}]),run,prepared:()=>({ family, version: "opencode-ai@1.18.21", model: "deepseek/deepseek-flash", outputLimitTokens: 64, promptRequests: 2, maxProviderAttempts: 12, continuation: true, config: openCodeModelConfig() }),methods:Object.freeze({openCodeModelConfig,parseOpenCode})}) }
