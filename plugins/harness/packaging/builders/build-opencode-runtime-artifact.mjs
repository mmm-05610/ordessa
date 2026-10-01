#!/usr/bin/env node
/**
 * Build the OpenCode runtime artifact: the pinned OpenCode ACP entry and the one
 * platform-native binary it actually executes, with no network access at build
 * or run time.
 *
 * This is Work Order 43's family convention applied to OpenCode, but it is NOT a
 * faithful clone of the dsh/kilo builders, because OpenCode is a different shape
 * and pretending otherwise would hide the difference that matters:
 *
 *   - `opencode-ai` declares no library entry at all. Its `bin` points at
 *     `bin/opencode.exe`, and that file is not a launcher script: it is the
 *     184 MB native ELF itself, which the package's `postinstall.mjs` copies
 *     (hardlinks) into place from the platform package. Measured on this tree,
 *     `opencode-ai/bin/opencode.exe` and `opencode-linux-x64/bin/opencode` are
 *     the same inode (BuildID c30f169b1bef81fa57467cd091ba53aab5235468).
 *   - `os`/`cpu` matching is therefore NOT enough to pick a platform package.
 *     On linux/x64 npm materialises FOUR of the optional packages -- plain,
 *     `-musl`, `-baseline` and `-baseline-musl` -- because all four declare the
 *     same os/cpu and differ only in libc and CPU baseline. The dsh/kilo
 *     `platformMatches()` would select all four and ship ~724 MB of which three
 *     copies cannot run here. So the platform package is PINNED, never inferred.
 *   - The executed artifact is a native binary, so this builder records its
 *     sha256 in the manifest. Whether the installed-asset verifier should trust
 *     that shape is an open security ruling and is NOT decided here; what this
 *     builder does is make the facts available to whichever variant is approved.
 *
 * The `postinstall` is deliberately NOT run by this builder. It has already run
 * (npm ci performed it); the builder verifies the resulting entry rather than
 * re-executing install-time code, and fails with a typed code if it is absent.
 *
 * usage: build-opencode-runtime-artifact.mjs --output ABSOLUTE_DIR [--source RUNTIME_DIR]
 *                                         [--replace] [--json]
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
const DEFAULT_SOURCE = path.join(REPO, "packaging", "opencode")

export const MARKER_NAME = ".agentbox-opencode-runtime-artifact"
export const MARKER_CONTENT = "agentbox-opencode-runtime-artifact-r1\n"
export const ADAPTER_PACKAGE = "opencode-ai"
export const ADAPTER_VERSION = "1.18.21"

/** The one platform package this artifact is allowed to carry, pinned not inferred. */
export const TARGET_PLATFORM = {
  os: "linux", cpu: "x64", libc: "glibc",
  package: "opencode-linux-x64", version: "1.18.21",
}

/**
 * Every sibling OpenCode ships that must NOT ride along. On linux/x64 these are
 * installed by npm and differ only by libc/CPU baseline, so excluding them is a
 * policy decision this builder makes explicitly rather than by accident.
 */
export const EXCLUDED_PLATFORM_PACKAGES = [
  "opencode-darwin-arm64", "opencode-darwin-x64", "opencode-darwin-x64-baseline",
  "opencode-linux-arm64", "opencode-linux-arm64-musl",
  "opencode-linux-x64-baseline", "opencode-linux-x64-baseline-musl", "opencode-linux-x64-musl",
  "opencode-windows-arm64", "opencode-windows-x64", "opencode-windows-x64-baseline",
]

export const EXCLUDED_ADAPTERS = [
  "@automatalabs/pi-acp",
  "@agentclientprotocol/codex-acp",
  "@agentclientprotocol/claude-agent-acp",
  "@deepseek-ai/dsh",
  "@kilocode/cli",
]
/** The entry the package declares, and the native binary it actually executes. */
export const ENTRY = "node_modules/opencode-ai/bin/opencode.exe"
export const NATIVE_BINARY = "node_modules/opencode-ai/bin/opencode.exe"
export const NATIVE_BINARY_BYTES = 184498304
export const EXCLUDED_PACKAGES = [...EXCLUDED_ADAPTERS, ...EXCLUDED_PLATFORM_PACKAGES]
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

