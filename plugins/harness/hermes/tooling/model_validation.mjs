import { mkdirSync,writeFileSync } from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'
export function hermesModelConfig() {
  // Hermes 0.19 reads model.provider/default from config.yaml.  The key remains an env reference;
  // no secret is materialized in this file. max_tokens is the documented native model cap.
  //
  // `custom` is Hermes' own, first-class user-defined-provider kind: the single
  // `providers.custom` block below carries the product's provider content (official root, key_env,
  // chat_completions transport, extra_body) and, unlike the built-in `deepseek` provider, leaves
  // the model id unchanged (hermes_cli.model_normalize.normalize_model_for_provider passes a custom
  // provider through as-is).  The built-in provider folds every id that is not
  // `deepseek-v<digit>...` to `deepseek-chat`, which would put a different model id on the wire
  // than the product declared.
  // The block is keyed by the bare kind, not by `custom:deepseek`, because Hermes persists the
  // *resolved* provider identity in its ACP session store and resumes a session through it: a
  // `custom:<key>` reference resolves the block on a fresh session but a resumed session resolves
  // no block at all and falls back to a placeholder credential (measured; without the restored
  // base URL Hermes would even fall back to its default OpenRouter root).  Keying the block
  // `custom` keeps the same endpoint, the same key_env and the same model on both paths.
  // Measured cost of this declaration: Hermes' ACP model state and resolved provider identity read
  // `custom:deepseek-flash` / `custom`, and model-metadata lookup falls back to the heuristic 128K
  // context window instead of the built-in DeepSeek table's 1,000,000.
  return {
    model: { provider: "custom", default: "deepseek-flash", max_tokens: 8192,
      base_url: "https://api.deepseek.com" },
    providers: { custom: {
      name: "DeepSeek official", api: "https://api.deepseek.com",
      key_env: "DEEPSEEK_API_KEY", transport: "chat_completions",
      default_model: "deepseek-flash", models: { "deepseek-flash": {} },
      extra_body: { thinking: { type: "disabled" } },
    } },
    agent: { api_max_retries: 1 },
  }
}

export function hermesConfigYaml() {
  return [
    "model:",
    "  provider: custom",
    "  default: deepseek-flash",
    "  max_tokens: 8192",
    "  base_url: https://api.deepseek.com",
    "providers:",
    "  custom:",
    "    name: DeepSeek official",
    "    api: https://api.deepseek.com",
    "    key_env: DEEPSEEK_API_KEY",
    "    transport: chat_completions",
    "    default_model: deepseek-flash",
    "    models:",
    "      deepseek-flash: {}",
    "    extra_body:",
    "      thinking:",
    "        type: disabled",
    "agent:",
    "  api_max_retries: 1",
    "",
  ].join("\n")
}

async function run({scratch,workspace,isolatedEnvironment,resolveToolchain,acpRoundTrip,runChild,textFrom}) {
  // Refuse before any child exists: a missing location must not become a
  // spawned process that fails somewhere less legible.
  const toolchain = resolveToolchain("hermes")
  const hermesHome = path.join(scratch, "hermes")
  mkdirSync(hermesHome, { recursive: true })
  const env = {
    ...isolatedEnvironment({ binDirectories: toolchain.binDirectories }),
    PYTHONPATH: toolchain.HERMES_PYTHON_SITE,
    PYTHONUNBUFFERED: "1",
    HERMES_HOME: hermesHome,
    HERMES_IGNORE_USER_CONFIG: "1",
    HERMES_IGNORE_RULES: "1",
    HERMES_SKIP_NODE_BOOTSTRAP: "1",
    HERMES_MODEL: "deepseek-flash",
    HERMES_INFERENCE_MODEL: "deepseek-flash",
    HERMES_TUI_PROVIDER: "custom",
    HERMES_INFERENCE_PROVIDER: "custom",
    HERMES_MAX_TOKENS: "64",
    HERMES_MAX_ITERATIONS: "1",
  }
  writeFileSync(path.join(hermesHome, "config.yaml"), hermesConfigYaml())
  return acpRoundTrip(toolchain.HERMES_BIN, ["acp"], env, null, "hermes")
}


export function modelValidationDeclaration() { const family="hermes"; return Object.freeze({ownerId:family,requirements:Object.freeze([{"name": "HERMES_BIN", "what": "the Hermes executable this family drives", "onPath": true}, {"name": "HERMES_PYTHON_SITE", "what": "the site-packages directory that holds the Hermes Python package", "onPath": false}]),run,prepared:()=>({ family, version: "hermes-agent@0.19.0", model: "deepseek-flash", provider: "custom", outputLimitTokens: 64, promptRequests: 2, maxProviderAttempts: 2, continuation: true, config: hermesModelConfig() }),methods:Object.freeze({hermesModelConfig,hermesConfigYaml})}) }
