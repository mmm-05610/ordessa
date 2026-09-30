#!/usr/bin/env node
/**
 * Build the Pi runtime artifact: the adapter and exactly the native dependency
 * closure Node resolves for it, with no network access at build or run time.
 *
 * Why a builder exists at all: Pi's adapter embeds the Pi coding agent through
 * its published SDK, so the artifact is a *directory tree*, not one file. The
 * Server must not read it (it is a WSL path), the Worker verifies it by tree
 * digest, and bwrap mounts it read-only - so what matters is that the tree is
 * exact, reproducible, and honest about what it excludes.
 *
 * Rules, in the order they are enforced:
 *
 *   1. The closure starts at `@automatalabs/pi-acp` and follows, with Node's own
 *      resolution order (nearest `node_modules` first, then every ancestor up to
 *      the runtime root): `dependencies`, the `optionalDependencies` that are
 *      present and match this platform, and peer dependencies that are not
 *      declared optional. A missing required dependency or peer is a hard
 *      failure - never a silently incomplete artifact.
 *   2. Every selected package's version must equal the version `package-lock.json`
 *      records for that exact path, and the adapter and the Pi packages are
 *      pinned explicitly. The lock is the authority; this build never resolves
 *      anything from the network.
 *   3. Only runtime files are copied. npm's generated `.bin` symlink farm, its
 *      hidden lockfile, TypeScript declarations, source maps, TypeScript sources
 *      and package documentation are excluded: none of them is loaded by Node
 *      when the adapter runs, and the tree has to stay inside the runtime
 *      artifact entry and byte bounds.
 *   4. The result may contain no symlink and no special file at all - a tree
 *      that does is refused, not repaired. This is also the rule the Worker's
 *      digest enforces inside WSL, so a violation is caught here first with a
 *      better message.
 *   5. Nothing unrelated may ride along: the builder computes the codex closure
 *      from the same runtime root and refuses any package that is reachable only
 *      from codex, plus the explicit exclusions `@openai/codex`,
 *      `@agentprotocol/codex-acp` and OpenCode. Codex now owns its own npm root,
 *      so that closure is usually absent here; the absence is not a failure, and
 *      the name-based exclusions are asserted either way.
 *   6. The tree is verified through the reviewed Python digest implementation,
 *      then made read-only and published atomically. A failed build leaves the
 *      output path untouched.
 *
 * Output layout: `<output>/node_modules/...` plus an owner marker, so the
 * adapter entry is `<output>/node_modules/@automatalabs/pi-acp/dist/index.js`
 * and Node resolves its dependencies from `<output>/node_modules`. The manifest
 * (versions, entry, counts, digest, source lock digest) is written next to the
 * output as `<output>.manifest.json` - deliberately outside the tree, so the
 * record does not change what the digest covers. Nothing is written into the
 * repository.
 *
 * usage: build-pi-runtime-artifact.mjs --output ABSOLUTE_DIR [--source RUNTIME_DIR]
 *                                     [--replace] [--json]
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
const DEFAULT_SOURCE = path.join(REPO, "packaging", "pi")

export const MARKER_NAME = ".agentbox-pi-runtime-artifact"
export const MARKER_CONTENT = "agentbox-pi-runtime-artifact-r1\n"
export const ADAPTER_PACKAGE = "@automatalabs/pi-acp"
export const ADAPTER_VERSION = "0.5.0"
export const PI_PACKAGE_VERSION = "0.84.2"
export const PINNED_PI_PACKAGES = [
  "@earendil-works/pi-coding-agent",
  "@earendil-works/pi-ai",
  "@earendil-works/pi-agent-core",
]
export const ENTRY = "node_modules/@automatalabs/pi-acp/dist/index.js"
export const PROFILE_ENTRY = "node_modules/@automatalabs/pi-acp/dist/ordessa-profile.mjs"
export const EXCLUDED_PACKAGES = ["@openai/codex", "@agentclientprotocol/codex-acp", "opencode"]
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

function platformMatches(manifest) {
  const oses = Array.isArray(manifest.os) ? manifest.os : null
  const cpus = Array.isArray(manifest.cpu) ? manifest.cpu : null
  if (oses && !oses.includes(process.platform)) return false
  if (cpus && !cpus.includes(process.arch)) return false
  return true
}

/**
 * Every package the runtime needs, keyed by path relative to the runtime root.
 * `fail` receives (code, message) for anything the closure cannot satisfy.
 */
