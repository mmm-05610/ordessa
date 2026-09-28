#!/usr/bin/env node
/**
 * Build the claude runtime artifact: the Claude Code ACP adapter and exactly
 * the native dependency closure Node resolves for it - including Anthropic's
 * platform CLI binary package for this platform - with no network access at
 * build or run time.
 *
 * Work Order 43 clone of the reviewed dsh/Pi builders with two claude-specific
 * additions, both structural facts about the closure rather than shortcuts:
 *
 *   1. `EXECUTABLE_FILES`: the SDK's platform package ships a native CLI
 *      binary (`claude`), which the SDK spawns directly. The tree is published
 *      read-only, so those files are published 0555 instead of 0644 - without
 *      the execute bit the artifact would be a complete but unrunnable tree.
 *   2. `libcMatches()`: the SDK declares same-os/cpu packages for both glibc
 *      and musl; os/cpu matching alone would copy both ~224 MB binaries. The
 *      build machine's libc (from `process.report`) selects one, exactly the
 *      rule npm itself applies.
 *
 * The source root is `packaging/claude/`, deliberately separate from the shared
 * `runtime/`: the adapter needs `@agentclientprotocol/sdk` 1.4.x and the shared
 * root pins 1.3.0 for the four integrated families.
 *
 * License boundary (recorded in the family packaging doc): the adapter is
 * Apache-2.0; `@anthropic-ai/claude-agent-sdk` and its platform binaries are
 * Anthropic proprietary ("All rights reserved", Commercial ToS). This build
 * installs and runs them unmodified for internal use; it does not redistribute
 * them.
 *
 * usage: build-claude-runtime-artifact.mjs --output ABSOLUTE_DIR [--source RUNTIME_DIR]
 *                                       [--legacy-alias] [--replace] [--json]
 */