/**
 * OpenCode's closure is resolved against the PINNED platform, not against
 * process.platform/process.arch. os/cpu alone selects four linux/x64 packages.
 */
export function platformPackageIsTargeted(name) {
  return name === TARGET_PLATFORM.package
}

export function resolveClosure({ sourceRoot, fail }) {
  const start = resolvePackage(ADAPTER_PACKAGE, sourceRoot, sourceRoot)
  if (!start) fail("OPENCODE_CLOSURE_ENTRY_MISSING", `${ADAPTER_PACKAGE} is not installed under ${sourceRoot}`)
  const selected = new Map()
  const excluded = []
  const queue = []
  const add = (directory, requiredBy) => {
    if (selected.has(directory)) return
    let manifest
    try {
      manifest = manifestOf(directory)
    } catch {
      fail("OPENCODE_CLOSURE_MANIFEST_INVALID", `${directory} has no readable package.json`)
    }
    selected.set(directory, manifest)
    queue.push({ directory, manifest, requiredBy })
  }
  add(start, "root")
  let sawPlatformPackage = false
  while (queue.length) {
    const { directory, manifest } = queue.shift()
    for (const name of Object.keys(manifest.dependencies ?? {})) {
      const resolved = resolvePackage(name, directory, sourceRoot)
      if (!resolved) fail("OPENCODE_CLOSURE_DEPENDENCY_MISSING", `${manifest.name} requires ${name}, which is not installed`)
      add(resolved, manifest.name)
    }
    for (const name of Object.keys(manifest.optionalDependencies ?? {})) {
      if (!platformPackageIsTargeted(name)) {
        const installed = resolvePackage(name, directory, sourceRoot)
        excluded.push({
          by: manifest.name, name,
          reason: installed ? "not-the-pinned-platform" : "not-installed",
        })
        continue
      }
      const resolved = resolvePackage(name, directory, sourceRoot)
      if (!resolved) {
        fail("OPENCODE_PLATFORM_PACKAGE_MISSING",
          `${manifest.name} requires the pinned platform package ${name}, which is not installed. ` +
          `This builder never infers a platform: build on, or install for, ${TARGET_PLATFORM.os}/${TARGET_PLATFORM.cpu} ` +
          `and install ${TARGET_PLATFORM.package}@${TARGET_PLATFORM.version} explicitly.`)
      }
      sawPlatformPackage = true
      add(resolved, `${manifest.name} (pinned platform)`)
    }
  }
  if (!sawPlatformPackage) {
    fail("OPENCODE_PLATFORM_PACKAGE_MISSING",
      `no pinned platform package (${TARGET_PLATFORM.package}) was selected`)
  }
  return { selected, excluded }
}

function versionsFromLock(sourceRoot) {
  const lock = JSON.parse(readFileSync(path.join(sourceRoot, "package-lock.json"), "utf8"))
  if (!lock || typeof lock.packages !== "object") {
    throw new BuildError("OPENCODE_LOCK_INVALID", "package-lock.json has no package map")
  }
  return lock.packages
}

// -- copy rules --------------------------------------------------------------

const EXCLUDED_DIRECTORIES = new Set([".bin", "docs", "examples"])
const EXCLUDED_FILES = new Set([".package-lock.json", "package-lock.json", "postinstall.mjs"])

/** True for the files a running OpenCode binary never loads. */
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
    throw new BuildError("OPENCODE_ARTIFACT_SHAPE_INVALID",
      `the tree is not a plain file tree: ${problems.slice(0, 5).join(", ")}`)
  }
}

// -- native binary -----------------------------------------------------------