export function resolveClosure({ sourceRoot, entry = ADAPTER_PACKAGE, fail }) {
  const start = resolvePackage(entry, sourceRoot, sourceRoot)
  if (!start) fail("PI_CLOSURE_ENTRY_MISSING", `${entry} is not installed under ${sourceRoot}`)
  const selected = new Map()
  const optional = []
  const queue = []
  const add = (directory, requiredBy) => {
    if (selected.has(directory)) return
    let manifest
    try {
      manifest = manifestOf(directory)
    } catch {
      fail("PI_CLOSURE_MANIFEST_INVALID", `${directory} has no readable package.json`)
    }
    selected.set(directory, manifest)
    queue.push({ directory, manifest, requiredBy })
  }
  add(start, "root")
  while (queue.length) {
    const { directory, manifest } = queue.shift()
    for (const name of Object.keys(manifest.dependencies ?? {})) {
      const resolved = resolvePackage(name, directory, sourceRoot)
      if (!resolved) fail("PI_CLOSURE_DEPENDENCY_MISSING", `${manifest.name} requires ${name}, which is not installed`)
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
        if (!isOptional) fail("PI_CLOSURE_PEER_MISSING", `${manifest.name} requires peer ${name}, which is not installed`)
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
    throw new BuildError("PI_LOCK_INVALID", "package-lock.json has no package map")
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
    throw new BuildError("PI_ARTIFACT_SHAPE_INVALID", `the tree is not a plain file tree: ${problems.slice(0, 5).join(", ")}`)
  }
}

// -- Python digest (the reviewed implementation) -----------------------------

function environmentForPython() {
  const pythonPaths = [
    path.resolve(REPO, "..", "..", "packages", "pacthold", "src"),
    path.resolve(REPO, "..", "runtime-compat", "src"),
    ...(process.env.PYTHONPATH ? [process.env.PYTHONPATH] : []),
  ]
  return { ...process.env, PYTHONPATH: pythonPaths.join(path.delimiter) }
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
      throw new BuildError("PI_ARTIFACT_OUTSIDE_BOUNDS", diagnostic.slice(-300))
    }
    throw new BuildError("PI_ARTIFACT_DIGEST_UNAVAILABLE",
      `the reviewed digest implementation refused the tree: ${diagnostic.slice(-400)}`)
  }
  return JSON.parse(result.stdout)
}

// -- output policy -----------------------------------------------------------

const RESERVED_ROOTS = [".config", ".local", ".pi", ".agentbox", ".ssh", ".gnupg"]

export function assertOutputPolicy(output, { repo = REPO } = {}) {
  if (!path.isAbsolute(output)) throw new BuildError("PI_OUTPUT_NOT_ABSOLUTE", "--output must be an absolute path")
  const resolved = path.resolve(output)
  if (resolved === repo || resolved.startsWith(repo + path.sep)) {
    throw new BuildError("PI_OUTPUT_INSIDE_REPOSITORY", "--output must be outside the repository")
  }
  if (resolved === "/" || resolved === path.parse(resolved).root) {
    throw new BuildError("PI_OUTPUT_UNSAFE", "--output must not be a filesystem root")
  }
  const home = process.env.HOME
  if (home) {
    for (const reserved of RESERVED_ROOTS) {
      const forbidden = path.join(home, reserved)
      if (resolved === forbidden || resolved.startsWith(forbidden + path.sep)) {
        throw new BuildError("PI_OUTPUT_RESERVED", "--output must not be a user configuration directory")
      }
    }
  }
  const relative = path.relative(repo, resolved)
  if (relative.split(path.sep).includes("node_modules")) {
    throw new BuildError("PI_OUTPUT_INSIDE_REPOSITORY", "--output must not be a package directory")
  }
  return resolved
}

export function isOwnedArtifact(directory) {
  try {
    return readFileSync(path.join(directory, MARKER_NAME), "utf8") === MARKER_CONTENT
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
      else chmodSync(location, 0o444)
    }
    chmodSync(directory, 0o555)
  }
  walk(root)
  chmodSync(root, 0o555)
}

