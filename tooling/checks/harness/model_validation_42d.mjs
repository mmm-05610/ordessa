#!/usr/bin/env node
import { capturedModelValidationPorts } from "./selected_validation_ports.mjs"
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

// Pi's adapter is installed into Pi's own packaging npm root; the plugin's
// `runtime/` carries no dependency closure and never did hold one.
const bridge = fileURLToPath(new URL("../../../packages/execution/agents/src/ordessa_execution_agents/harness/transport/vendor/harness_remote/bridge/src", import.meta.url))
const captured = capturedModelValidationPorts()
const declarations = new Map(captured.map(port => [port.ownerId,port]))
const allowed = new Set(declarations.keys())
export const TOOL_REQUIREMENTS = Object.freeze(Object.fromEntries(captured.map(port => [port.ownerId,port.requirements])))

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

function declaredMethod(name,...args) { for(const port of captured) if(typeof port.methods[name]==='function') return port.methods[name](...args); throw new Error('MODEL_VALIDATION_METHOD_UNDECLARED') }
export function piModelConfig() {return declaredMethod('piModelConfig')}
export function piSettings() {return declaredMethod('piSettings')}
export function hermesModelConfig() {return declaredMethod('hermesModelConfig')}
export function hermesConfigYaml() {return declaredMethod('hermesConfigYaml')}
export function openCodeModelConfig() {return declaredMethod('openCodeModelConfig')}
export function parseOpenCode(output) {return declaredMethod('parseOpenCode',output,textFrom)}

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


try {
  if (dryRun) {
    const prepared = declarations.get(family).prepared()
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
    const result = await declarations.get(family).run({scratch,workspace,isolatedEnvironment,resolveToolchain,acpRoundTrip,runChild,textFrom})
    process.stdout.write(`${JSON.stringify(result)}\n`)
  }
} catch (error) {
  process.stdout.write(`${JSON.stringify({ family, outcome: "FAILED", error: safeError(error) })}\n`)
  process.exitCode = 1
} finally {
  secret = "[CLEARED]"
  rmSync(scratch, { recursive: true, force: true })
}
