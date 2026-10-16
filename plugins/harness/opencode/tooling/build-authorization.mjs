#!/usr/bin/env node
/**
 * Authorize the single-file OpenCode binary for the managed Worker projection.
 *
 * OpenCode ships as one self-contained executable (a Bun-compiled ELF), not as
 * a dependency tree, so the Pi-style runtime artifact builder has nothing to
 * build here. What the deployment needs instead is a *verified identity* for
 * that one file: the canonical source the Worker will mount read-only at
 * `/runtime/bin/opencode`, the full sha256 the Worker re-verifies before bwrap
 * starts, the file type, and the version the binary itself reports.
 *
 * This tool derives that identity from the real installation instead of
 * trusting a hand-written digest:
 *
 *   1. The CLI entry (an npm-installed symlink) is resolved to the real file;
 *      both paths are recorded, and the mount source is always the real file.
 *   2. The source has to be a controlled installation path: a regular,
 *      executable, plain ELF file inside the installed package directory. A
 *      relative or non-canonical path, a symlink, a directory, a whole
 *      `node_modules` directory, or a user configuration/cache location is
 *      refused with a typed code - those are exactly the shapes that would
 *      smuggle a user-managed or post-install-modified binary into the sandbox.
 *   3. The digest is the full sha256 of the file and the size is recorded, so a
 *      rebuilt or patched binary is a loud drift instead of a silent change.
 *   4. The binary is asked for its own version, and that answer must be the
 *      pinned one, so the authorization describes the binary that will run.
 *
 * Which installation to authorize is configuration, never a guess: the
 * launcher directory and the installed package directory come from
 * `OPENCODE_BIN_DIR` / `OPENCODE_PACKAGE_ROOT` or from `--entry` /
 * `--install-root`. When neither is supplied the tool refuses with a message
 * naming what is missing; it never falls back to one machine's home directory.
 *
 * usage: build-opencode-authorization.mjs [--entry PATH] [--source PATH]
 *          [--install-root PATH] [--expect-digest sha256:...] [--expect-size N]
 *          [--expect-version V] [--deployment-out PATH] [--json]
 *
 * environment: OPENCODE_BIN_DIR         absolute directory holding the opencode launcher
 *             OPENCODE_PACKAGE_ROOT    absolute installed opencode-ai package directory
 *                                      (a package directory inside a node_modules tree)
 */