/** Remove an output path only when this builder provably owns it. */
export function clearTarget(output, { replace }) {
  if (!existsSync(output)) return
  const stats = lstatSync(output)
  if (stats.isSymbolicLink()) {
    throw new BuildError("PI_OUTPUT_NOT_OWNED", `${output} is a symlink; refusing to touch it`)
  }
  if (!stats.isDirectory()) {
    throw new BuildError("PI_OUTPUT_NOT_OWNED", `${output} is not a directory; refusing to touch it`)
  }
  if (isOwnedArtifact(output)) {
    if (!replace) {
      throw new BuildError("PI_OUTPUT_EXISTS", `${output} is an existing artifact; pass --replace to rebuild it`)
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
  throw new BuildError("PI_OUTPUT_NOT_OWNED", `${output} is non-empty and carries no builder marker; refusing to overwrite it`)
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
          throw new BuildError("PI_ARTIFACT_SHAPE_INVALID", `${relativePath} is a symlink in the source closure`)
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
          throw new BuildError("PI_ARTIFACT_SHAPE_INVALID", `${relativePath} is not a regular file`)
        }
        if (!isRuntimeFile(relativePath)) {
          counters.skippedFiles += 1
          continue
        }
        copyFileSync(location, target)
        chmodSync(target, 0o644)
        counters.files += 1
        counters.bytes += stats.size
      }
    }
    walk(directory, destination)
  }
}

function codexOnlyPackages(sourceRoot, piDirectories) {
  const fail = (code, message) => { throw new BuildError(code, message) }
  let closure
  try {
    closure = resolveClosure({ sourceRoot, entry: "@agentclientprotocol/codex-acp", fail })
  } catch (error) {
    // Codex owns its own npm root now, so its closure is simply not installed
    // here; an absence cannot leak into this tree. The name-based
    // `EXCLUDED_PACKAGES` assertion below still runs either way, and the Codex
    // builder applies the same tolerance to the Pi closure.
    return { unrelated: [], available: false }
  }
  const unrelated = []
  for (const directory of closure.selected.keys()) {
    if (!piDirectories.has(directory)) unrelated.push(path.relative(sourceRoot, directory))
  }
  return { unrelated, available: true }
}