import { createHash } from "node:crypto"
import { spawnSync } from "node:child_process"
import {
  chmodSync, copyFileSync, existsSync, lstatSync, mkdirSync, mkdtempSync,
  readFileSync, readdirSync, renameSync, rmdirSync, rmSync, writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
const DEFAULT_SOURCE = path.join(REPO, "packaging", "claude")
const LEGACY_SOURCE = path.join(REPO, "packaging", "claude-legacy")

export const MARKER_NAME = ".agentbox-claude-runtime-artifact"
export const MARKER_CONTENT = "agentbox-claude-runtime-artifact-r1\n"
export const ADAPTER_PACKAGE = "@agentclientprotocol/claude-agent-acp"
export const ADAPTER_VERSION = "0.81.2"
export const LEGACY_ADAPTER_VERSION = "0.75.1"
const LEGACY_MARKER_NAME = ".ordessa-claude-legacy-runtime-artifact"
const LEGACY_MARKER_CONTENT = "ordessa-claude-legacy-runtime-artifact-r1\n"
export const EXCLUDED_ADAPTERS = [
  "@automatalabs/pi-acp",
  "@agentclientprotocol/codex-acp",
  "@deepseek-ai/dsh",
  "opencode",
  "@openai/codex",
]
export const EXECUTABLE_FILES = new Set([
  "node_modules/@anthropic-ai/claude-agent-sdk-linux-x64/claude",
])
export const ENTRY = "node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js"
export const EXCLUDED_PACKAGES = EXCLUDED_ADAPTERS
//: Entries (directories included) and bytes the runtime artifact contract allows.
export const MAX_ENTRIES = 32768
export const MAX_BYTES = 1024 * 1024 * 1024

class BuildError extends Error {
  constructor(code, message) {
    super(`${code}: ${message}`)
    this.code = code
  }
}

// -- closure resolution ------------------------------------------------------

/** Node's lookup order, bounded to the runtime root the build is allowed to read. */
export function resolvePackage(name, fromDirectory, sourceRoot) {
  let current = fromDirectory
  while (true) {
    const candidate = path.join(current, "node_modules", name)
    if (existsSync(path.join(candidate, "package.json"))) return candidate
    if (current === sourceRoot) return null
    const parent = path.dirname(current)
    if (parent === current || !current.startsWith(sourceRoot)) return null
    current = parent
  }
}

function manifestOf(directory) {
  return JSON.parse(readFileSync(path.join(directory, "package.json"), "utf8"))
}

function buildLibc() {
  // glibc vs musl, once: `process.report` carries the loader family on Linux.
  // A platform that cannot report falls back to "unknown", which disables the
  // libc filter rather than guessing.
  try {
    const header = process.report?.getReport?.()?.header ?? {}
    if (typeof header.glibcVersionRuntime === "string") return "glibc"
  } catch {
    // Fall through to "unknown".
  }
  return "unknown"
}
const BUILD_LIBC = buildLibc()

function platformMatches(manifest) {
  const oses = Array.isArray(manifest.os) ? manifest.os : null
  const cpus = Array.isArray(manifest.cpu) ? manifest.cpu : null
  if (oses && !oses.includes(process.platform)) return false
  if (cpus && !cpus.includes(process.arch)) return false
  const libcs = Array.isArray(manifest.libc) ? manifest.libc : null
  if (libcs && BUILD_LIBC !== "unknown" && !libcs.includes(BUILD_LIBC)) return false
  return true
}

/**
 * Every package the runtime needs, keyed by path relative to the runtime root.
 * `fail` receives (code, message) for anything the closure cannot satisfy.
 */
export function resolveClosure({ sourceRoot, entry = ADAPTER_PACKAGE, fail }) {
  const start = resolvePackage(entry, sourceRoot, sourceRoot)
  if (!start) fail("CLAUDE_CLOSURE_ENTRY_MISSING", `${entry} is not installed under ${sourceRoot}`)
  const selected = new Map()
  const optional = []
  const queue = []
  const add = (directory, requiredBy) => {
    if (selected.has(directory)) return
    let manifest
    try {
      manifest = manifestOf(directory)
    } catch {
      fail("CLAUDE_CLOSURE_MANIFEST_INVALID", `${directory} has no readable package.json`)
    }
    selected.set(directory, manifest)
    queue.push({ directory, manifest, requiredBy })
  }
  add(start, "root")
  while (queue.length) {
    const { directory, manifest } = queue.shift()
    for (const name of Object.keys(manifest.dependencies ?? {})) {
      const resolved = resolvePackage(name, directory, sourceRoot)
      if (!resolved) fail("CLAUDE_CLOSURE_DEPENDENCY_MISSING", `${manifest.name} requires ${name}, which is not installed`)
      add(resolved, manifest.name)
    }
    for (const name of Object.keys(manifest.optionalDependencies ?? {})) {
      const resolved = resolvePackage(name, directory, sourceRoot)
      if (!resolved) {
        optional.push({ by: manifest.name, name, reason: "not-installed" })
        continue
      }
      if (!platformMatches(manifestOf(resolved))) {
        optional.push({ by: manifest.name, name, reason: "platform" })
        continue
      }
      add(resolved, `${manifest.name} (optional)`)
    }
    for (const name of Object.keys(manifest.peerDependencies ?? {})) {
      const resolved = resolvePackage(name, directory, sourceRoot)
      const isOptional = manifest.peerDependenciesMeta?.[name]?.optional === true
      if (!resolved) {
        if (!isOptional) fail("CLAUDE_CLOSURE_PEER_MISSING", `${manifest.name} requires peer ${name}, which is not installed`)
        optional.push({ by: manifest.name, name, reason: "optional-peer" })
        continue
      }
      add(resolved, `${manifest.name} (peer)`)
    }
  }
  return { selected, optional }
}

function versionsFromLock(sourceRoot) {
  const lock = JSON.parse(readFileSync(path.join(sourceRoot, "package-lock.json"), "utf8"))
  if (!lock || typeof lock.packages !== "object") {
    throw new BuildError("CLAUDE_LOCK_INVALID", "package-lock.json has no package map")
  }
  return lock.packages
}

// -- copy rules --------------------------------------------------------------

const EXCLUDED_DIRECTORIES = new Set([".bin", "docs", "examples"])
const EXCLUDED_FILES = new Set([".package-lock.json", "package-lock.json"])

/** True for the files a running Node adapter never loads. */
export function isRuntimeFile(relativePath) {
  const segments = relativePath.split("/")
  if (segments.some((segment) => EXCLUDED_DIRECTORIES.has(segment))) return false
  const base = segments[segments.length - 1]
  if (EXCLUDED_FILES.has(base)) return false
  if (/\.d\.ts$/.test(base)) return false
  if (/\.(js|mjs|cjs|d\.ts)\.map$/.test(base)) return false
  if (/\.(ts|tsx|mts|cts)$/.test(base)) return false
  if (/\.md$/.test(base) || /\.markdown$/.test(base)) return false
  return true
}

function assertPlainTree(root) {
  const problems = []
  const walk = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const location = path.join(directory, entry.name)
      const stats = lstatSync(location)
      const relative = path.relative(root, location)
      if (stats.isSymbolicLink()) problems.push(`symlink ${relative}`)
      else if (stats.isDirectory()) {
        if (entry.name === ".bin") problems.push(`bin-directory ${relative}`)
        walk(location)
      } else if (!stats.isFile()) problems.push(`special ${relative}`)
    }
  }
  walk(root)
  if (problems.length) {
    throw new BuildError("CLAUDE_ARTIFACT_SHAPE_INVALID", `the tree is not a plain file tree: ${problems.slice(0, 5).join(", ")}`)
  }
}

