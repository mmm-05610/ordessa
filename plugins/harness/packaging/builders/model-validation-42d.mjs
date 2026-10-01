#!/usr/bin/env node
/**
 * Bounded Work Order 42-D native Harness validation.
 *
 * The caller supplies exactly one authorized credential file and one family.
 * Secret content is held only in this coordinator and the selected child
 * environment, is never included in argv/output, and is overwritten in the
 * in-memory environment after the child exits. Every model request has a
 * 64-token output ceiling and a hard process/request deadline.
 *
 * The native tool locations are configuration, not constants: each family
 * declares which environment variables it needs (`HERMES_BIN`,
 * `HERMES_PYTHON_SITE`, `OPENCODE_BIN`) and the run fails closed, before any
 * child process is started, when a required one is absent. The child PATH is
 * then built from the resolved tool directories plus the system directories,
 * so no machine's personal bin directory is ever committed or inherited.
 */
import { spawn } from "node:child_process"
import { randomUUID } from "node:crypto"
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync, mkdirSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
// Pi's adapter is installed into Pi's own packaging npm root; the plugin's
// `runtime/` carries no dependency closure and never did hold one.
const npmRoot = path.join(root, "packaging", "pi")
const bridge = path.join(root, "third_party", "harness_remote", "bridge", "src")
const piAdapter = path.join(npmRoot, "node_modules", "@automatalabs", "pi-acp", "dist", "index.js")
const allowed = new Set(["pi", "hermes", "opencode"])

// -- native tool locations ---------------------------------------------------

/** Environment variables each family needs before it may start anything. */
export const TOOL_REQUIREMENTS = {
  pi: [],
  hermes: [
    { name: "HERMES_BIN", what: "the Hermes executable this family drives", onPath: true },
    { name: "HERMES_PYTHON_SITE", what: "the site-packages directory that holds the Hermes Python package", onPath: false },
  ],
  opencode: [
    { name: "OPENCODE_BIN", what: "the OpenCode executable this family drives", onPath: true },
  ],
}

//: The only directories every child may inherit unconditionally.
export const SYSTEM_BIN_DIRS = ["/usr/bin", "/bin"]

function environmentValue(env, name) {
  const raw = env?.[name]
  return typeof raw === "string" && raw.trim() ? raw.trim() : null
}

/**
 * Resolve every location a family needs, or refuse naming exactly what is
 * absent. Nothing is defaulted: a missing variable is a refusal, because a
 * guessed absolute path would silently validate a different installation.
 */
export function resolveToolchain(family, env = process.env) {
  const requirements = TOOL_REQUIREMENTS[family] ?? []
  const resolved = {}
  const missing = []
  for (const requirement of requirements) {
    const value = environmentValue(env, requirement.name)
    if (value === null) {
      missing.push(`${requirement.name} (${requirement.what})`)
      continue
    }
    if (!value.startsWith("/")) {
      missing.push(`${requirement.name}=${value} (${requirement.what}) must be an absolute path`)
      continue
    }
    resolved[requirement.name] = value
  }
  if (missing.length > 0) {
    throw new Error(
      `TOOLCHAIN_NOT_CONFIGURED: ${family} cannot start without ${missing.join(" and ")}.`
      + " Set the variable(s); this tool never guesses an absolute path under one machine's home directory.")
  }
  return {
    ...resolved,
    // Only executable locations contribute a directory to the child PATH; a
    // site-packages directory is a library root, not a bin directory.
    binDirectories: requirements.filter(({ onPath }) => onPath).map(({ name }) => path.dirname(resolved[name])),
  }
}

/**
 * The child PATH: the system directories plus the directories the resolved
 * tools actually live in. No personal bin directory is ever embedded here.
 */
export function buildIsolatedPath(binDirectories = [], systemDirectories = SYSTEM_BIN_DIRS) {
  const seen = new Set()
  const parts = []
  for (const directory of [...systemDirectories, ...binDirectories]) {
    const value = typeof directory === "string" ? directory.trim() : ""
    if (!value || seen.has(value)) continue
    seen.add(value)
    parts.push(value)
  }
  if (parts.length === 0) throw new Error("TOOLCHAIN_NOT_CONFIGURED: no executable directory to build a PATH from")
  return parts.join(path.delimiter)
}

function argument(name) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : undefined
}