/** SHA-256 of the executable this artifact actually runs. */
export function nativeBinaryDigest(sourceRoot) {
  const file = path.join(sourceRoot, NATIVE_BINARY)
  if (!existsSync(file)) {
    throw new BuildError("OPENCODE_NATIVE_BINARY_MISSING",
      `${NATIVE_BINARY} is absent. opencode-ai ships no library entry: its postinstall places the ` +
      `platform binary at this path, and this builder verifies that rather than running install-time code. ` +
      `Run "npm ci" in the runtime root first.`)
  }
  const stats = lstatSync(file)
  if (!stats.isFile()) {
    throw new BuildError("OPENCODE_NATIVE_BINARY_INVALID", `${NATIVE_BINARY} is not a regular file`)
  }
  if (stats.size !== NATIVE_BINARY_BYTES) {
    throw new BuildError("OPENCODE_NATIVE_BINARY_SIZE_MISMATCH",
      `${NATIVE_BINARY} is ${stats.size} bytes; the pinned ${ADAPTER_PACKAGE}@${ADAPTER_VERSION} ` +
      `binary is ${NATIVE_BINARY_BYTES} bytes`)
  }
  return "sha256:" + createHash("sha256").update(readFileSync(file)).digest("hex")
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
    if (diagnostic.includes("RUNTIME_ARTIFACT_OUTSIDE_BOUNDS")) {
      throw new BuildError("OPENCODE_ARTIFACT_OUTSIDE_BOUNDS", diagnostic.slice(-300))
    }
    throw new BuildError("OPENCODE_ARTIFACT_DIGEST_UNAVAILABLE",
      `the reviewed digest implementation refused the tree: ${diagnostic.slice(-400)}`)
  }
  return JSON.parse(result.stdout)
}

// -- output policy -----------------------------------------------------------

const RESERVED_ROOTS = [".config", ".local", ".pi", ".agentbox", ".opencode", ".ssh", ".gnupg"]

export function assertOutputPolicy(output, { repo = REPO } = {}) {
  if (!path.isAbsolute(output)) throw new BuildError("OPENCODE_OUTPUT_NOT_ABSOLUTE", "--output must be an absolute path")
  const resolved = path.resolve(output)
  if (resolved === repo || resolved.startsWith(repo + path.sep)) {
    throw new BuildError("OPENCODE_OUTPUT_INSIDE_REPOSITORY", "--output must be outside the repository")
  }
  if (resolved === "/" || resolved === path.parse(resolved).root) {
    throw new BuildError("OPENCODE_OUTPUT_UNSAFE", "--output must not be a filesystem root")
  }
  const home = process.env.HOME
  if (home) {
    for (const reserved of RESERVED_ROOTS) {
      const forbidden = path.join(home, reserved)
      if (resolved === forbidden || resolved.startsWith(forbidden + path.sep)) {
        throw new BuildError("OPENCODE_OUTPUT_RESERVED", "--output must not be a user configuration directory")
      }
    }
  }
  const relative = path.relative(repo, resolved)
  if (relative.split(path.sep).includes("node_modules")) {
    throw new BuildError("OPENCODE_OUTPUT_INSIDE_REPOSITORY", "--output must not be a package directory")
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

/** Files that must stay executable through the read-only sealing pass. */
const EXECUTABLE_FILES = new Set([ENTRY])

function makeReadOnly(root) {
  const walk = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const location = path.join(directory, entry.name)
      if (entry.isDirectory()) walk(location)
      // The sealing pass must not strip the exec bit off the entry: OpenCode's
      // entry is a native ELF, not a `node <script>` invocation, so a 0444 mode
      // makes the artifact unrunnable. Sealing is about immutability, not about
      // removing the one permission the entry needs.
      else chmodSync(location, EXECUTABLE_FILES.has(path.relative(root, location).split(path.sep).join("/")) ? 0o555 : 0o444)
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
    throw new BuildError("OPENCODE_OUTPUT_NOT_OWNED", `${output} is a symlink; refusing to touch it`)
  }
  if (!stats.isDirectory()) {
    throw new BuildError("OPENCODE_OUTPUT_NOT_OWNED", `${output} is not a directory; refusing to touch it`)
  }
  if (isOwnedArtifact(output)) {
    if (!replace) {
      throw new BuildError("OPENCODE_OUTPUT_EXISTS", `${output} is an existing artifact; pass --replace to rebuild it`)
    }
    makeWritable(output)
    rmSync(output, { recursive: true, force: true })
    return
  }
  if (readdirSync(output).length === 0) {
    rmdirSync(output)
    return
  }
  throw new BuildError("OPENCODE_OUTPUT_NOT_OWNED", `${output} is non-empty and carries no builder marker; refusing to overwrite it`)
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
          throw new BuildError("OPENCODE_ARTIFACT_SHAPE_INVALID", `${relativePath} is a symlink in the source closure`)
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
          throw new BuildError("OPENCODE_ARTIFACT_SHAPE_INVALID", `${relativePath} is not a regular file`)
        }
        if (!isRuntimeFile(relativePath)) {
          counters.skippedFiles += 1
          continue
        }
        copyFileSync(location, target)
        // The executed entry must stay executable; the rest is content.
        chmodSync(target, relativePath === ENTRY ? 0o755 : 0o644)
        counters.files += 1
        counters.bytes += stats.size
      }
    }
    walk(directory, destination)
  }
}