// -- Python digest (the reviewed implementation) -----------------------------

function environmentForPython() {
  const existing = process.env.PYTHONPATH ? `:${process.env.PYTHONPATH}` : ""
  return { ...process.env, PYTHONPATH: `${path.join(REPO, "..", "runtime-compat", "src")}${existing}` }
}

export function treeSummary(directory) {
  const program = [
    "import json, sys",
    "from pacthold_runtime_compat.resource_contracts.runtime_artifacts import runtime_artifact_tree_summary as summary",
    "print(json.dumps(summary(sys.argv[1])))",
  ].join("; ")
  const result = spawnSync("python3", ["-c", program, directory], {
    env: environmentForPython(), encoding: "utf8",
  })
  if (result.status !== 0) {
    const diagnostic = `${result.stderr ?? ""}`.trim()
    // The reviewed implementation owns the bounds; report its refusal as the
    // bound it is, and only fall back to "unavailable" for anything else.
    if (diagnostic.includes("RUNTIME_ARTIFACT_OUTSIDE_BOUNDS")) {
      throw new BuildError("CLAUDE_ARTIFACT_OUTSIDE_BOUNDS", diagnostic.slice(-300))
    }
    throw new BuildError("CLAUDE_ARTIFACT_DIGEST_UNAVAILABLE",
      `the reviewed digest implementation refused the tree: ${diagnostic.slice(-400)}`)
  }
  return JSON.parse(result.stdout)
}

// -- output policy -----------------------------------------------------------

const RESERVED_ROOTS = [".config", ".local", ".pi", ".agentbox", ".ssh", ".gnupg"]

export function assertOutputPolicy(output, { repo = REPO } = {}) {
  if (!path.isAbsolute(output)) throw new BuildError("CLAUDE_OUTPUT_NOT_ABSOLUTE", "--output must be an absolute path")
  const resolved = path.resolve(output)
  if (resolved === repo || resolved.startsWith(repo + path.sep)) {
    throw new BuildError("CLAUDE_OUTPUT_INSIDE_REPOSITORY", "--output must be outside the repository")
  }
  if (resolved === "/" || resolved === path.parse(resolved).root) {
    throw new BuildError("CLAUDE_OUTPUT_UNSAFE", "--output must not be a filesystem root")
  }
  const home = process.env.HOME
  if (home) {
    for (const reserved of RESERVED_ROOTS) {
      const forbidden = path.join(home, reserved)
      if (resolved === forbidden || resolved.startsWith(forbidden + path.sep)) {
        throw new BuildError("CLAUDE_OUTPUT_RESERVED", "--output must not be a user configuration directory")
      }
    }
  }
  const relative = path.relative(repo, resolved)
  if (relative.split(path.sep).includes("node_modules")) {
    throw new BuildError("CLAUDE_OUTPUT_INSIDE_REPOSITORY", "--output must not be a package directory")
  }
  return resolved
}

