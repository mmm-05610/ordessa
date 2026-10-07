/**
 * Controlled-peer allowlist: the boundary, the pinned digests, the port.
 *
 * Three guards over `runtime/controlled-peers.mjs` (spec 019, "锁内容不锁位置"):
 *
 *   1. **boundary (CP-4)** — the plugin's production code carries no path
 *      constant into the repository's test trees. The regex is core's
 *      any-written-form pattern: it catches `tests/acp_orchestration` as well
 *      as the Python `Path("tests") / "acp_orchestration"` spelling, because a
 *      path constant does not stop deciding security by being written
 *      differently. The allowlist being digest-based is what makes this
 *      possible: matching has no need for a location, so none is pinned.
 *   2. **digest pin (CP-1 update flow)** — the built-in table pins exactly the
 *      committed fixture content. A fixture edit without a table update fails
 *      here, and so does a table edit without the fixture: this test is the
 *      enforcement end of the update flow documented in the package README.
 *   3. **injection port (CP-2)** — parsing and fail-closed semantics of
 *      `AGENTBOX_CONTROLLED_PEER_ALLOWLIST`, unit-level (the spawn-level
 *      behavior is pinned in `tests/access/access_launch_route.test.mjs`).
 */
import assert from "node:assert/strict"
import { createHash } from "node:crypto"
import { readdirSync, readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"
import {
  BUILTIN_CONTROLLED_PEERS,
  CONTROLLED_PEER_ALLOWLIST_ENV,
  resolveControlledPeerAllowlist,
} from "../runtime/controlled-peers.mjs"

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const repoRoot = path.resolve(pluginRoot, "..", "..")

/** Core's any-written-form pattern for a path constant into the test trees. */
const TESTS_PATH_PATTERN = new RegExp(`tests[/"'.  ]*(acp_orchestration|acp-connector|integration)`)

const PRODUCTION_ROOTS = ["runtime", "harnesses", "src", "api/src"]

function collectFiles(directory, found = []) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === "__pycache__" || entry.name === "node_modules") continue
      collectFiles(full, found)
    } else found.push(full)
  }
  return found
}

test("production code carries no path constant into the test trees", () => {
  const violations = []
  for (const root of PRODUCTION_ROOTS) {
    for (const file of collectFiles(path.join(pluginRoot, root))) {
      const text = readFileSync(file, "utf8")
      const lines = text.split("\n")
      lines.forEach((line, index) => {
        if (TESTS_PATH_PATTERN.test(line)) {
          violations.push(`${path.relative(repoRoot, file)}:${index + 1}: ${line.trim().slice(0, 120)}`)
        }
      })
    }
  }
  assert.deepEqual(violations, [],
    "production code must not decide anything by a test-tree path; found:\n" + violations.join("\n"))
})

test("the built-in table pins exactly the committed controlled peers", () => {
  const digest = (file) => createHash("sha256").update(readFileSync(file)).digest("hex")
  const unbound = digest(path.join(pluginRoot, "tests", "access", "controlled_harness.mjs"))
  const orchestration = digest(path.join(repoRoot, "tests", "acp_orchestration", "fixtures",
    "bidirectional_acp_peer.mjs"))
  assert.deepEqual([...BUILTIN_CONTROLLED_PEERS], [
    { sha256: unbound, file: "controlled_harness.mjs" },
    { sha256: orchestration, file: "bidirectional_acp_peer.mjs", harness: "pi" },
  ])
})

test("an absent or empty injection leaves the built-in table standing", () => {
  assert.equal(resolveControlledPeerAllowlist({}).injected, false)
  assert.equal(resolveControlledPeerAllowlist({ [CONTROLLED_PEER_ALLOWLIST_ENV]: "" }).injected, false)
  const ambient = resolveControlledPeerAllowlist({})
  assert.equal(ambient.peers, BUILTIN_CONTROLLED_PEERS)
})

test("a valid injection replaces the built-in table wholesale", () => {
  const table = JSON.stringify([
    { sha256: "a".repeat(64), file: "injected-peer.mjs" },
    { sha256: "B".repeat(64), harness: "pi" },
  ])
  const resolved = resolveControlledPeerAllowlist({ [CONTROLLED_PEER_ALLOWLIST_ENV]: table })
  assert.equal(resolved.injected, true)
  assert.equal(resolved.error, undefined)
  // Precedence is replacement: an injected table does not merge with the
  // built-in one, so the fixture digests are gone while it stands.
  assert.deepEqual(resolved.peers, [
    { sha256: "a".repeat(64), file: "injected-peer.mjs" },
    { sha256: "b".repeat(64), harness: "pi" },
  ])
  assert.equal(BUILTIN_CONTROLLED_PEERS.length, 2)
})

test("an invalid injection is fail-closed: empty table plus the reason", () => {
  const cases = [
    "{not json",
    '"a string"',
    "42",
    "[",
    '[{"sha256":"nothex"}]',
    '[{"sha256":"a"}]',
    '[{"sha256":"' + "a".repeat(64) + '","command":"/bin/sh"}]',   // no command surface
    '[{"sha256":"' + "a".repeat(64) + '","args":["-c"]}]',          // no argument surface
    '[{"sha256":"' + "a".repeat(64) + '","unknown":true}]',
    '[{"sha256":"' + "a".repeat(64) + '","file":"bad\\nline"}]',
    '[{"sha256":"' + "a".repeat(64) + '","file":' + JSON.stringify("x".repeat(257)) + "}]",
    '[{"sha256":"' + "a".repeat(64) + '","harness":""}]',
    '[["nested-array"]]',
    '[null]',
  ]
  for (const raw of cases) {
    const resolved = resolveControlledPeerAllowlist({ [CONTROLLED_PEER_ALLOWLIST_ENV]: raw })
    assert.equal(resolved.injected, true, raw)
    assert.deepEqual(resolved.peers, [], raw)
    assert.equal(typeof resolved.error, "string", raw)
  }
})

test("an empty injected array allows nothing — and that is a valid declaration", () => {
  const resolved = resolveControlledPeerAllowlist({ [CONTROLLED_PEER_ALLOWLIST_ENV]: "[]" })
  assert.equal(resolved.injected, true)
  assert.equal(resolved.error, undefined)
  assert.deepEqual(resolved.peers, [])
})