import { createHash } from "node:crypto"
import { lstatSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs"
import { spawnSync } from "node:child_process"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

//: The pinned OpenCode release this deployment was prepared against.
export const OPENCODE_VERSION = "1.18.21"
//: Where the installation that is being authorized is configured. A committed
//: tool must not carry one machine's home directory, so these are inputs.
export const OPENCODE_BIN_DIR_ENV = "OPENCODE_BIN_DIR"
export const OPENCODE_PACKAGE_ROOT_ENV = "OPENCODE_PACKAGE_ROOT"
//: The file the launcher resolves to inside the installed package.
export const OPENCODE_BINARY_RELATIVE = "bin/opencode.exe"
//: The fixed guest path the Worker mounts the verified binary at.
export const EXECUTABLE_TARGET = "/runtime/bin/opencode"
//: Directories a mount source must never come from: user-managed state.
const FORBIDDEN_ROOTS = [".config", ".cache", ".local", ".ssh", ".gnupg", ".agentbox"]

export class AuthorizationError extends Error {
  constructor(code, message) {
    super(`${code}: ${message}`)
    this.name = "AuthorizationError"
    this.code = code
    this.detail = message
  }
}

function fail(code, message) {
  throw new AuthorizationError(code, message)
}

// -- installation configuration ---------------------------------------------

function configured(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null
}

/**
 * Derive the installation locations from the environment.
 *
 * Missing input resolves to `null`; it is never replaced by a default path,
 * so `requireInstall` can refuse and name what the operator has to supply.
 */
export function resolveInstall(env = process.env) {
  const binDir = configured(env[OPENCODE_BIN_DIR_ENV])
  const packageRoot = configured(env[OPENCODE_PACKAGE_ROOT_ENV])
  return {
    entry: binDir === null ? null : path.join(binDir, "opencode"),
    packageRoot,
    source: packageRoot === null ? null : path.join(packageRoot, ...OPENCODE_BINARY_RELATIVE.split("/")),
  }
}

/**
 * Combine explicit arguments with the environment, refusing anything the
 * caller left unconfigured. A caller that passes everything explicitly is
 * honoured and never needs the environment.
 */
export function requireInstall({ entry = null, packageRoot = null, env = process.env } = {}) {
  const fromEnvironment = resolveInstall(env)
  const entryPath = configured(entry) ?? fromEnvironment.entry
  const packageRootPath = configured(packageRoot) ?? fromEnvironment.packageRoot
  const missing = []
  if (entryPath === null) {
    missing.push(`${OPENCODE_BIN_DIR_ENV} (the absolute directory holding the opencode launcher)`
      + ` or --entry (an explicit absolute launcher path)`)
  }
  if (packageRootPath === null) {
    missing.push(`${OPENCODE_PACKAGE_ROOT_ENV} (the absolute installed opencode-ai package directory)`
      + ` or --install-root (an explicit absolute package root)`)
  }
  if (missing.length > 0) {
    fail("OPENCODE_INSTALL_NOT_CONFIGURED",
      `the OpenCode installation to authorize is not configured: supply ${missing.join(", and ")}`
      + ". This tool never guesses an absolute path under one machine's home directory.")
  }
  return { entry: entryPath, packageRoot: packageRootPath }
}

// -- path and shape checks ---------------------------------------------------

export function assertCanonical(value, { code, what }) {
  if (typeof value !== "string" || !value.startsWith("/")) {
    fail(code, `${what} must be an absolute path`)
  }
  if (value.includes("\0") || value.includes("//") || value.endsWith("/")
      || value.split("/").some((part) => part === "." || part === "..")) {
    fail(code, `${what} is not canonical`)
  }
  return value
}

/** Refuse a mount source that is not a controlled installation file. */
export function assertControlledSource({ source, packageRoot, home = process.env.HOME }) {
  assertCanonical(source, { code: "OPENCODE_SOURCE_NOT_ABSOLUTE", what: "the mount source" })
  assertCanonical(packageRoot, { code: "OPENCODE_SOURCE_NOT_CONTROLLED", what: "the package root" })
  for (const forbidden of FORBIDDEN_ROOTS) {
    if (!home) continue
    const root = path.join(home, forbidden)
    if (packageRoot === root || packageRoot.startsWith(root + path.sep)) {
      fail("OPENCODE_SOURCE_NOT_CONTROLLED", "the package root is a user configuration or cache directory")
    }
  }
  const segments = packageRoot.split("/")
  if (path.basename(packageRoot) === "node_modules" || packageRoot === "/"
      || !segments.includes("node_modules")) {
    fail("OPENCODE_SOURCE_NOT_CONTROLLED",
      "the package root must be an installed package directory inside a node_modules tree")
  }
  if (!source.startsWith(packageRoot + "/")) {
    fail("OPENCODE_SOURCE_NOT_CONTROLLED", "the mount source is outside the installed package")
  }
  let link
  try {
    link = lstatSync(source)
  } catch {
    fail("OPENCODE_ENTRY_MISSING", `the mount source does not exist: ${source}`)
  }
  if (link.isSymbolicLink()) {
    fail("OPENCODE_SOURCE_SYMLINK", "the mount source is a symlink; resolve it and mount the real file")
  }
  if (link.isDirectory()) fail("OPENCODE_SOURCE_NOT_REGULAR_FILE", "the mount source is a directory")
  if (!link.isFile()) fail("OPENCODE_SOURCE_NOT_REGULAR_FILE", "the mount source is not a regular file")
  if ((link.mode & 0o111) === 0) fail("OPENCODE_SOURCE_NOT_EXECUTABLE", "the mount source is not executable")
  return statSync(source)
}

// -- ELF identity ------------------------------------------------------------

const ELF_CLASS = { 1: "32-bit", 2: "64-bit" }
const ELF_DATA = { 1: "LSB", 2: "MSB" }
const ELF_TYPE = { 1: "relocatable", 2: "executable", 3: "shared object", 4: "core" }
const ELF_MACHINE = { 0x03: "i386", 0x28: "arm", 0x3e: "x86-64", 0xb7: "aarch64", 0xf3: "riscv" }

/** Decode the ELF header itself: the file's own bytes, not a `file` call. */
export function elfIdentity(bytes) {
  if (!bytes || bytes.length < 20) fail("OPENCODE_SOURCE_NOT_ELF", "the file is too short for an ELF header")
  if (!(bytes[0] === 0x7f && bytes[1] === 0x45 && bytes[2] === 0x4c && bytes[3] === 0x46)) {
    fail("OPENCODE_SOURCE_NOT_ELF", "the file does not start with the ELF magic")
  }
  const bits = ELF_CLASS[bytes[4]]
  const endian = ELF_DATA[bytes[5]]
  if (!bits || !endian) fail("OPENCODE_SOURCE_NOT_ELF", "the ELF identification is not understood")
  const read = endian === "LSB"
    ? (offset) => bytes.readUInt16LE(offset)
    : (offset) => bytes.readUInt16BE(offset)
  const type = read(16)
  const machine = read(18)
  return {
    fileType: `ELF ${bits} ${endian} ${ELF_TYPE[type] ?? `type ${type}`}, ${ELF_MACHINE[machine] ?? `machine 0x${machine.toString(16)}`}`,
    elfBits: bits, elfEndian: endian, elfType: ELF_TYPE[type] ?? `type ${type}`,
    elfMachine: ELF_MACHINE[machine] ?? `machine 0x${machine.toString(16)}`,
  }
}

export function sha256File(location) {
  return "sha256:" + createHash("sha256").update(readFileSync(location)).digest("hex")
}

// -- version probe -----------------------------------------------------------

/** Ask the binary itself which version it is, with no inherited environment. */
export function probeVersion(resolved, { run = defaultVersionRun, expect = OPENCODE_VERSION } = {}) {
  const outcome = run(resolved)
  if (!outcome || typeof outcome.stdout !== "string") {
    fail("OPENCODE_VERSION_PROBE_FAILED", "the binary produced no version output")
  }
  if (outcome.status !== 0) {
    fail("OPENCODE_VERSION_PROBE_FAILED",
      `the binary exited ${outcome.status}: ${String(outcome.stderr ?? "").trim().slice(-200)}`)
  }
  const version = outcome.stdout.trim()
  if (version !== expect) {
    fail("OPENCODE_VERSION_MISMATCH",
      `the binary reports ${JSON.stringify(version)}, expected ${JSON.stringify(expect)}`)
  }
  return version
}

function defaultVersionRun(resolved) {
  const home = mkdtempSync(path.join(tmpdir(), "agentbox-opencode-version-"))
  try {
    return spawnSync(resolved, ["--version"], {
      // A version probe must not see this process's environment: it is a
      // read-only question, and an inherited environment could change its answer.
      env: { PATH: "/usr/bin:/bin", HOME: home, LANG: "C.UTF-8" },
      encoding: "utf8", timeout: 60_000, stdio: ["ignore", "pipe", "pipe"],
    })
  } finally {
    rmSync(home, { recursive: true, force: true })
  }
}

// -- authorization -----------------------------------------------------------

/**
 * Derive one verified binary declaration.
 *
 * Every field a deployment quotes (source, digest, size, version) is computed
 * here from the real file, and every expectation the caller adds is compared
 * against it; a disagreement is a typed refusal, never a warning.
 */
export function authorizeBinary({
  entry = null, source = null, packageRoot = null,
  expectDigest = null, expectSize = null, expectVersion = OPENCODE_VERSION,
  runVersion = defaultVersionRun, home = process.env.HOME, env = process.env,
} = {}) {
  const install = requireInstall({ entry, packageRoot, env })
  entry = install.entry
  packageRoot = install.packageRoot
  assertCanonical(entry, { code: "OPENCODE_ENTRY_NOT_ABSOLUTE", what: "the CLI entry" })
  let entryLink
  try {
    entryLink = lstatSync(entry)
  } catch {
    fail("OPENCODE_ENTRY_MISSING", `the CLI entry does not exist: ${entry}`)
  }
  const entryIsSymlink = entryLink.isSymbolicLink()
  if (!entryIsSymlink && !entryLink.isFile()) {
    fail("OPENCODE_ENTRY_MISSING", "the CLI entry is neither a file nor a symlink")
  }
  const resolved = realpathSync(entry)
  assertCanonical(resolved, { code: "OPENCODE_SOURCE_NOT_CANONICAL", what: "the resolved CLI entry" })
  if (source !== null) {
    assertCanonical(source, { code: "OPENCODE_SOURCE_NOT_ABSOLUTE", what: "the mount source" })
    if (source !== resolved) {
      let isLink = false
      try {
        isLink = lstatSync(source).isSymbolicLink()
      } catch {
        fail("OPENCODE_ENTRY_MISSING", `the mount source does not exist: ${source}`)
      }
      fail(isLink ? "OPENCODE_SOURCE_SYMLINK" : "OPENCODE_SOURCE_NOT_RESOLVED",
        "the mount source must be the resolved real file, not another path")
    }
  }
  const mounted = source ?? resolved
  const stats = assertControlledSource({ source: mounted, packageRoot, home })
  const bytes = readFileSync(mounted)
  const identity = elfIdentity(bytes)
  const digest = "sha256:" + createHash("sha256").update(bytes).digest("hex")
  const sizeBytes = stats.size
  if (expectDigest !== null && expectDigest !== digest) {
    fail("OPENCODE_DIGEST_DRIFT",
      `the binary hashes to ${digest}, not the declared ${String(expectDigest).slice(0, 24)}...`)
  }
  if (expectSize !== null && Number(expectSize) !== sizeBytes) {
    fail("OPENCODE_SIZE_DRIFT", `the binary is ${sizeBytes} bytes, not the declared ${expectSize}`)
  }
  const version = probeVersion(mounted, { run: runVersion, expect: expectVersion })
  return {
    result: "OPENCODE_BINARY_AUTHORIZED",
    entry,
    entryIsSymlink,
    resolved,
    source: mounted,
    packageRoot,
    digest,
    sizeBytes,
    version,
    versionOutput: version,
    fileType: identity.fileType,
    elfIdentity: identity,
    executableMounts: [{ source: mounted, target: EXECUTABLE_TARGET, digest }],
  }
}

/** The deployment fragment a caller may write for the template to consume. */
export function deploymentFragment(declaration) {
  return {
    schemaVersion: 1,
    kind: "agentbox-opencode-executable-authorization",
    harnesses: [{ id: "opencode", executableMounts: declaration.executableMounts }],
    binary: {
      entry: declaration.entry, resolved: declaration.resolved, source: declaration.source,
      digest: declaration.digest, sizeBytes: declaration.sizeBytes,
      version: declaration.version, fileType: declaration.fileType,
    },
  }
}

function argument(name) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : undefined
}

