import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { appendFileSync, cpSync, mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const manifest = JSON.parse(readFileSync(path.join(pluginRoot, "access-entry-files.json"), "utf8"))

test("staged access entry has its descriptor and answers discovery", () => {
  assert.equal(manifest.schema_version, 1)
  assert(manifest.required.includes("src/ordessa_harness/launch-descriptors.json"))
  const root = mkdtempSync(path.join(tmpdir(), "ordessa-harness-stage-"))
  try {
    for (const relative of manifest.required) {
      assert(!path.isAbsolute(relative) && !relative.split("/").includes(".."))
      const destination = path.join(root, relative)
      mkdirSync(path.dirname(destination), { recursive: true })
      cpSync(path.join(pluginRoot, relative), destination, { recursive: true })
    }
    const entry = path.join(root, "runtime", "access-entry.mjs")
    const run = spawnSync(process.execPath, [entry, "--native"], {
      cwd: root,
      input: '{"id":"discovery","op":"harnesses"}\n',
      encoding: "utf8",
      timeout: 10000,
    })
    assert.equal(run.status, 0, run.stderr)
    const answer = run.stdout.split("\n").filter(Boolean).map((line) => JSON.parse(line))
      .find((row) => row.id === "discovery")
    assert.equal(answer?.ok, true, run.stdout)
    assert(answer.result.harnesses.includes("claude"))
    assert(answer.result.harnesses.includes("claude-code"))
    assert(answer.result.harnesses.includes("omp"))
    const sourcePeer = path.resolve(pluginRoot, "..", "..", "tests", "integration", "acp_orchestration",
      "fixtures", "bidirectional_acp_peer.mjs")
    // The staged entry pins the same content digests as the source checkout
    // (spec 019: the allowlist locks content, not location), so the source
    // checkout's peer file is accepted from a path outside the staged closure.
    // What the stage must still refuse is *content that does not match* — a
    // one-byte tamper below — and content that matches an entry bound to a
    // different brand.
    const controlled = spawnSync(process.execPath, [entry, "--native", "--controlled-test-peer"], {
      cwd: root,
      env: { ...process.env, AGENTBOX_ACCESS_TEST_MODE: "controlled-peer-v1",
        HD003_LOG: path.join(root, "peer-log") },
      input: JSON.stringify({ id: "staged-peer", op: "connect", harness: "pi",
        launch: { command: process.execPath, args: [sourcePeer] }, directory: root }) + "\n"
        + JSON.stringify({ id: "staged-release", op: "close" }) + "\n",
      encoding: "utf8", timeout: 10000,
    })
    assert.equal(controlled.status, 0, controlled.stderr)
    const stagedLines = controlled.stdout.split("\n").filter(Boolean).map((line) => JSON.parse(line))
    const stagedAnswer = stagedLines.find((row) => row.id === "staged-peer")
    assert.equal(stagedAnswer?.ok, true, controlled.stdout)
    assert.equal(stagedAnswer?.result?.launch?.source, "controlled-test-peer")
    const release = stagedLines.find((row) => row.id === "staged-release")
    assert.equal(release?.result?.released, true, controlled.stdout)
    const tampered = path.join(root, "tampered-peer.mjs")
    cpSync(sourcePeer, tampered)
    appendFileSync(tampered, "\n// one comment line of changed content\n")
    const refusal = spawnSync(process.execPath, [entry, "--native", "--controlled-test-peer"], {
      cwd: root,
      env: { ...process.env, AGENTBOX_ACCESS_TEST_MODE: "controlled-peer-v1" },
      input: JSON.stringify({ id: "tampered-peer", op: "connect", harness: "pi",
        launch: { command: process.execPath, args: [tampered] }, directory: root }) + "\n",
      encoding: "utf8", timeout: 10000,
    })
    assert.equal(refusal.status, 0, refusal.stderr)
    const tamperLines = refusal.stdout.split("\n").filter(Boolean).map((line) => JSON.parse(line))
    assert.equal(tamperLines.find((row) => row.id === "tampered-peer")?.error?.code,
      "CONTROLLED_PEER_MISMATCH",
      "a one-byte content change refuses the peer in a staged artifact too")
    rmSync(path.join(root, "src", "ordessa_harness", "launch-descriptors.json"))
    const missing = spawnSync(process.execPath, [entry, "--native"], {
      cwd: root, input: '{"id":"discovery","op":"harnesses"}\n',
      encoding: "utf8", timeout: 10000,
    })
    assert.notEqual(missing.status, 0, "a stage missing the descriptor must not advertise brands")
    assert.match(missing.stderr, /launch-descriptors\.json/)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
