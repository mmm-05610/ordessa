/**
 * The 42-D coordinator resolves its native tool locations from configuration.
 *
 * `--check-toolchain` resolves and reports without starting any child process
 * and without contacting a provider, so these tests exercise the real
 * fail-closed boundary without a model call. There is no OpenCode runtime on
 * the machine that runs them, and none is installed by these tests.
 */
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"

const SCRIPT = fileURLToPath(new URL("./model-validation-42d.mjs", import.meta.url))

/** Run the real entrypoint with a throwaway 0600 credential file. */
function check(family, env = {}) {
  const scratch = mkdtempSync(path.join(tmpdir(), "ordessa-42d-toolchain-"))
  const secret = path.join(scratch, "not-a-real-token")
  writeFileSync(secret, "token-for-a-configuration-test")
  chmodSync(secret, 0o600)
  // A directory that looks exactly like the personal bin directories this tool
  // used to hardcode; if it were ever embedded again, PATH would contain it.
  const personal = path.join(scratch, "home", "someones-home", ".npm-global", "bin")
  const home = path.join(scratch, "home", "someones-home")
  mkdirSync(personal, { recursive: true })
  try {
    const child = spawnSync(process.execPath,
      [SCRIPT, "--family", family, "--secret-file", secret, "--check-toolchain"], {
        encoding: "utf8",
        env: { PATH: "/usr/bin:/bin", HOME: home, TMPDIR: tmpdir(), NODE_NO_WARNINGS: "1", ...env },
      })
    return { status: child.status, stdout: child.stdout, stderr: child.stderr, home, personal }
  } finally { rmSync(scratch, { recursive: true, force: true }) }
}

// -- fail closed -------------------------------------------------------------

test("opencode refuses to start when its executable is not configured", () => {
  const run = check("opencode")
  assert.equal(run.status, 1, run.stdout + run.stderr)
  const result = JSON.parse(run.stdout)
  assert.equal(result.family, "opencode")
  assert.equal(result.outcome, "FAILED")
  // The message must name the operator's missing input, not just "it failed".
  assert.match(result.error, /TOOLCHAIN_NOT_CONFIGURED/)
  assert.match(result.error, /OPENCODE_BIN/)
  // A refusal is not a validation.
  assert.doesNotMatch(result.error, /MODEL_VERIFIED/)
})

test("hermes refuses to start and names both of its required inputs", () => {
  const run = check("hermes")
  assert.equal(run.status, 1, run.stdout + run.stderr)
  const result = JSON.parse(run.stdout)
  assert.equal(result.outcome, "FAILED")
  assert.match(result.error, /HERMES_BIN/)
  assert.match(result.error, /HERMES_PYTHON_SITE/)
})

test("a partial configuration still refuses and names what remains missing", () => {
  const run = check("hermes", { HERMES_BIN: "/opt/hermes/bin/hermes" })
  assert.equal(run.status, 1, run.stdout + run.stderr)
  const result = JSON.parse(run.stdout)
  assert.match(result.error, /HERMES_PYTHON_SITE/)
  // The supplied value is not itself reported as missing.
  assert.doesNotMatch(result.error, /HERMES_BIN \(/)
})

test("a blank value is a refusal, not an empty path", () => {
  const run = check("opencode", { OPENCODE_BIN: "   " })
  assert.equal(run.status, 1, run.stdout + run.stderr)
  assert.match(JSON.parse(run.stdout).error, /OPENCODE_BIN/)
})

test("a relative configured location is refused", () => {
  const run = check("opencode", { OPENCODE_BIN: "bin/opencode" })
  assert.equal(run.status, 1, run.stdout + run.stderr)
  assert.match(JSON.parse(run.stdout).error, /absolute path/)
})

// -- explicit configuration is honoured --------------------------------------

test("an explicitly supplied location is used verbatim", () => {
  const run = check("opencode", { OPENCODE_BIN: "/opt/opencode/bin/opencode" })
  assert.equal(run.status, 0, run.stdout + run.stderr)
  const result = JSON.parse(run.stdout)
  assert.equal(result.outcome, "TOOLCHAIN_READY")
  assert.equal(result.OPENCODE_BIN, "/opt/opencode/bin/opencode")
  assert.deepEqual(result.binDirectories, ["/opt/opencode/bin"])
})

test("pi requires no external location at all", () => {
  // Pi's adapter is resolved from this repository, so pi never had a personal
  // machine path to configure; that must stay true.
  const run = check("pi")
  assert.equal(run.status, 0, run.stdout + run.stderr)
  const result = JSON.parse(run.stdout)
  assert.equal(result.outcome, "TOOLCHAIN_READY")
  assert.deepEqual(result.binDirectories, [])
  assert.equal(result.isolatedPath, "/usr/bin:/bin")
})

// -- PATH construction -------------------------------------------------------

test("the isolated PATH is the system directories plus the resolved tool directory", () => {
  const run = check("hermes", {
    HERMES_BIN: "/opt/hermes/bin/hermes",
    HERMES_PYTHON_SITE: "/opt/hermes/lib/python3.12/site-packages",
  })
  assert.equal(run.status, 0, run.stdout + run.stderr)
  const result = JSON.parse(run.stdout)
  // A library root is not an executable directory: site-packages contributes
  // PYTHONPATH, never PATH.
  assert.equal(result.isolatedPath, "/usr/bin:/bin:/opt/hermes/bin")
  assert.deepEqual(result.binDirectories, ["/opt/hermes/bin"])
  assert.equal(result.HERMES_PYTHON_SITE, "/opt/hermes/lib/python3.12/site-packages")
})

test("the isolated PATH never contains a personal home directory", () => {
  // The scratch tree carries a realistic `.npm-global/bin` and `$HOME`; the
  // assertion is that neither reaches the child PATH. This is the exact shape
  // the script used to hardcode, so the check is not vacuous: a regression that
  // reintroduced `~/.npm-global/bin` would have to also make this scratch path
  // literal to pass, which the source guard test forbids outright.
  for (const family of ["pi", "hermes", "opencode"]) {
    const run = check(family, { HERMES_BIN: "/opt/hermes/bin/hermes",
      HERMES_PYTHON_SITE: "/opt/hermes/site-packages", OPENCODE_BIN: "/opt/opencode/bin/opencode" })
    assert.equal(run.status, 0, run.stdout + run.stderr)
    const result = JSON.parse(run.stdout)
    assert.doesNotMatch(result.isolatedPath, /\/home\//)
    assert.doesNotMatch(result.isolatedPath, /\.npm-global/)
    assert.doesNotMatch(result.isolatedPath, /\.local\/bin/)
    // The scratch $HOME and its `.npm-global/bin` are the exact shapes the
    // script used to hardcode, so if either were re-derived from $HOME they
    // would land here. The path is regex-escaped because it is under /tmp and
    // may legitimately contain regex metacharacters.
    assert.doesNotMatch(result.isolatedPath, new RegExp(run.home.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    assert.doesNotMatch(result.isolatedPath, new RegExp(run.personal.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    for (const directory of result.binDirectories) assert.doesNotMatch(directory, /\.npm-global|\.local/)
  }
})