export function isOwnedArtifact(directory, { markerName = MARKER_NAME, markerContent = MARKER_CONTENT } = {}) {
  try {
    return readFileSync(path.join(directory, markerName), "utf8") === markerContent
  } catch {
    return false
  }
}

function makeWritable(root) {
  const walk = (directory) => {
    chmodSync(directory, 0o755)
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const location = path.join(directory, entry.name)
      if (entry.isDirectory()) walk(location)
      else chmodSync(location, 0o644)
    }
  }
  walk(root)
}

function makeReadOnly(root) {
  const walk = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const location = path.join(directory, entry.name)
      if (entry.isDirectory()) walk(location)
      else {
        const relativeEntry = path.relative(root, location).split(path.sep).join("/")
        chmodSync(location, EXECUTABLE_FILES.has(relativeEntry) ? 0o555 : 0o444)
      }
    }
    chmodSync(directory, 0o555)
  }
  walk(root)
  chmodSync(root, 0o555)
}

/** Remove an output path only when this builder provably owns it. */
export function clearTarget(output, { replace, markerName = MARKER_NAME, markerContent = MARKER_CONTENT }) {
  if (!existsSync(output)) return
  const stats = lstatSync(output)
  if (stats.isSymbolicLink()) {
    throw new BuildError("CLAUDE_OUTPUT_NOT_OWNED", `${output} is a symlink; refusing to touch it`)
  }
  if (!stats.isDirectory()) {
    throw new BuildError("CLAUDE_OUTPUT_NOT_OWNED", `${output} is not a directory; refusing to touch it`)
  }
  if (isOwnedArtifact(output, { markerName, markerContent })) {
    if (!replace) {
      throw new BuildError("CLAUDE_OUTPUT_EXISTS", `${output} is an existing artifact; pass --replace to rebuild it`)
    }
    makeWritable(output)
    rmSync(output, { recursive: true, force: true })
    return
  }
  if (readdirSync(output).length === 0) {
    // An empty directory is not a tree we would have to destroy recursively.
    rmdirSync(output)
    return
  }
  throw new BuildError("CLAUDE_OUTPUT_NOT_OWNED", `${output} is non-empty and carries no builder marker; refusing to overwrite it`)
}

// -- build -------------------------------------------------------------------

function copyTree(root, selected, sourceRoot, counters) {
  for (const directory of selected.keys()) {
    const relative = path.relative(sourceRoot, directory)
    const destination = path.join(root, relative)
    const walk = (from, to) => {
      mkdirSync(to, { recursive: true })
      for (const entry of readdirSync(from, { withFileTypes: true })) {
        const location = path.join(from, entry.name)
        const stats = lstatSync(location)
        const target = path.join(to, entry.name)
        const relativePath = path.relative(root, target)
        if (stats.isSymbolicLink()) {
          throw new BuildError("CLAUDE_ARTIFACT_SHAPE_INVALID", `${relativePath} is a symlink in the source closure`)
        }
        if (stats.isDirectory()) {
          if (EXCLUDED_DIRECTORIES.has(entry.name)) {
            counters.skippedDirectories += 1
            continue
          }
          walk(location, target)
          continue
        }
        if (!stats.isFile()) {
          throw new BuildError("CLAUDE_ARTIFACT_SHAPE_INVALID", `${relativePath} is not a regular file`)
        }
        if (!isRuntimeFile(relativePath)) {
          counters.skippedFiles += 1
          continue
        }
        copyFileSync(location, target)
        // The native CLI binary is spawned directly and the tree is published
        // read-only, so its execute bit must be part of the published artifact.
        chmodSync(target, EXECUTABLE_FILES.has(relativePath) ? 0o555 : 0o644)
        counters.files += 1
        counters.bytes += stats.size
      }
    }
    walk(directory, destination)
  }
}

