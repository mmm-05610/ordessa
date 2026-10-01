/**
 * The OpenCode installation is configuration, not a committed constant.
 *
 * These tests never authorize a real OpenCode: there is no such runtime on the
 * machine that runs them, and the identity checks are exercised against a
 * fixture ELF through the script's own `runVersion` injection point, which
 * already exists in the production code path.
 */
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { createHash } from "node:crypto"
import { chmodSync, copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"

import {
  OPENCODE_BIN_DIR_ENV,
  OPENCODE_BINARY_RELATIVE,
  OPENCODE_PACKAGE_ROOT_ENV,
  OPENCODE_VERSION,
  authorizeBinary,
  resolveInstall,
  requireInstall,
} from "./build-opencode-authorization.mjs"

const SCRIPT = fileURLToPath(new URL("./build-opencode-authorization.mjs", import.meta.url))

/**
 * A stand-in installation: a real ELF file (the running node binary) at the
 * path the launcher resolves to, behind an npm-style symlink in a bin dir.
 */
function fixtureInstallation() {
  const scratch = mkdtempSync(path.join(tmpdir(), "ordessa-opencode-install-"))
  const packageRoot = path.join(scratch, "lib", "node_modules", "opencode-ai")
  const binary = path.join(packageRoot, ...OPENCODE_BINARY_RELATIVE.split("/"))
  const binDir = path.join(scratch, "bin")
  mkdirSync(path.dirname(binary), { recursive: true })
  mkdirSync(binDir)
  copyFileSync(process.execPath, binary)
  chmodSync(binary, 0o755)
  const entry = path.join(binDir, "opencode")
  symlinkSync(binary, entry)
  return { scratch, binDir, packageRoot, binary, entry }
}

// -- fail closed -------------------------------------------------------------

test("an unconfigured environment resolves to no installation at all", () => {
  // Not "a path that happens not to exist": absent input resolves to null so
  // that nothing downstream can mistake it for a usable location.
  assert.deepEqual(resolveInstall({}), { entry: null, packageRoot: null, source: null })
  assert.deepEqual(resolveInstall({ [OPENCODE_BIN_DIR_ENV]: "   " }), { entry: null, packageRoot: null, source: null })
})

test("requireInstall refuses and names both missing inputs", () => {
  assert.throws(() => requireInstall({ env: {} }), (error) => {
    assert.equal(error.code, "OPENCODE_INSTALL_NOT_CONFIGURED")
    assert.equal(error.name, "AuthorizationError")
    assert.match(error.message, /OPENCODE_BIN_DIR/)
    assert.match(error.message, /OPENCODE_PACKAGE_ROOT/)
    assert.match(error.message, /--entry/)
    assert.match(error.message, /--install-root/)
    return true
  })
})

test("requireInstall names only the input that is actually missing", () => {
  assert.throws(
    () => requireInstall({ env: { [OPENCODE_BIN_DIR_ENV]: "/opt/opencode/bin" } }),
    (error) => {
      assert.equal(error.code, "OPENCODE_INSTALL_NOT_CONFIGURED")
      assert.doesNotMatch(error.message, /--entry\b/)
      assert.match(error.message, /OPENCODE_PACKAGE_ROOT/)
      return true
    })
})

test("the command line refuses when neither flag nor environment is supplied", () => {
  const scratch = mkdtempSync(path.join(tmpdir(), "ordessa-opencode-cli-"))
  try {
    const child = spawnSync(process.execPath, [SCRIPT, "--json"], {
      encoding: "utf8", env: { PATH: "/usr/bin:/bin", HOME: scratch },
    })
    assert.equal(child.status, 1, child.stdout + child.stderr)
    const result = JSON.parse(child.stdout)
    assert.equal(result.result, "OPENCODE_BINARY_AUTHORIZATION_FAILED")
    assert.equal(result.code, "OPENCODE_INSTALL_NOT_CONFIGURED")
    assert.match(result.error, /OPENCODE_BIN_DIR/)
    assert.match(result.error, /OPENCODE_PACKAGE_ROOT/)
    // A refusal must not be confused with a successful authorization.
    assert.equal(result.executableMounts, undefined)
  } finally { rmSync(scratch, { recursive: true, force: true }) }
})

// -- explicit configuration is honoured --------------------------------------

test("explicit arguments are honoured with an empty environment", () => {
  const install = fixtureInstallation()
  try {
    const declaration = authorizeBinary({
      entry: install.entry, packageRoot: install.packageRoot,
      expectVersion: OPENCODE_VERSION,
      // The version probe is the script's own injection point; the real probe
      // would execute the fixture, which is not an OpenCode build.
      runVersion: () => ({ status: 0, stdout: `${OPENCODE_VERSION}\n` }),
      home: install.scratch, env: {},
    })
    assert.equal(declaration.result, "OPENCODE_BINARY_AUTHORIZED")
    assert.equal(declaration.entry, install.entry)
    assert.equal(declaration.entryIsSymlink, true)
    assert.equal(declaration.source, install.binary)
    assert.equal(declaration.packageRoot, install.packageRoot)
    assert.equal(declaration.sizeBytes, statSize(install.binary))
    assert.equal(declaration.digest, digestOf(install.binary))
    assert.deepEqual(declaration.executableMounts, [{
      source: install.binary, target: "/runtime/bin/opencode", digest: declaration.digest,
    }])
  } finally { rmSync(install.scratch, { recursive: true, force: true }) }
})

test("the environment is honoured when no argument is supplied", () => {
  const install = fixtureInstallation()
  try {
    const declaration = authorizeBinary({
      expectVersion: OPENCODE_VERSION,
      runVersion: () => ({ status: 0, stdout: OPENCODE_VERSION }),
      home: install.scratch,
      env: { [OPENCODE_BIN_DIR_ENV]: install.binDir, [OPENCODE_PACKAGE_ROOT_ENV]: install.packageRoot },
    })
    assert.equal(declaration.result, "OPENCODE_BINARY_AUTHORIZED")
    assert.equal(declaration.entry, install.entry)
    assert.equal(declaration.source, install.binary)
  } finally { rmSync(install.scratch, { recursive: true, force: true }) }
})

test("the derived package binary path follows the resolved package root", () => {
  const install = fixtureInstallation()
  try {
    assert.deepEqual(resolveInstall({
      [OPENCODE_BIN_DIR_ENV]: install.binDir, [OPENCODE_PACKAGE_ROOT_ENV]: install.packageRoot,
    }), { entry: install.entry, packageRoot: install.packageRoot, source: install.binary })
  } finally { rmSync(install.scratch, { recursive: true, force: true }) }
})

test("a configured but non-absolute entry is still refused as non-canonical", () => {
  // The refusal happens on the value itself, not because the environment was
  // consulted: an operator who supplies a relative path gets the same answer
  // an operator who supplies nothing gets for that field.
  assert.throws(() => authorizeBinary({
    entry: "bin/opencode", packageRoot: "/opt/lib/node_modules/opencode-ai", env: {},
  }), (error) => {
    assert.equal(error.code, "OPENCODE_ENTRY_NOT_ABSOLUTE")
    return true
  })
})

// -- helpers -----------------------------------------------------------------

/** An independent encoding of the fixture's real size and digest. */
function statSize(file) {
  return readFileSync(file).length
}

function digestOf(file) {
  return "sha256:" + createHash("sha256").update(readFileSync(file)).digest("hex")
}