const family = argument("--family")
const secretPath = argument("--secret-file")
const dryRun = process.argv.includes("--dry-run")
const checkToolchain = process.argv.includes("--check-toolchain")
if (!allowed.has(family) || !secretPath) {
  throw new Error("usage: model-validation-42d.mjs --family <pi|hermes|opencode> --secret-file <authorized-file> [--dry-run] [--check-toolchain]")
}
const mode = statSync(secretPath).mode & 0o777
if (mode & 0o077) throw new Error("AUTHORIZED_SECRET_PERMISSIONS_TOO_BROAD")
let secret = readFileSync(secretPath, "utf8").trim()
if (!secret || secret.length > 4096 || /[\r\n\0]/.test(secret)) throw new Error("AUTHORIZED_SECRET_INVALID")

const scratch = mkdtempSync(path.join(tmpdir(), `agentbox-42d-${family}-`))
const workspace = path.join(scratch, "workspace")
mkdirSync(workspace, { recursive: true })

function isolatedEnvironment({ binDirectories = [] } = {}) {
  return {
    PATH: buildIsolatedPath(binDirectories),
    HOME: scratch,
    TMPDIR: tmpdir(),
    XDG_CONFIG_HOME: path.join(scratch, "xdg-config"),
    XDG_CACHE_HOME: path.join(scratch, "xdg-cache"),
    XDG_DATA_HOME: path.join(scratch, "xdg-data"),
    DEEPSEEK_API_KEY: secret,
  }
}

function safeError(error) {
  return String(error?.message ?? error).replaceAll(secret, "[REDACTED]").slice(0, 500)
}

function textFrom(value) {
  const found = []
  const visit = (item) => {
    if (!item || typeof item !== "object") return
    if (typeof item.text === "string") found.push(item.text)
    if (Array.isArray(item)) for (const nested of item) visit(nested)
    else for (const [key, nested] of Object.entries(item)) if (key !== "text") visit(nested)
  }
  visit(value)
  return found.join("")
}

// These are deliberately pure descriptions of each native configuration surface.  Keeping them
// separate makes the acceptance preparation auditable without starting a Harness or contacting a
// provider.  The returned values never contain the credential itself.
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

async function acpRoundTrip(command, args, environment, model, label) {
  const { AcpClient } = await import(`file://${path.join(bridge, "acp-client.js")}`)
  const notifications = []
  const client = new AcpClient({
    command,
    args,
    permissionMode: "deny",
    spawnProcess: (cmd, cmdArgs, options) => spawn(cmd, cmdArgs, { ...options, env: environment }),
  })
  client.on("notification", (message) => notifications.push(message))
  const started = Date.now()
  try {
    await client.start(30_000)
    const created = await client.request("session/new", { cwd: workspace, mcpServers: [] }, 30_000)
    const sessionId = created.sessionId
    if (!sessionId) throw new Error("NATIVE_SESSION_ID_MISSING")
    if (model) {
      await client.request("session/set_config_option", {
        sessionId, configId: "model", value: model,
      }, 30_000)
    }
    const first = await client.request("session/prompt", {
      sessionId,
      prompt: [{ type: "text", text: "Reply with exactly OK. Do not use tools." }],
    }, 60_000)
    const firstText = textFrom(notifications.splice(0))
    const second = await client.request("session/prompt", {
      sessionId,
      prompt: [{ type: "text", text: "Reply with exactly TWO. Do not use tools." }],
    }, 60_000)
    const secondText = textFrom(notifications.splice(0))
    if (!/\bOK\b/i.test(firstText) || !/\bTWO\b/i.test(secondText)) {
      throw new Error(`${label.toUpperCase()}_MODEL_OUTPUT_MISSING`)
    }
    client.close()

    // A fresh adapter process must be able to load the native Session without
    // another model request. This is the independent persistence/reopen gate.
    const reopened = new AcpClient({
      command,
      args,
      permissionMode: "deny",
      spawnProcess: (cmd, cmdArgs, options) => spawn(cmd, cmdArgs, { ...options, env: environment }),
    })
    try {
      await reopened.start(30_000)
      await reopened.request("session/load", { sessionId, cwd: workspace, mcpServers: [] }, 30_000)
    } finally {
      reopened.close()
    }
    return {
      family: label,
      outcome: "MODEL_VERIFIED",
      model,
      promptRequests: 2,
      maxProviderAttempts: 2,
      outputLimitTokens: 64,
      continuation: true,
      reopened: true,
      firstStopReason: first.stopReason ?? null,
      secondStopReason: second.stopReason ?? null,
      elapsedMs: Date.now() - started,
    }
  } finally {
    client.close()
  }
}