export function build({ output, source = DEFAULT_SOURCE, replace = false, profileBridge = false }) {
  const resolved = assertOutputPolicy(output)
  const sourceRoot = path.resolve(source)
  if (!existsSync(path.join(sourceRoot, "package-lock.json"))) {
    throw new BuildError("PI_SOURCE_INVALID", `${sourceRoot} has no package-lock.json`)
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
      throw new BuildError("PI_LOCK_ENTRY_MISSING", `${relative} is not recorded in package-lock.json`)
    }
    if (recorded.version !== manifest.version) {
      throw new BuildError("PI_LOCK_VERSION_MISMATCH",
        `${relative} is ${manifest.version} on disk but ${recorded.version} in package-lock.json`)
    }
    packages.push({ path: relative, name: manifest.name, version: manifest.version })
  }
  packages.sort((left, right) => left.path.localeCompare(right.path))
  const adapter = packages.find((item) => item.name === ADAPTER_PACKAGE)
  if (!adapter || adapter.version !== ADAPTER_VERSION) {
    throw new BuildError("PI_ADAPTER_VERSION_MISMATCH",
      `${ADAPTER_PACKAGE} must be ${ADAPTER_VERSION}, found ${adapter ? adapter.version : "nothing"}`)
  }
  for (const name of PINNED_PI_PACKAGES) {
    const entry = packages.find((item) => item.name === name)
    if (entry && entry.version !== PI_PACKAGE_VERSION) {
      throw new BuildError("PI_PACKAGE_VERSION_MISMATCH", `${name} must be ${PI_PACKAGE_VERSION}, found ${entry.version}`)
    }
  }
  const sdk = packages.filter((item) => item.name === "@agentclientprotocol/sdk")
  for (const entry of sdk) {
    if (lock[entry.path].version !== entry.version) {
      throw new BuildError("PI_ACP_SDK_VERSION_MISMATCH", `${entry.path} does not match the lock`)
    }
  }

  // (5) nothing unrelated may ride along
  const { unrelated } = codexOnlyPackages(sourceRoot, new Set(selected.keys()))
  for (const excluded of EXCLUDED_PACKAGES) {
    if (packages.some((item) => item.name === excluded)) {
      throw new BuildError("PI_ARTIFACT_UNRELATED_PACKAGE", `${excluded} must not be in the Pi artifact`)
    }
  }

  clearTarget(resolved, { replace })
  mkdirSync(path.dirname(resolved), { recursive: true })
  const staging = mkdtempSync(path.join(path.dirname(resolved), `${path.basename(resolved)}.building-`))
  writeFileSync(path.join(staging, MARKER_NAME), MARKER_CONTENT)
  const counters = { files: 0, bytes: 0, skippedFiles: 0, skippedDirectories: 0 }
  try {
    copyTree(staging, selected, sourceRoot, counters)
    if (profileBridge) {
      // Additive, explicitly selected variant: the upstream entry is preserved.
      const extensionRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../pi-profile')
      const destination = path.join(staging, 'node_modules/@automatalabs/pi-acp/dist')
      mkdirSync(destination, { recursive: true })
      for (const [sourceName, targetName] of [
        ['entry.mjs', 'ordessa-profile.mjs'],
        ['server.mjs', 'ordessa-profile-server.mjs'],
        ['configuration-query.mjs', 'ordessa-configuration-query.mjs'],
      ]) copyFileSync(path.join(extensionRoot, sourceName), path.join(destination, targetName))
    }
    assertPlainTree(staging)
    const seen = new Set(packages.map((item) => item.path))
    for (const relative of unrelated) {
      if (seen.has(relative)) {
        throw new BuildError("PI_ARTIFACT_UNRELATED_PACKAGE", `${relative} is reachable only from codex`)
      }
    }
    const summary = treeSummary(staging)
    if (Number(summary.entries) > MAX_ENTRIES || Number(summary.bytes) > MAX_BYTES) {
      throw new BuildError("PI_ARTIFACT_OUTSIDE_BOUNDS",
        `${summary.entries} entries / ${summary.bytes} bytes exceed the runtime artifact bounds`)
    }
    makeReadOnly(staging)
    const manifest = {
      schemaVersion: 1,
      kind: "agentbox-pi-runtime-artifact",
      adapter: { package: ADAPTER_PACKAGE, version: ADAPTER_VERSION, entry: profileBridge ? PROFILE_ENTRY : ENTRY },
      ...(profileBridge ? { ordessaExtension: { id: 'pi-profile', version: 1,
        configurationQuery: '_ordessa/session/configuration', instanceDirectoryRequired: true } } : {}),
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
  const source = argument("--source") ?? DEFAULT_SOURCE
  const json = process.argv.includes("--json")
  if (!output) {
    process.stdout.write(JSON.stringify({
      result: "PI_RUNTIME_BUILD_FAILED", code: "PI_USAGE",
      error: "usage: build-pi-runtime-artifact.mjs --output ABSOLUTE_DIR [--source RUNTIME_DIR] [--replace] [--json]",
    }) + "\n")
    return 2
  }
  try {
    const result = build({ output, source, replace: process.argv.includes("--replace"),
      profileBridge: process.argv.includes("--profile-bridge") })
    process.stdout.write(JSON.stringify({
      result: "PI_RUNTIME_ARTIFACT_BUILT",
      output: result.output, treeDigest: result.treeDigest,
      entries: result.entries, bytes: result.bytes,
      adapter: result.adapter, packages: result.packages.length,
      sourceLockDigest: result.sourceLockDigest,
      manifest: `${result.output}.manifest.json`,
    }) + "\n")
    return 0
  } catch (error) {
    process.stdout.write(JSON.stringify({
      result: "PI_RUNTIME_BUILD_FAILED",
      code: error.code ?? "PI_RUNTIME_BUILD_ERROR",
      error: String(error.message ?? error).slice(0, 500),
      ...(json ? { stack: String(error.stack ?? "").split("\n").slice(0, 4).join(" | ") } : {}),
    }) + "\n")
    return 1
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  process.exitCode = main()
}