/**
 * The separate runtime root must not carry another family's adapter at all:
 * the exclusion is structural (not installed), not a walk-away check.
 */
function assertNoForeignAdapters(sourceRoot) {
  for (const name of EXCLUDED_ADAPTERS) {
    if (resolvePackage(name, sourceRoot, sourceRoot)) {
      throw new BuildError("CLAUDE_ARTIFACT_UNRELATED_PACKAGE",
        `${name} must not be installed in the dsh runtime root`)
    }
  }
}

export function build({ output, source, replace = false, variant = "canonical" }) {
  if (!["canonical", "legacy-alias"].includes(variant)) {
    throw new BuildError("CLAUDE_VARIANT_INVALID", "unsupported Claude artifact variant")
  }
  const legacy = variant === "legacy-alias"
  source ??= legacy ? LEGACY_SOURCE : DEFAULT_SOURCE
  const version = legacy ? LEGACY_ADAPTER_VERSION : ADAPTER_VERSION
  const markerName = legacy ? LEGACY_MARKER_NAME : MARKER_NAME
  const markerContent = legacy ? LEGACY_MARKER_CONTENT : MARKER_CONTENT
  const resolved = assertOutputPolicy(output)
  const sourceRoot = path.resolve(source)
  if (!existsSync(path.join(sourceRoot, "package-lock.json"))) {
    throw new BuildError("CLAUDE_SOURCE_INVALID", `${sourceRoot} has no package-lock.json`)
  }
  const lock = versionsFromLock(sourceRoot)
  const fail = (code, message) => { throw new BuildError(code, message) }
  const { selected, optional } = resolveClosure({ sourceRoot, fail })

  // (2) every selected package must be exactly what the lock records
  const packages = []
  for (const [directory, manifest] of selected) {
    const relative = path.relative(sourceRoot, directory).split(path.sep).join("/")
    const recorded = lock[relative]
    if (!recorded) {
      throw new BuildError("CLAUDE_LOCK_ENTRY_MISSING", `${relative} is not recorded in package-lock.json`)
    }
    if (recorded.version !== manifest.version) {
      throw new BuildError("CLAUDE_LOCK_VERSION_MISMATCH",
        `${relative} is ${manifest.version} on disk but ${recorded.version} in package-lock.json`)
    }
    packages.push({ path: relative, name: manifest.name, version: manifest.version })
  }
  packages.sort((left, right) => left.path.localeCompare(right.path))
  const adapter = packages.find((item) => item.name === ADAPTER_PACKAGE)
  if (!adapter || adapter.version !== version) {
    throw new BuildError("CLAUDE_ADAPTER_VERSION_MISMATCH",
      `${ADAPTER_PACKAGE} must be ${version}, found ${adapter ? adapter.version : "nothing"}`)
  }
  const sdk = packages.filter((item) => item.name === "@agentclientprotocol/sdk")
  for (const entry of sdk) {
    if (lock[entry.path].version !== entry.version) {
      throw new BuildError("CLAUDE_ACP_SDK_VERSION_MISMATCH", `${entry.path} does not match the lock`)
    }
  }

  // (5) nothing unrelated may ride along
  assertNoForeignAdapters(sourceRoot)
  const unrelated = []
  for (const excluded of EXCLUDED_PACKAGES) {
    if (packages.some((item) => item.name === excluded)) {
      throw new BuildError("CLAUDE_ARTIFACT_UNRELATED_PACKAGE", `${excluded} must not be in the Pi artifact`)
    }
  }

  clearTarget(resolved, { replace, markerName, markerContent })
  mkdirSync(path.dirname(resolved), { recursive: true })
  const staging = mkdtempSync(path.join(path.dirname(resolved), `${path.basename(resolved)}.building-`))
  writeFileSync(path.join(staging, markerName), markerContent)
  const counters = { files: 0, bytes: 0, skippedFiles: 0, skippedDirectories: 0 }
  try {
    copyTree(staging, selected, sourceRoot, counters)
    assertPlainTree(staging)
    const seen = new Set(packages.map((item) => item.path))
    for (const relative of unrelated) {
      if (seen.has(relative)) {
        throw new BuildError("CLAUDE_ARTIFACT_UNRELATED_PACKAGE", `${relative} is reachable only from codex`)
      }
    }
    const summary = treeSummary(staging)
    if (Number(summary.entries) > MAX_ENTRIES || Number(summary.bytes) > MAX_BYTES) {
      throw new BuildError("CLAUDE_ARTIFACT_OUTSIDE_BOUNDS",
        `${summary.entries} entries / ${summary.bytes} bytes exceed the runtime artifact bounds`)
    }
    makeReadOnly(staging)
    const manifest = {
      schemaVersion: 1,
      kind: legacy ? "ordessa-claude-legacy-runtime-artifact" : "agentbox-claude-runtime-artifact",
      adapter: { package: ADAPTER_PACKAGE, version, entry: ENTRY },
      packages: packages.map((item) => ({
        path: item.path,
        name: item.name,
        version: item.version,
        optional: (lock[item.path]?.optional === true) || undefined,
      })),
      excluded: {
        packages: EXCLUDED_PACKAGES,
        codexOnlyPackages: unrelated,
        directories: [...EXCLUDED_DIRECTORIES].sort(),
        files: [...EXCLUDED_FILES].sort(),
        rules: ["d.ts", "source-maps", "typescript-sources", "documentation"],
        skippedFiles: counters.skippedFiles,
        skippedDirectories: counters.skippedDirectories,
      },
      optionalSkipped: optional.sort((left, right) =>
        `${left.by}:${left.name}`.localeCompare(`${right.by}:${right.name}`)),
      entries: Number(summary.entries),
      bytes: Number(summary.bytes),
      treeDigest: summary.digest,
      sourceLockDigest: "sha256:" + createHash("sha256")
        .update(readFileSync(path.join(sourceRoot, "package-lock.json"))).digest("hex"),
    }
    // Published before the manifest exists at its final name, so a reader never
    // sees a manifest for a tree that is not there yet.
    renameSync(staging, resolved)
    writeFileSync(`${resolved}.manifest.json`, JSON.stringify(manifest, null, 2) + "\n")
    return { ...manifest, output: resolved, source: sourceRoot }
  } catch (error) {
    if (existsSync(staging)) {
      try {
        makeWritable(staging)
        rmSync(staging, { recursive: true, force: true })
      } catch {
        // The staging tree carries the marker; leaving it is recoverable.
      }
    }
    throw error
  }
}