function main() {
  const json = process.argv.includes("--json")
  if (process.argv.includes("--help")) {
    process.stdout.write(
      "usage: build-opencode-authorization.mjs [--entry PATH] [--source PATH]\n"
      + "         [--install-root PATH] [--expect-digest sha256:...] [--expect-size N]\n"
      + "         [--expect-version V] [--deployment-out PATH] [--json]\n"
      + "\n"
      + `environment: ${OPENCODE_BIN_DIR_ENV}      absolute directory holding the opencode launcher\n`
      + `            ${OPENCODE_PACKAGE_ROOT_ENV} absolute installed opencode-ai package directory\n`
      + "\n"
      + "--entry / --install-root are required unless the matching environment\n"
      + "variable is set; with neither, this tool refuses instead of guessing.\n")
    return 2
  }
  try {
    const declaration = authorizeBinary({
      entry: argument("--entry") ?? null,
      source: argument("--source") ?? null,
      packageRoot: argument("--install-root") ?? null,
      expectDigest: argument("--expect-digest") ?? null,
      expectSize: argument("--expect-size") ?? null,
      expectVersion: argument("--expect-version") ?? OPENCODE_VERSION,
    })
    const deploymentOut = argument("--deployment-out")
    if (deploymentOut) {
      const location = path.resolve(deploymentOut)
      writeFileSync(location, JSON.stringify(deploymentFragment(declaration), null, 2) + "\n")
      declaration.deploymentFragment = location
    }
    process.stdout.write(JSON.stringify(declaration) + "\n")
    return 0
  } catch (error) {
    process.stdout.write(JSON.stringify({
      result: "OPENCODE_BINARY_AUTHORIZATION_FAILED",
      code: error?.code ?? "OPENCODE_AUTHORIZATION_ERROR",
      error: String(error?.message ?? error).slice(0, 500),
      ...(json ? { script: fileURLToPath(import.meta.url) } : {}),
    }) + "\n")
    return 1
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  process.exitCode = main()
}
