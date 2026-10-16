import { mkdirSync,writeFileSync } from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'
export function piModelConfig() {
  return {
    providers: { deepseek: {
      baseUrl: "https://api.deepseek.com",
      api: "openai-completions",
      apiKey: "$DEEPSEEK_API_KEY",
      models: [{ id: "deepseek-flash", name: "DeepSeek Flash (bounded acceptance)", reasoning: false,
        input: ["text"], contextWindow: 1_000_000, maxTokens: 8192,
        samplingParams: { thinking: { type: "disabled" } },
        // Conservative current official peak Flash tariff (USD / 1M tokens).
        cost: { input: 0.44, output: 1.32, cacheRead: 0.014, cacheWrite: 0 } }],
    } },
  }
}

export function piSettings() {
  // Disable both the agent-level replay and provider-client retry. One prompt
  // therefore has exactly one billable provider attempt.
  return { retry: { enabled: false, maxRetries: 0,
    provider: { maxRetries: 0, maxRetryDelayMs: 1_000 } } }
}

const piAdapter = fileURLToPath(new URL("./npm/node_modules/@automatalabs/pi-acp/dist/index.js",import.meta.url))
async function run({scratch,workspace,isolatedEnvironment,resolveToolchain,acpRoundTrip,runChild,textFrom}) {
  const agentDir = path.join(scratch, "pi-agent")
  mkdirSync(agentDir, { recursive: true })
  writeFileSync(path.join(agentDir, "models.json"), JSON.stringify(piModelConfig()))
  writeFileSync(path.join(agentDir, "settings.json"), JSON.stringify(piSettings()))
  const env = { ...isolatedEnvironment(), PI_CODING_AGENT_DIR: agentDir }
  return acpRoundTrip(process.execPath, [piAdapter], env, "deepseek/deepseek-flash", "pi")
}


export function modelValidationDeclaration() { const family="pi"; return Object.freeze({ownerId:family,requirements:Object.freeze([]),run,prepared:()=>({ family, version: "@automatalabs/pi-acp@0.5.0", model: "deepseek/deepseek-flash", outputLimitTokens: 64, promptRequests: 2, maxProviderAttempts: 2, continuation: true, config: piModelConfig(), settings: piSettings() }),methods:Object.freeze({piModelConfig,piSettings})}) }