function argument(name) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : undefined
}

function main() {
  const output = argument("--output")
  const source = argument("--source")
  const variant = process.argv.includes("--legacy-alias") ? "legacy-alias" : "canonical"
  const json = process.argv.includes("--json")
  if (!output) {
    process.stdout.write(JSON.stringify({
      result: "CLAUDE_RUNTIME_BUILD_FAILED", code: "CLAUDE_USAGE",
      error: "usage: build-claude-runtime-artifact.mjs --output ABSOLUTE_DIR [--source RUNTIME_DIR] [--legacy-alias] [--replace] [--json]",
    }) + "\n")
    return 2
  }
  try {
    const result = build({ output, source, variant, replace: process.argv.includes("--replace") })
    process.stdout.write(JSON.stringify({
      result: "CLAUDE_RUNTIME_ARTIFACT_BUILT",
      output: result.output, treeDigest: result.treeDigest,
      entries: result.entries, bytes: result.bytes,
      adapter: result.adapter, packages: result.packages.length,
      sourceLockDigest: result.sourceLockDigest,
      manifest: `${result.output}.manifest.json`,
    }) + "\n")
    return 0
  } catch (error) {
    process.stdout.write(JSON.stringify({
      result: "CLAUDE_RUNTIME_BUILD_FAILED",
      code: error.code ?? "CLAUDE_RUNTIME_BUILD_ERROR",
      error: String(error.message ?? error).slice(0, 500),
      ...(json ? { stack: String(error.stack ?? "").split("\n").slice(0, 4).join(" | ") } : {}),
    }) + "\n")
    return 1
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  process.exitCode = main()
}