async function runPi() {
  const agentDir = path.join(scratch, "pi-agent")
  mkdirSync(agentDir, { recursive: true })
  writeFileSync(path.join(agentDir, "models.json"), JSON.stringify(piModelConfig()))
  writeFileSync(path.join(agentDir, "settings.json"), JSON.stringify(piSettings()))
  const env = { ...isolatedEnvironment(), PI_CODING_AGENT_DIR: agentDir }
  return acpRoundTrip(process.execPath, [piAdapter], env, "deepseek/deepseek-flash", "pi")
}

async function runHermes() {
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

function runChild(command, args, environment, deadlineMs) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      env: environment,
      cwd: workspace,
      stdio: ["ignore", "pipe", "pipe"],
      detached: true,
    })
    let stdout = ""
    let stderr = ""
    const append = (current, chunk) => `${current}${chunk}`.slice(-512 * 1024)
    child.stdout.on("data", (chunk) => { stdout = append(stdout, chunk) })
    child.stderr.on("data", (chunk) => { stderr = append(stderr, chunk) })
    const timer = setTimeout(() => {
      try { process.kill(-child.pid, "SIGKILL") } catch {}
      reject(new Error("NATIVE_PROCESS_DEADLINE_EXCEEDED"))
    }, deadlineMs)
    child.on("error", (error) => { clearTimeout(timer); reject(error) })
    child.on("close", (code) => {
      clearTimeout(timer)
      if (code !== 0) reject(new Error(`NATIVE_PROCESS_EXIT_${code}: ${stderr.slice(-300)}`))
      else resolve({ stdout, stderr })
    })
  })
}

export function parseOpenCode(output) {
  const events = output.split(/\r?\n/).filter(Boolean).flatMap((line) => {
    try { return [JSON.parse(line)] } catch { return [] }
  })
  const sessionId = events.map((item) => item.sessionID ?? item.sessionId ?? item.part?.sessionID).find(Boolean)
  return { events, sessionId, text: textFrom(events) }
}

async function runOpenCode() {
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
  const parsedFirst = parseOpenCode(first.stdout)
  if (!parsedFirst.sessionId || !/\bOK\b/i.test(parsedFirst.text)) throw new Error("OPENCODE_FIRST_OUTPUT_MISSING")
  const second = await runChild(toolchain.OPENCODE_BIN, [
    "run", "--pure", "--session", parsedFirst.sessionId, "--model", "deepseek/deepseek-flash",
    "--format", "json", "--dir", workspace,
    "Reply with exactly TWO. Do not use tools.",
  ], env, 90_000)
  const parsedSecond = parseOpenCode(second.stdout)
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

try {
  if (dryRun) {
    const prepared = family === "pi"
      ? { family, version: "@automatalabs/pi-acp@0.5.0", model: "deepseek/deepseek-flash",
          outputLimitTokens: 64, promptRequests: 2, maxProviderAttempts: 2,
          continuation: true, config: piModelConfig(), settings: piSettings() }
      : family === "hermes"
        ? { family, version: "hermes-agent@0.19.0", model: "deepseek-flash",
            // The native provider declaration Hermes resolves (the user-defined-provider kind that
            // resolves the providers.custom block); the product's provider identity stays DeepSeek
            // official in that block (see hermesModelConfig).
            provider: "custom",
            outputLimitTokens: 64, promptRequests: 2, maxProviderAttempts: 2,
            continuation: true, config: hermesModelConfig() }
        : { family, version: "opencode-ai@1.18.21", model: "deepseek/deepseek-flash",
            outputLimitTokens: 64, promptRequests: 2, maxProviderAttempts: 12,
            continuation: true, config: openCodeModelConfig() }
    process.stdout.write(`${JSON.stringify({ outcome: "PREPARED", ...prepared })}\n`)
  } else if (checkToolchain) {
    // Resolve and report only: no child process and no model request, so an
    // operator can see which location is missing before spending anything.
    const toolchain = resolveToolchain(family)
    process.stdout.write(`${JSON.stringify({
      family, outcome: "TOOLCHAIN_READY", ...toolchain,
      // The exact PATH a real run would hand the child.
      isolatedPath: isolatedEnvironment({ binDirectories: toolchain.binDirectories }).PATH,
    })}\n`)
  } else {
    const result = family === "pi" ? await runPi() : family === "hermes" ? await runHermes() : await runOpenCode()
    process.stdout.write(`${JSON.stringify(result)}\n`)
  }
} catch (error) {
  process.stdout.write(`${JSON.stringify({ family, outcome: "FAILED", error: safeError(error) })}\n`)
  process.exitCode = 1
} finally {
  secret = "[CLEARED]"
  rmSync(scratch, { recursive: true, force: true })
}
