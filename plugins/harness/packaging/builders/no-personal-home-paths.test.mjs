/**
 * A committed tool must not carry one machine's home directory.
 *
 * This is a guard over the source text of the two 42-D/OpenCode preparation
 * scripts, which is the only place the defect can reappear: the functional
 * tests exercise resolved values, but a hardcoded literal would survive them.
 */
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import test from "node:test"

const SUBJECTS = [
  "build-opencode-authorization.mjs",
  "model-validation-42d.mjs",
].map((name) => ({
  name,
  source: readFileSync(fileURLToPath(new URL(`./${name}`, import.meta.url)), "utf8"),
}))

for (const { name, source } of SUBJECTS) {
  test(`${name} embeds no absolute path under a personal home directory`, () => {
    // Any `/home/<something>` literal at all: the developers' paths, and every
    // other account's, are equally unrunnable on the next machine.
    assert.doesNotMatch(source, /\/home\/[^\s"'`]*[A-Za-z0-9._-]/,
      `${name} must take installation locations from configuration, not a home directory`)
    assert.doesNotMatch(source, /\/Users\/[^\s"'`]*[A-Za-z0-9._-]/,
      `${name} must not carry a macOS home directory either`)
  })
}

test("the OpenCode authorization defaults are configuration, not paths", () => {
  const { source } = SUBJECTS.find((subject) => subject.name === "build-opencode-authorization.mjs")
  // The names the tool tells an operator to supply.
  assert.match(source, /OPENCODE_BIN_DIR/)
  assert.match(source, /OPENCODE_PACKAGE_ROOT/)
  // The retired literals must not reappear under any spelling.
  assert.doesNotMatch(source, /npm-global/)
  assert.doesNotMatch(source, /\.npm-global/)
})

test("the 42-D coordinator declares what each family needs and where from", () => {
  const { source } = SUBJECTS.find((subject) => subject.name === "model-validation-42d.mjs")
  for (const name of ["HERMES_BIN", "HERMES_PYTHON_SITE", "OPENCODE_BIN"]) {
    assert.match(source, new RegExp(name), `${name} must be a declared configuration input`)
  }
  // PATH is assembled from the resolved tool directories and the system ones.
  assert.match(source, /buildIsolatedPath/)
  assert.match(source, /SYSTEM_BIN_DIRS = \["\/usr\/bin", "\/bin"\]/)
  // And the refusal has to name the operator's missing input.
  assert.match(source, /TOOLCHAIN_NOT_CONFIGURED/)
})