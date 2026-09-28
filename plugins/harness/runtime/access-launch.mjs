import { realpathSync, readFileSync } from "node:fs"
import path from "node:path"
import { harnessLaunchContext, listHarnesses, registryIdentityVersionMatches } from "../harnesses/index.mjs"

/** Launch authority for the three managed ACP brands. No network fallback is permitted. */

const MANAGED = {
  pi: { artifact: "pi-runtime", package: "@automatalabs/pi-acp" },
  codex: { artifact: "codex-runtime", package: "@agentclientprotocol/codex-acp" },
  "claude-code": { artifact: "claude-runtime", package: "@agentclientprotocol/claude-agent-acp" },
  claude: { artifact: "claude-legacy-runtime", package: "@agentclientprotocol/claude-agent-acp" },
}

export function allowsPythonPath(harness, key) {
  return key !== "PYTHONPATH" || harness === "hermes"
}

export function launchDiscovery() {
  return { harnesses: listHarnesses() }
}

class LaunchRefusal extends Error {
  constructor(code) { super(code); this.code = code }
}

function pinFor(harness, discovered) {
  const binary = harness === "pi" ? "pi-acp" : harness === "codex" ? "codex-acp" : "claude-agent-acp"
  if (harness === "claude-code") {
    const version = "0.81.2"
    if (!registryIdentityVersionMatches(harness, version) || discovered.harness !== harness
        || discovered.origin !== "agentbox" || discovered.command !== binary
        || discovered.args.length !== 0) throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
    return version
  }
  const spec = MANAGED[harness]
  const packageArg = `--package=${spec.package}@`
  const pinned = discovered.args?.find((arg) => arg.startsWith(packageArg))
  if (discovered.harness !== harness || discovered.origin !== "upstream"
      || !["npx", "npx.cmd"].includes(discovered.command)
      || !pinned || discovered.args.at(-1) !== binary) {
    throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
  }
  const version = pinned.slice(packageArg.length)
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
  return version
}

function onReadOnlyMount(file, mountInfoText = null) {
  if (process.platform !== "linux") return false
  const decoded = (value) => value.replace(/\\([0-7]{3})/g, (_, octal) =>
    String.fromCharCode(Number.parseInt(octal, 8)))
  const rows = (mountInfoText ?? readFileSync("/proc/self/mountinfo", "utf8")).split("\n")
  let best = null
  for (const row of rows) {
    const fields = row.split(" ")
    if (fields.length < 6) continue
    const mountpoint = decoded(fields[4])
    if ((file === mountpoint || file.startsWith(`${mountpoint === "/" ? "" : mountpoint}/`))
        && (!best || mountpoint.length > best.mountpoint.length)) {
      best = { mountpoint, options: fields[5] }
    }
  }
  return best?.options.split(",").includes("ro") === true
}

export function resolveManagedLaunch(harness, launch,
                                     { artifactBase = "/runtime/artifacts", mountInfoText = null } = {}) {
  const spec = MANAGED[harness]
  if (!spec) return null
  const discovered = harnessLaunchContext(harness, { find: () => null })
  const version = pinFor(harness, discovered)
  const artifactRoot = path.join(artifactBase, spec.artifact)
  const artifactEntry = path.join(artifactRoot, "node_modules", spec.package, "dist/index.js")
  if (launch.command === process.execPath && launch.args?.length === 1 && launch.args[0] === artifactEntry) {
    try {
      const root = realpathSync(artifactRoot)
      const entry = realpathSync(artifactEntry)
      const manifestPath = realpathSync(path.join(artifactRoot, "node_modules", spec.package, "package.json"))
      if (!entry.startsWith(`${root}${path.sep}`) || !manifestPath.startsWith(`${root}${path.sep}`)) {
        throw new Error("outside artifact")
      }
      if (![root, entry, manifestPath].every((file) => onReadOnlyMount(file, mountInfoText))) {
        throw new Error("artifact mount is writable")
      }
      const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
      if (manifest.name !== spec.package || manifest.version !== version) throw new Error("pin mismatch")
    } catch { throw new LaunchRefusal("ADAPTER_ARTIFACT_UNVERIFIED") }
    return { command: process.execPath, args: [artifactEntry], source: "managed-artifact", version }
  }
  throw new LaunchRefusal("ADAPTER_LAUNCH_MISMATCH")
}

const LEGACY_ARTIFACTS = {
  dsh: { command: "/usr/bin/node", root: "/runtime/artifacts/dsh-runtime",
    args: ["/runtime/artifacts/dsh-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js", "--profile", "acp"] },
  qwen: { command: "/usr/bin/node", root: "/runtime/artifacts/qwen-runtime",
    args: ["/runtime/artifacts/qwen-runtime/node_modules/@qwen-code/qwen-code/cli-entry.js", "--acp"] },
  kilo: { command: "/runtime/artifacts/kilo-runtime/node_modules/@kilocode/cli-linux-x64-baseline/bin/kilo",
    root: "/runtime/artifacts/kilo-runtime", args: ["acp"] },
}

function sameArgs(actual, expected) {
  return Array.isArray(actual) && actual.length === expected.length
    && actual.every((arg, index) => arg === expected[index])
}

function under(root, file) {
  try { return realpathSync(file).startsWith(`${realpathSync(root)}${path.sep}`) }
  catch { return false }
}

export function resolveLegacyLaunch(harness, launch, environment) {
  const descriptor = harnessLaunchContext(harness, { find: () => null })
  if (descriptor.harness !== harness) throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
  const artifact = LEGACY_ARTIFACTS[harness]
  if (artifact) {
    const routeArgs = artifact.command.startsWith(artifact.root) ? artifact.args : artifact.args.slice(1)
    if (!sameArgs(routeArgs, descriptor.args)) throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
    if (launch.command !== artifact.command || !sameArgs(launch.args ?? [], artifact.args)
        || !under(artifact.root, artifact.args[0].startsWith(artifact.root) ? artifact.args[0] : artifact.command)) {
      throw new LaunchRefusal("ADAPTER_LAUNCH_MISMATCH")
    }
    return { command: artifact.command, args: artifact.args, source: "legacy-artifact-route" }
  }
  if (harness === "hermes") {
    const site = "/runtime/artifacts/hermes-runtime/site-packages"
    if (!sameArgs(descriptor.args, ["acp"])) throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
    if (launch.command !== "/usr/bin/python3" || !sameArgs(launch.args ?? [], ["-m", "hermes_cli.main", "acp"])
        || environment.PYTHONPATH !== site || !under(site, `${site}/hermes_cli/main.py`)) {
      throw new LaunchRefusal("ADAPTER_LAUNCH_MISMATCH")
    }
    return { command: launch.command, args: launch.args, source: "legacy-artifact-route" }
  }
  if (harness === "omp") {
    // Legacy OMP is an upstream native CLI route. Its executable name and argv come from the
    // shared profile, and PATH belongs to the sidecar process owner, not to the renderer frame.
    if (launch.command !== descriptor.command || !sameArgs(launch.args ?? [], descriptor.args)) {
      throw new LaunchRefusal("ADAPTER_LAUNCH_MISMATCH")
    }
    return { command: descriptor.command, args: descriptor.args, source: "legacy-profile-route" }
  }
  throw new LaunchRefusal("ADAPTER_ROUTE_UNBOUND")
}