function assertNoForeignAdapters(sourceRoot) {
  for (const name of EXCLUDED_ADAPTERS) {
    if (resolvePackage(name, sourceRoot, sourceRoot)) {
      throw new BuildError("OPENCODE_ARTIFACT_UNRELATED_PACKAGE",
        `${name} must not be installed in the opencode runtime root`)
    }
  }
}

export function build({ output, source = DEFAULT_SOURCE, replace = false }) {
  const resolved = assertOutputPolicy(output)
  const sourceRoot = path.resolve(source)
  if (!existsSync(path.join(sourceRoot, "package-lock.json"))) {
    throw new BuildError("OPENCODE_SOURCE_INVALID", `${sourceRoot} has no package-lock.json`)
  }
  const lock = versionsFromLock(sourceRoot)
  const fail = (code, message) => { throw new BuildError(code, message) }
  const { selected, excluded } = resolveClosure({ sourceRoot, fail })

  // every selected package must be exactly what the lock records
  const packages = []
  for (const [directory, manifest] of selected) {
    const relative = path.relative(sourceRoot, directory).split(path.sep).join("/")
    const recorded = lock[relative]
    if (!recorded) {
      throw new BuildError("OPENCODE_LOCK_ENTRY_MISSING", `${relative} is not recorded in package-lock.json`)
    }
    if (recorded.version !== manifest.version) {
      throw new BuildError("OPENCODE_LOCK_VERSION_MISMATCH",
        `${relative} is ${manifest.version} on disk but ${recorded.version} in package-lock.json`)
    }
    packages.push({ path: relative, name: manifest.name, version: manifest.version })
  }
  packages.sort((left, right) => left.path.localeCompare(right.path))
  const adapter = packages.find((item) => item.name === ADAPTER_PACKAGE)
  if (!adapter || adapter.version !== ADAPTER_VERSION) {
    throw new BuildError("OPENCODE_ADAPTER_VERSION_MISMATCH",
      `${ADAPTER_PACKAGE} must be ${ADAPTER_VERSION}, found ${adapter ? adapter.version : "nothing"}`)
  }
  const platform = packages.find((item) => item.name === TARGET_PLATFORM.package)
  if (!platform || platform.version !== TARGET_PLATFORM.version) {
    throw new BuildError("OPENCODE_PLATFORM_VERSION_MISMATCH",
      `${TARGET_PLATFORM.package} must be ${TARGET_PLATFORM.version}, found ${platform ? platform.version : "nothing"}`)
  }
  for (const excludedName of EXCLUDED_PLATFORM_PACKAGES) {
    if (packages.some((item) => item.name === excludedName)) {
      throw new BuildError("OPENCODE_ARTIFACT_UNRELATED_PACKAGE",
        `${excludedName} must not be in the OpenCode artifact; only ${TARGET_PLATFORM.package} is pinned`)
    }
  }
  assertNoForeignAdapters(sourceRoot)

  const nativeDigest = nativeBinaryDigest(sourceRoot)

  clearTarget(resolved, { replace })
  mkdirSync(path.dirname(resolved), { recursive: true })
  const staging = mkdtempSync(path.join(path.dirname(resolved), `${path.basename(resolved)}.building-`))
  writeFileSync(path.join(staging, MARKER_NAME), MARKER_CONTENT)
  const counters = { files: 0, bytes: 0, skippedFiles: 0, skippedDirectories: 0 }
  try {
    copyTree(staging, selected, sourceRoot, counters)
    assertPlainTree(staging)
    const summary = treeSummary(staging)
    if (Number(summary.entries) > MAX_ENTRIES || Number(summary.bytes) > MAX_BYTES) {
      throw new BuildError("OPENCODE_ARTIFACT_OUTSIDE_BOUNDS",
        `${summary.entries} entries / ${summary.bytes} bytes exceed the runtime artifact bounds`)
    }
    makeReadOnly(staging)
    const manifest = {
      schemaVersion: 1,
      kind: "agentbox-opencode-runtime-artifact",
      adapter: { package: ADAPTER_PACKAGE, version: ADAPTER_VERSION, entry: ENTRY },
      // OpenCode executes a native binary, not a JS module. Recorded so the
      // installed-asset verifier has the facts whichever trust variant it adopts;
      // accepting this shape is an open security ruling, not decided here.
      nativeBinary: {
        path: NATIVE_BINARY, bytes: NATIVE_BINARY_BYTES, sha256: nativeDigest,
        platformPackage: TARGET_PLATFORM.package, platformVersion: TARGET_PLATFORM.version,
        os: TARGET_PLATFORM.os, cpu: TARGET_PLATFORM.cpu, libc: TARGET_PLATFORM.libc,
      },
      packages: packages.map((item) => ({
        path: item.path,
        name: item.name,
        version: item.version,
        optional: (lock[item.path]?.optional === true) || undefined,
      })),
      excluded: {
        packages: EXCLUDED_PACKAGES,
        platformPackages: EXCLUDED_PLATFORM_PACKAGES,
        directories: [...EXCLUDED_DIRECTORIES].sort(),
        files: [...EXCLUDED_FILES].sort(),
        rules: ["d.ts", "source-maps", "typescript-sources", "documentation", "install-scripts"],
        skippedFiles: counters.skippedFiles,
        skippedDirectories: counters.skippedDirectories,
      },
      optionalSkipped: excluded.sort((left, right) =>
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
      result: "OPENCODE_RUNTIME_BUILD_FAILED", code: "OPENCODE_USAGE",
      error: "usage: build-opencode-runtime-artifact.mjs --output ABSOLUTE_DIR [--source RUNTIME_DIR] [--replace] [--json]",
    }) + "\n")
    return 2
  }
  try {
    const result = build({ output, source, replace: process.argv.includes("--replace") })
    process.stdout.write(JSON.stringify({
      result: "OPENCODE_RUNTIME_ARTIFACT_BUILT",
      output: result.output, treeDigest: result.treeDigest,
      entries: result.entries, bytes: result.bytes,
      adapter: result.adapter, nativeBinary: result.nativeBinary,
      packages: result.packages.length,
      sourceLockDigest: result.sourceLockDigest,
      manifest: `${result.output}.manifest.json`,
    }) + "\n")
    return 0
  } catch (error) {
    process.stdout.write(JSON.stringify({
      result: "OPENCODE_RUNTIME_BUILD_FAILED",
      code: error.code ?? "OPENCODE_RUNTIME_BUILD_ERROR",
      error: String(error.message ?? error).slice(0, 500),
      ...(json ? { stack: String(error.stack ?? "").split("\n").slice(0, 4).join(" | ") } : {}),
    }) + "\n")
    return 1
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  process.exitCode = main()
}
