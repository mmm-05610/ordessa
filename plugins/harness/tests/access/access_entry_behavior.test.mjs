/**
 * The access entry's own guarantees — what `runtime/access-entry.mjs` must do as the process that
 * owns a connection, as opposed to what the relay must never do (that is
 * `acp_passthrough_target.test.mjs`, T1-T10).
 *
 * These are the retargeted survivors of `sidecar_boundary_behavior.test.mjs`, whose 12 cases were
 * written against the retired envelope: five reappear here over the new entry (home/directory
 * isolation, launch-context validation, the end-of-connection facts, native-identity separation,
 * per-connection process release), and the rest are mapped in `tests/RETIRED.md`. Each keeps the
 * counterexample it was written for; nothing here asserts the envelope's vocabulary, because the
 * envelope is gone.
 *
 * E9-E13 are the review round's four implementation holes, each pinned by the process behaviour that
 * exposes it: a release is only reportable once the OS has stopped answering for the pid (so the
 * fixture ignores `SIGTERM`), an establishment is claimed before it is awaited (so two connects can
 * only produce one Harness), a host that hangs up mid-launch is cleaned up on the way out, and a
 * frame that carries an `op` of its own is the Harness's, not the entry's.
 *
 * E20-E23 are the three boundaries the next review found in that reclaiming: a descendant two levels
 * down that left the group, a release that cannot read the process table and must therefore not claim
 * a tree, and a pid that has been handed out again to somebody else's process. E24-E25 close the hole
 * left inside that identity check — a check which cannot be carried out is not a check that passed —
 * and the same for the group number, which is now proved by who is in it *now* and not by who was.
 *
 * Everything is offline: a controlled ACP harness in temp directories with fake credentials only.
 * No real Agent, no model request, no credential read, no existing service started or stopped.
 */
import assert from "node:assert/strict"
import { mkdtemp, readdir, rm, cp, mkdir, readFile, writeFile } from "node:fs/promises"
import { readFileSync } from "node:fs"
import { spawn } from "node:child_process"
import { tmpdir } from "node:os"
import path from "node:path"
import test from "node:test"
import {
  Sidecar, alive, controlledHarness, entry, fixtureChildrenIn, harnessPidsIn, pluginRoot, sleep,
  waitAllGone, waitGone, withSidecar,
} from "./sidecar_harness.mjs"
import { releaseProcessTree } from "../../runtime/access-transport.mjs"
import { FIXTURE_CHILD_MARKER } from "./fixture_child_marker.mjs"

/**
 * Poll until a process-tree fact is observable, and fail by name if it never was.
 *
 * A child appearing, or a reparented orphan disappearing, is an OS event on somebody else's clock.
 * A fixed sleep would either make these cases flaky or make them measure nothing, so every tree
 * assertion waits for the state it is about to depend on and says which one it timed out on.
 */
async function waitFor(describe, probe, limitMs = 8_000) {
  const startedAt = Date.now()
  for (;;) {
    const value = probe()
    if (value) return value
    if (Date.now() - startedAt > limitMs) throw new Error(`timed out waiting for ${describe}`)
    await sleep(10)
  }
}

/** One client round trip far enough into the protocol that a process, cwd and session all exist. */
async function connected(sidecar, { harness = "codex" } = {}) {
  const connectedResult = await sidecar.connect({ harness })
  assert.equal(connectedResult.ok, true, JSON.stringify(connectedResult))
  const initialize = await sidecar.request({ op: "harnesses" })
  assert.equal(initialize.ok, true)
  const id = "entry-client-1"
  sidecar.writeRaw({ jsonrpc: "2.0", id, method: "initialize",
    params: { protocolVersion: 1, clientCapabilities: {}, clientInfo: { name: "entry-test", version: "test" } } })
  const reply = await sidecar.waitForFrame((frame) => frame.id === id && frame.result !== undefined, "initialize reply")
  const created = "entry-client-2"
  sidecar.writeRaw({ jsonrpc: "2.0", id: created, method: "session/new",
    params: { cwd: sidecar.cwd, mcpServers: [] } })
  await sidecar.waitForFrame((frame) => frame.id === created && frame.result !== undefined, "session/new reply")
  return { connectionId: connectedResult.result.connectionId, agentInfo: reply.result.agentInfo }
}

test("E1: connecting uses the explicit entry and the directory the caller named, and writes nothing into the Agent home", async () => {
  // Counterexamples: a connect that mints config into HOME, a native home swap, an installer
  // context injected into the adapter environment, or a project directory the Agent never sees.
  await withSidecar(async ({ sidecar, home, project }) => {
    await connected(sidecar)
    const [execution] = await sidecar.notes("exec")
    assert.equal(execution.cwd, project, "the adapter runs in the directory the caller named")
    assert.equal(execution.home, home, "the adapter keeps the environment the user already configured")
    assert.deepEqual(execution.homeEntries, [], "no native config may be manufactured for it")
    assert.deepEqual(execution.npmConfigKeys, [], "no installer context may be injected")
    assert.equal(execution.nodeOptions, null, "the launch must not rewrite how the Agent process runs")
    assert.equal(execution.isolationMarker, null, "native access must not require the sandbox marker")
    assert.deepEqual(await readdir(home), [], "the Agent home is still empty after a whole connection")
    assert.deepEqual(await readdir(project), [], "the project directory is not written either")
  })
})

test("E2: connect demands an explicit launch context, and the adapter environment is validated rather than trusted", async () => {
  // Counterexample in both directions: a launch with no command must be refused, and a
  // credential-shaped variable must never reach an Agent through the generic environment a
  // deployment may pass. A declared non-secret variable must still arrive.
  await withSidecar(async ({ sidecar }) => {
    const missing = await sidecar.request({ op: "connect", harness: "codex", launch: {} })
    assert.equal(missing.ok, false)
    assert.equal(missing.error.code, "ADAPTER_LAUNCH_REQUIRED")

    const secret = await sidecar.request({
      op: "connect", harness: "codex",
      launch: { command: process.execPath, args: [controlledHarness],
        environment: { DEEPSEEK_API_KEY: "sk-not-a-real-key" } },
    })
    assert.equal(secret.ok, false)
    assert.equal(secret.error.code, "ADAPTER_ENVIRONMENT_INVALID")

    const marker = await sidecar.request({
      op: "connect", harness: "codex",
      launch: { command: process.execPath, args: [controlledHarness],
        environment: { AGENTBOX_FIXTURE_MARKER: "declared" } },
    })
    assert.equal(marker.ok, true, JSON.stringify(marker))
    await sidecar.request({ op: "harnesses" })
    const [execution] = await sidecar.notes("exec")
    assert.equal(execution.marker, "declared", "a declared non-secret variable does reach the Agent")
  })
})

test("E3: an undirected frame, a second connection and a retired field are each refused by name", async () => {
  // Three ways a caller can still be living in the old chain, each refused rather than guessed at:
  // sending ACP before connecting (the entry must not invent a session to answer for), connecting
  // twice on a relay that cannot multiplex, and naming a knob that used to decide on the user's
  // behalf. Silently accepting any of them would leave the caller believing it worked.
  await withSidecar(async ({ sidecar }) => {
    sidecar.writeRaw({ jsonrpc: "2.0", id: "early", method: "initialize", params: {} })
    const early = await sidecar.waitForResponse("early")
    assert.equal(early.ok, false)
    assert.equal(early.error.code, "ACP_NOT_CONNECTED")
    assert.deepEqual(await sidecar.allNotes(), [], "a refused frame must not have reached the Agent")

    const retired = await sidecar.request({ op: "connect", harness: "pi", permissionRoundTrip: true })
    assert.equal(retired.ok, false)
    assert.match(retired.error.code, /RETIRED|UNKNOWN/)
    assert.match(retired.error.message, /permissionRoundTrip/, "the refusal names the field it refused")
    assert.deepEqual(await sidecar.allNotes(), [], "a refused connect must not have launched anything")

    await connected(sidecar)
    const again = await sidecar.connect()
    assert.equal(again.ok, false)
    assert.equal(again.error.code, "ACP_ALREADY_CONNECTED",
      "one byte-transparent relay cannot carry two Harnesses")

    const unknown = await sidecar.request({ op: "prompt", sessionId: "x", text: "y" })
    assert.equal(unknown.ok, false)
    assert.equal(unknown.error.code, "UNKNOWN_OP", "the entry has no per-turn op to fall back to")
  })
})

test("E4: status reports the connection and its process, and close and a crash stay two different facts", async () => {
  // The old chain borrowed one envelope for three states (cancel, disconnect, close). Two of them
  // belong to the client now — a cancel is a `session/cancel` frame the client sends and the Agent
  // settles — so what the entry owns is the difference between *I released this* and *it died*,
  // reported once each, with no terminal reason invented for the open turn.
  await withSidecar(async ({ sidecar }) => {
    const { connectionId } = await connected(sidecar)
    const status = await sidecar.request({ op: "status" })
    assert.equal(status.ok, true, JSON.stringify(status))
    assert.equal(status.result.connectionId, connectionId)
    assert.equal(status.result.state, "running")
    assert.equal(status.result.connected, true)
    const pid = status.result.processId
    assert.ok(alive(pid), "status names the process it is reporting on")

    const closed = await sidecar.request({ op: "close" })
    assert.equal(closed.result.released, true)
    assert.equal(closed.result.connectionId, connectionId)
    // Checked the instant the reply arrives, with no polling first: `released: true` is a claim about
    // a dead process, so a live pid at this point is the claim being false.
    assert.equal(closed.result.processId, pid, "the release names the process it says it confirmed")
    assert.equal(alive(pid), false, "close answers after the process is gone, not after it was asked")
    assert.equal(await waitGone(pid), true, "close releases the process the entry started")
    const end = await sidecar.waitForEvent("transport_end")
    assert.equal(end.data.reason, "closed_by_caller")
    assert.equal(end.connectionId, connectionId)
    const afterClose = await sidecar.request({ op: "status" })
    assert.equal(afterClose.error.code, "ACP_NOT_CONNECTED")
  })

  await withSidecar(async ({ sidecar }) => {
    const { connectionId } = await connected(sidecar)
    const [{ pid }] = await sidecar.notes("session/new")
    // An open turn that the Agent never answers: killing it must not produce a result.
    sidecar.writeRaw({ jsonrpc: "2.0", id: "dying-turn", method: "session/prompt",
      params: { sessionId: "unused", prompt: [{ type: "text", text: "hold" }] } })
    const beforeDeath = sidecar.streamFrames().length
    process.kill(pid)
    const end = await sidecar.waitForEvent("transport_end")
    assert.equal(end.data.reason, "adapter_exit")
    assert(typeof end.data.message === "string" && end.data.message.length > 0, "the exit says what happened")
    assert.equal(end.connectionId, connectionId)
    assert.notEqual(end.data.reason, "closed_by_caller", "a crash is never reported as a release")

    const reported = sidecar.streamFrames().slice(beforeDeath)
    const forged = reported.find((frame) => frame.id === "dying-turn" && frame.result !== undefined)
    assert.equal(forged, undefined, "the dead Agent is not answered on the client's behalf")
    const status = await sidecar.request({ op: "status" })
    assert.equal(status.result.state, "ended", "status keeps reporting the end, not a live process")
    assert.equal(status.result.connected, false)
  })
})

test("E5: two Sessions on one transport keep their own native ids and their own turn counters", async () => {
  // The entry does not own sessions, so it must not blur them either: the ids are the Agent's and
  // a frame addressed to one session may not be re-stamped for the other. This is the same
  // guarantee the old chain tested through `op:"create"`/`op:"prompt"`, now measured on frames the
  // client wrote.
  await withSidecar(async ({ sidecar }) => {
    await connected(sidecar)
    const opened = async (name) => {
      sidecar.writeRaw({ jsonrpc: "2.0", id: name, method: "session/new",
        params: { cwd: sidecar.cwd, mcpServers: [] } })
      const reply = await sidecar.waitForFrame((frame) => frame.id === name && frame.result !== undefined,
        `the reply to ${name}`)
      return reply.result.sessionId
    }
    const a = await opened("entry-session-a")
    const b = await opened("entry-session-b")
    assert.notEqual(a, b, "each Session keeps its own native identity")

    for (const [index, text] of [[1, "first turn"], [2, "second turn"]]) {
      const id = `entry-turn-${index}`
      sidecar.writeRaw({ jsonrpc: "2.0", id, method: "session/prompt",
        params: { sessionId: a, prompt: [{ type: "text", text }] } })
      await sidecar.waitForFrame((frame) => frame.id === id && frame.result !== undefined, `the reply to ${id}`)
      const prompts = (await sidecar.notes("prompt")).filter((row) => row.sessionId === a)
      assert.equal(prompts.length, index)
      assert.equal(prompts.at(-1).turn, index, "the Agent sees one continuing conversation")
    }
    const lonely = "entry-turn-b"
    sidecar.writeRaw({ jsonrpc: "2.0", id: lonely, method: "session/prompt",
      params: { sessionId: b, prompt: [{ type: "text", text: "only turn" }] } })
    await sidecar.waitForFrame((frame) => frame.id === lonely && frame.result !== undefined, `the reply to ${lonely}`)
    const bPrompts = (await sidecar.notes("prompt")).filter((row) => row.sessionId === b)
    assert.equal(bPrompts.length, 1, "the other Session's turn count is untouched")
    assert.equal(bPrompts[0].turn, 1, "turn counters do not cross Sessions")
  })
})

test("E6: discovery answers without a connection, and a brand that is not registered is refused", async () => {
  // Counterexample: a `harnesses` op that needs an Agent, or an unknown brand quietly launched
  // anyway because a command came with it. Discovery is the entry's own table, and the brand id
  // decides whether a connect is allowed at all.
  await withSidecar(async ({ sidecar }) => {
    const listed = await sidecar.request({ op: "harnesses" })
    assert.equal(listed.ok, true, JSON.stringify(listed))
    const ids = listed.result.harnesses
    for (const expected of ["claude", "claude-code", "codex", "dsh", "hermes", "kilo", "omp", "pi"]) {
      assert(ids.includes(expected), `${expected} must be discoverable`)
    }
    assert.equal(ids.includes("opencode"), false,
      "OpenCode is not registered in this round's brand scope; `connect` cannot serve a brand "
      + "discovery has no launch context for, so discovery must not advertise one either")
    assert.deepEqual(listed.result.transport, null)

    const refused = await sidecar.request({
      op: "connect", harness: "opencode",
      launch: { command: process.execPath, args: [controlledHarness] },
    })
    assert.equal(refused.ok, false)
    assert.equal(refused.error.code, "HARNESS_UNDISCOVERED")
    assert.deepEqual(await sidecar.allNotes(), [], "a refused brand must not have been launched")
  })
})

test("E7: closing one connection releases exactly its own Agent process, not the neighbour's", async () => {
  const home = await mkdtemp(path.join(tmpdir(), "agentbox-conv-home-"))
  const project = await mkdtemp(path.join(tmpdir(), "agentbox-conv-project-"))
  const one = new Sidecar()
  const two = new Sidecar()
  await one.start({ home, cwd: project })
  await two.start({ home, cwd: project })
  try {
    await connected(one)
    await connected(two)
    const pidOne = (await one.request({ op: "status" })).result.processId
    const pidTwo = (await two.request({ op: "status" })).result.processId
    assert.ok(pidOne && pidTwo && pidOne !== pidTwo)

    const closed = await one.request({ op: "close" })
    assert.equal(closed.result.released, true)
    assert.equal(await waitGone(pidOne), true)
    assert.equal(alive(pidTwo), true, "the other connection's Agent is untouched")

    // The surviving entry still reports its own connection after its neighbour released its process.
    const stillThere = await two.request({ op: "status" })
    assert.equal(stillThere.result.processId, pidTwo)
    assert.equal(alive(pidTwo), true, "closing one entry cannot reach into another's process")
    await two.request({ op: "close" })
    assert.equal(await waitGone(pidTwo), true)
  } finally {
    await one.closeProcess()
    await two.closeProcess()
    for (const directory of [home, project, one.state, two.state]) {
      await rm(directory, { recursive: true, force: true }).catch(() => undefined)
    }
  }
})

test("E8: the execution-mode gate and the provenance check fail closed", async () => {
  // The native entry refuses the sandbox marker (and vice versa), refuses an unrecognised flag, and
  // refuses to run at all against a snapshot whose bytes do not match the recorded hashes. A
  // relay that stopped verifying would silently run patched-vendored code nobody signed off on.
  for (const [args, environment, code] of [
    [["--native"], { AGENTBOX_SIDECAR_ISOLATED: "1" }, "SIDECAR_MODE_CONFLICT"],
    [[], {}, "SIDECAR_ISOLATION_REQUIRED"],
    [["--unsupported"], { AGENTBOX_SIDECAR_ISOLATED: "1" }, "SIDECAR_MODE_INVALID"],
  ]) {
    const output = await runEntry(args, environment)
    assert.match(output, new RegExp(code), `${JSON.stringify(args)} / ${JSON.stringify(environment)}`)
  }

  const root = await mkdtemp(path.join(tmpdir(), "agentbox-entry-tamper-"))
  try {
    await mkdir(root, { recursive: true })
    for (const directory of ["runtime", "third_party", "harnesses"]) {
      await cp(path.join(pluginRoot, directory), path.join(root, directory), { recursive: true })
    }
    await mkdir(path.join(root, "src", "ordessa_harness"), { recursive: true })
    await cp(path.join(pluginRoot, "src", "ordessa_harness", "launch-descriptors.json"),
      path.join(root, "src", "ordessa_harness", "launch-descriptors.json"))
    const victim = path.join(root, "third_party", "harness_remote", "bridge", "src", "acp-client.js")
    await writeFile(victim, `${await readFile(victim, "utf8")}\n// tampered\n`)
    const output = await runEntry(["--native"], {}, path.join(root, "runtime", "access-entry.mjs"))
    assert.match(output, /PROVENANCE_MISMATCH: bridge\/src\/acp-client\.js/, "the tamper is named, not swallowed")
    assert.doesNotMatch(output, /"ok":true/, "a tampered snapshot must not answer any op")
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test("E9: a release is reported only once the process is gone, escalating past an ignored SIGTERM", async () => {
  // Counterexample: a Harness that traps the graceful signal and keeps running. Delivering `SIGTERM`
  // is not a death, so an entry that answered `released: true` there would hand the caller a dead-
  // sounding receipt, a null pid and no handle over a process that is still serving — the one
  // outcome the last responsibility exists to prevent. The fixture proves its own counterexample by
  // recording that the signal arrived and was refused.
  await withSidecar(async ({ sidecar }) => {
    const { connectionId } = await connected(sidecar)
    const pid = (await sidecar.request({ op: "status" })).result.processId
    assert.ok(alive(pid), "the Harness is up while the caller still has a connection to close")

    const closed = await sidecar.request({ op: "close" })
    assert.equal(closed.ok, true, JSON.stringify(closed))
    assert.equal(closed.result.released, true, JSON.stringify(closed.result))
    assert.equal(closed.result.connectionId, connectionId)
    assert.equal(closed.result.processId, pid, "the report names the process it confirmed gone")
    assert.equal(closed.result.signalUsed, "SIGKILL", "the report says which signal it had to use")
    assert.equal(alive(pid), false, "the reply arrives after the death, not after the signal")
    const ignored = await sidecar.notes("sigterm-ignored")
    assert.ok(ignored.length >= 1, "the graceful signal was really refused, so the escalation was needed")
  }, { AGENTBOX_FIXTURE_SIGTERM: "ignore" })
})

test("E9b: a release the OS will not confirm is a failure, with the process identity kept", async () => {
  // `released: false` needs a process that survives `SIGKILL`, and none does — a case that spawned a
  // real one to reach this branch would be claiming something it cannot build. So the policy is
  // exercised directly, with a stand-in that never answers for the pid, and E9 covers what the entry
  // does with the answer over a process that really exists.
  const delivered = []
  const refusesToDie = (target, name) => {
    if (name !== 0) delivered.push({ target, name })
    throw Object.assign(new Error("operation not permitted"), { code: "EPERM" })
  }
  const stuck = await releaseProcessTree({
    rootPid: 4242, graceMs: 40, forceMs: 40, pollMs: 5, signal: refusesToDie, wait: sleep,
    // The group identity is injected because 4242 is not a process this machine is running: what is
    // under test is what the release *does* with a tree it is told about. The identity that is injected
    // is the one the OS then confirms, so that this case stays about a process that will not die and
    // not about a member the release was not allowed to point at (E24 covers that one).
    identify: () => "1000",
    discover: () => [{ pid: 4242, group: 4242, identity: "1000" }],
  })
  assert.equal(stuck.released, false, "a deadline with a live process is reported as a failure")
  assert.equal(stuck.processId, 4242, "the identity survives, because it is the only way to keep looking")
  assert.deepEqual(stuck.tree.survivors, [4242], "and the report names what is still running")
  assert.deepEqual([...new Set(delivered.map((attempt) => attempt.target))], [-4242],
    "a member of the launched group is reached through the group, never by a private signal")
  assert.deepEqual([...new Set(delivered.map((attempt) => attempt.name))], ["SIGTERM", "SIGKILL"],
    "graceful first, then the signal that cannot be trapped")

  const alreadyGone = []
  const answered = await releaseProcessTree({
    rootPid: 4243, pollMs: 5,
    signal: (target, name) => {
      if (name !== 0) alreadyGone.push(target)
      throw Object.assign(new Error("no such process"), { code: "ESRCH" })
    },
    discover: () => [{ pid: 4243, group: 4243 }],
    wait: sleep,
  })
  assert.equal(answered.released, true)
  assert.equal(answered.processId, 4243)
  assert.equal(answered.signalUsed, null)
  assert.deepEqual(alreadyGone, [], "a process the OS has already forgotten is not signalled again")
})

test("E14: only ESRCH proves an exit — an odd probe answer is not a death", async () => {
  // Counterexample: a liveness probe that treats "the OS threw something" as "it is gone". A security
  // module returning `EACCES`, or an `EINVAL`, says nothing about whether the Harness is still
  // serving, and a release that folded it into a death would report `released: true` over a live
  // process while keeping no evidence of why it stopped looking.
  for (const code of ["EACCES", "EINVAL", "ENOENT"]) {
    const delivered = []
    const confused = (target, name) => {
      if (name !== 0) delivered.push(target)
      throw Object.assign(new Error(`the os said ${code}`), { code })
    }
    const report = await releaseProcessTree({
      rootPid: 4343, graceMs: 20, forceMs: 20, pollMs: 5, signal: confused, wait: sleep,
      // The members carry an identity this release can confirm, so the answer under test stays the one
      // the *probe* gave: an unverifiable member is refused earlier than this, whatever it answers (E24).
      identify: () => "1000",
      discover: () => [{ pid: 4343, group: 4343, identity: "1000" }],
    })
    assert.equal(report.released, false, `${code} is not evidence of an exit (release claimed ${report.released})`)
    assert.equal(report.processId, 4343, `${code} keeps the identity, so somebody can keep looking`)
    assert.deepEqual(report.tree.unconfirmed, [{ pid: 4343, code }], `${code} is reported as what it is`)
    assert.deepEqual(report.tree.survivors, [], "and it is not counted among the confirmed deaths either")
    assert.ok(delivered.length, `${code} still gets an attempt rather than being left alone`)
  }

  // The same distinction one level over: a bridge that really has exited does not make a child whose
  // probe is unanswerable into a reclaimed process.
  const mixed = await releaseProcessTree({
    rootPid: 4444, graceMs: 20, forceMs: 20, pollMs: 5, wait: sleep,
    discover: () => [{ pid: 4444, group: 4444 }, { pid: 4445, group: 4444 }],
    signal: (target, name) => {
      if (name === 0 && target === 4445) throw Object.assign(new Error("not permitted"), { code: "EACCES" })
      if (target === 4444 || target === -4444) throw Object.assign(new Error("no such process"), { code: "ESRCH" })
      return undefined
    },
  })
  assert.equal(mixed.released, false, "a dead bridge next to an unanswerable child is not a clean release")
  assert.deepEqual(mixed.tree.members.map((member) => member.state), ["gone", "unconfirmed"],
    "the report keeps those two facts apart instead of averaging them")
})

test("E15: without a process table to read, a tree is never reported as reclaimed", async () => {
  // Counterexample: `discover` answers `null` (no process table to walk) and the root pid is gone. The
  // OS has then answered for exactly one process, and the launch that owned it may have had children —
  // so the case decides between the two claims a release can make, not between a claim and nothing:
  // under the tree claim it refuses, and only a release that said "root only" from the start may answer
  // `true`, with the narrower scope left on the receipt so nobody reads it as the wider one.
  const child = spawn(process.execPath, ["-e", "setTimeout(() => undefined, 60000)", FIXTURE_CHILD_MARKER], { stdio: "ignore" })
  const targets = []
  const wrap = (target, name) => {
    if (name !== 0) targets.push(target)
    return process.kill(target, name)
  }
  try {
    const unclaimed = await releaseProcessTree({
      rootPid: child.pid, rootIdentity: procField(child.pid, 19), claim: "tree",
      graceMs: 2_000, forceMs: 1_000, pollMs: 10,
      discover: () => null, signal: wrap, wait: sleep,
    })
    assert.equal(unclaimed.tree.available, false, "the report says the tree could not be accounted for")
    assert.equal(unclaimed.released, false,
      `a root that stopped answering is not evidence about processes nobody could enumerate: ${JSON.stringify(unclaimed.tree)}`)
    assert.equal(unclaimed.tree.reason, "PROCESS_TABLE_UNAVAILABLE", "and the report names what defeated the claim")
    assert.deepEqual([...new Set(targets)], [child.pid], "the root alone is signalled; no group is aimed at blind")
    assert.equal(alive(child.pid), false, "and that root really did stop answering")

    const second = spawn(process.execPath, ["-e", "setTimeout(() => undefined, 60000)", FIXTURE_CHILD_MARKER], { stdio: "ignore" })
    const narrower = await releaseProcessTree({
      rootPid: second.pid, rootIdentity: procField(second.pid, 19), claim: "root-only",
      graceMs: 2_000, forceMs: 1_000, pollMs: 10,
      discover: () => null, signal: process.kill, wait: sleep,
    })
    assert.equal(narrower.released, true, "what this release did account for — one process — is what it got credit for")
    assert.equal(narrower.tree.scope, "root-only", "and the receipt carries the smaller scope, not the word 'tree'")
    assert.equal(alive(second.pid), false)
  } finally {
    try { process.kill(child.pid, "SIGKILL") } catch { /* already gone */ }
  }
})

test("E10: two connects at once establish one Harness, and the loser is refused by name", async () => {
  // Counterexample: the emptiness of `connection` is checked before the launch is awaited and filled
  // after it, so a second connect arriving in that window starts a second process whose handle the
  // first then overwrites — one survives, the other runs unmanaged. Exactly one Harness may exist at
  // the end of this, and it may be released.
  await withSidecar(async ({ sidecar, project }) => {
    const [one, two] = await Promise.all([sidecar.connect(), sidecar.connect()])
    assert.equal(one.ok, true, `the connect that arrived first establishes: ${JSON.stringify(one)}`)
    assert.equal(two.ok, false, "the one that arrived during it is refused, not served a second process")
    assert.equal(two.error.code, "ACP_CONNECT_IN_PROGRESS", JSON.stringify(two))
    assert.equal(two.result, undefined, "a refused connect hands out no handle")

    const executions = await sidecar.notes("exec")
    assert.equal(executions.length, 1, "the refused connect launched no second process")

    const live = await sidecar.request({ op: "status" })
    assert.equal(live.ok, true, "the connection that did establish is usable")
    assert.equal(alive(live.result.processId), true)
    const closed = await sidecar.request({ op: "close" })
    assert.equal(closed.result.released, true)
    assert.equal(alive(live.result.processId), false, "nothing is left running behind the two connects")
    assert.deepEqual(harnessPidsIn(project), [],
      "and the process table agrees: the unmanaged second Harness the bug would have left is not there")
  })
})

test("E11: a close that arrives during an establishment waits and releases what it produced", async () => {
  // Refusing here would be answerable — there is no connection yet — and would leave the Harness that
  // the in-flight connect spawns owned by nobody. The honest version is to wait for the outcome and
  // release it, which is what this measures: one process, and it is gone.
  await withSidecar(async ({ sidecar, project }) => {
    const establishing = sidecar.connect()
    const closed = await sidecar.request({ op: "close" })
    const established = await establishing
    assert.equal(established.ok, true, JSON.stringify(established))
    assert.equal(closed.ok, true, JSON.stringify(closed))
    assert.equal(closed.result.released, true, JSON.stringify(closed.result))
    assert.equal(closed.result.connectionId, established.result.connectionId,
      "the close answered for the very connection it waited on")
    assert.equal(alive(established.result.state.processId), false,
      "the process the close arrived during is gone")
    // Measured from the process table rather than from the harness's own record: this one was
    // released while it was still booting, so it never got to write anything, which is exactly the
    // fact a "nothing is left running" claim must not depend on.
    assert.deepEqual(harnessPidsIn(project), [], "no Harness is left running in the project directory")
    const status = await sidecar.request({ op: "status" })
    assert.equal(status.error.code, "ACP_NOT_CONNECTED", "and there is no connection left to report")
  })
})

test("E12: a host that hangs up mid-establishment leaves no Harness behind", async () => {
  // The same window E10 reserves, reached from the other side: the process exists before the entry
  // can answer, `connection` is still null, and an exit path that released only `connection` would
  // strand it. The fixture is told to keep serving after its stdin closes, so a Harness this entry
  // walks away from is still there to be found in the process table — which is what makes this a
  // measurement rather than the fixture leaving with its parent.
  const home = await mkdtemp(path.join(tmpdir(), "agentbox-conv-home-"))
  const project = await mkdtemp(path.join(tmpdir(), "agentbox-conv-project-"))
  const sidecar = new Sidecar({ AGENTBOX_FIXTURE_HOLD_OPEN: "1" })
  await sidecar.start({ home, cwd: project })
  try {
    assert.deepEqual(harnessPidsIn(project), [], "this project directory starts out holding nothing")
    sidecar.writeRaw({
      op: "connect", id: "e12-launch", harness: "codex",
      launch: { command: process.execPath, args: [controlledHarness] }, directory: sidecar.cwd,
    })
    sidecar.endStdin()
    const exitCode = await sidecar.waitForExit()
    assert.equal(exitCode, 0, "the entry finished its cleanup before leaving")
    assert.deepEqual(harnessPidsIn(project), [], "the Harness started during startup was released on the way out")
    const launch = sidecar.streamFrames().find((frame) => frame.id === "e12-launch")
    assert.ok(launch, "the entry reported the establishment it was in the middle of")
    assert.equal(alive(launch.result.state.processId), false,
      `and the pid it claimed, ${launch.result.state.processId}, is not in the process table any more`)
    assert.equal(sidecar.streamFrames().find((frame) => frame.event === "process_release_unconfirmed"), undefined,
      "it did not have to report a failure to say so")
  } finally {
    await sidecar.closeProcess()
    for (const directory of [home, project, sidecar.state]) {
      await rm(directory, { recursive: true, force: true }).catch(() => undefined)
    }
  }
})

test("E13: an ACP frame carrying an `op` extension field is relayed, not eaten as control", async () => {
  // `op` is a legal member of a Harness's own frame vocabulary, and a relay that keyed its control
  // plane on that name alone would answer such a frame itself with `UNKNOWN_OP` while the Agent never
  // saw it. Two facts have to hold at once: the frame reaches the Agent with its extension fields
  // intact and is answered by the Agent, and this entry's own control envelope is still control.
  await withSidecar(async ({ sidecar }) => {
    await connected(sidecar)
    sidecar.writeRaw({ jsonrpc: "2.0", id: "e13-session", method: "session/new",
      params: { cwd: sidecar.cwd, mcpServers: [] } })
    const created = await sidecar.waitForFrame((frame) => frame.id === "e13-session" && frame.result !== undefined,
      "the session/new reply")

    sidecar.writeRaw({ jsonrpc: "2.0", id: "e13-frame", method: "session/prompt",
      params: { sessionId: created.result.sessionId, prompt: [{ type: "text", text: "carries an op" }] },
      op: "agentbox-test-extension", tag: "e13" })
    const answered = await sidecar.waitForFrame(
      (frame) => frame.id === "e13-frame" && frame.result?.stopReason !== undefined,
      "the Agent's own reply to the frame")
    assert.equal(answered.jsonrpc, "2.0", "the reply is the Harness's, in the Harness's shape")
    assert.equal(sidecar.streamFrames().find((frame) => frame.id === "e13-frame" && frame.ok === false), undefined,
      "the entry answered nothing on the Harness's behalf")

    const [note] = (await sidecar.notes("prompt")).filter((row) => row.text === "carries an op")
    assert.ok(note, "the frame reached the Agent at all")
    assert.deepEqual(note.extensionKeys, ["op", "tag"], "with both extension fields, as top-level members")
    assert.deepEqual(note.extension, { op: "agentbox-test-extension", tag: "e13" },
      "and unchanged values: the relay added, removed and rewrote nothing")

    const control = await sidecar.request({ op: "status" })
    assert.equal(control.ok, true, "a control object is still handled here")
    assert.equal(control.result.connected, true, "and it reports the same connection the frame went through")
  })
})

async function runEntry(args, extraEnvironment, target = entry) {
  const child = spawn(process.execPath, [target, ...args], {
    env: { ...process.env, HOME: "/tmp", ...extraEnvironment },
    cwd: "/tmp", stdio: ["pipe", "pipe", "pipe"],
  })
  let output = ""
  child.stdout.setEncoding("utf8")
  child.stdout.on("data", (chunk) => { output += chunk })
  child.stdin.end()
  await Promise.race([
    new Promise((resolve) => child.on("close", resolve)),
    new Promise((resolve) => setTimeout(() => { child.kill(); resolve() }, 6000)),
  ])
  return output
}

/**
 * E16–E20, E23: the release owns a *tree*, not a pid.
 *
 * A production ACP launch is a launcher: `npx … codex-acp` (or a wrapper binary) starts the real
 * Agent as its own child and pipes to it. Killing the bridge therefore stops nothing, and a `close`
 * that reported `released: true` after signalling only the bridge would be the same false receipt
 * round 4 found, moved one level down. These four cases drive the real entry with real children and
 * ask the process table afterwards — the fixture's own record cannot be the witness, because the
 * interesting runs are the ones where it was killed before it wrote anything.
 */
async function connectedWithTree(sidecar, environment, { project, except = [] } = {}) {
  const connect = await sidecar.connect({ launch: { environment } })
  assert.equal(connect.ok, true, JSON.stringify(connect))
  const rootPid = connect.result.state.processId
  const expected = Number(environment.AGENTBOX_FIXTURE_CHILDREN ?? "0")
    + Number(environment.AGENTBOX_FIXTURE_GRANDCHILDREN ?? "0")
  const mine = () => fixtureChildrenIn(project).filter((pid) => !except.includes(pid))
  const children = await waitFor(`the launch to have ${expected} descendant processes`,
    () => (mine().length === expected ? mine() : null))
  return { rootPid, children }
}

/**
 * One of the fixed `/proc/<pid>/stat` fields, counted back from the command name the way the
 * production reader counts them: field 1 is the parent, field 2 the process group.
 *
 * The tests ask the process table these questions directly rather than reusing the module under test,
 * so that "did the release account for this grandchild" cannot be answered by the same code that
 * decided to account for it.
 */
function procField(pid, index) {
  try {
    const stat = readFileSync(`/proc/${pid}/stat`, "utf8")
    return Number(stat.slice(stat.lastIndexOf(")") + 1).trim().split(/\s+/)[index])
  } catch {
    return null
  }
}
const parentOf = (pid) => procField(pid, 1)
const groupOf = (pid) => procField(pid, 2)

test("E16: close reclaims the children the launch started, not only the process it spawned", async () => {
  await withSidecar(async ({ sidecar, project }) => {
    const { rootPid, children } = await connectedWithTree(
      sidecar, { AGENTBOX_FIXTURE_CHILDREN: "2" }, { project })
    assert.equal(alive(rootPid), true, "the bridge is up")
    for (const child of children) assert.equal(alive(child), true, "and so is each child of it")

    const closed = await sidecar.request({ op: "close" })
    assert.equal(closed.ok, true, JSON.stringify(closed))
    assert.equal(closed.result.released, true, JSON.stringify(closed.result))
    // The receipt has to name what it reclaimed: `released: true` with no per-process evidence is
    // exactly the claim this round exists to make provable.
    const reclaimed = closed.result.tree.members.map((member) => member.pid).sort((a, b) => a - b)
    assert.deepEqual(reclaimed, [rootPid, ...children].sort((a, b) => a - b),
      "the evidence covers the bridge and both of its children")
    assert.deepEqual(closed.result.tree.survivors, [])
    for (const pid of [rootPid, ...children]) {
      assert.equal(alive(pid), false, `pid ${pid} stopped answering the instant the reply arrived`)
    }
    assert.deepEqual(fixtureChildrenIn(project), [], "and nothing from this launch is left in the table")
  })
})

test("E17: a bridge that exits first does not release its children out from under the report", async () => {
  // Counterexample: the handle stops being able to see the process the moment the client reports the
  // exit, and an early return there — "the root is gone, so the release succeeded" — is precisely a
  // false receipt for the child that is still serving. The group outlives its leader, so this is
  // measurable: the children are up, the root is not, and the close still has to end with none.
  await withSidecar(async ({ sidecar, project }) => {
    const { rootPid, children } = await connectedWithTree(sidecar, {
      AGENTBOX_FIXTURE_CHILDREN: "2",
      AGENTBOX_FIXTURE_PARENT_EXITS_AFTER_MS: "120",
    }, { project })
    await waitFor("the bridge to exit on its own", () => (alive(rootPid) ? null : true))
    for (const child of children) {
      assert.equal(alive(child), true, `child ${child} is reparented, not exited — it is still running`)
    }

    const closed = await sidecar.request({ op: "close" })
    assert.equal(closed.ok, true, JSON.stringify(closed))
    assert.equal(closed.result.released, true,
      `the release may not hide behind the dead bridge: ${JSON.stringify(closed.result)}`)
    assert.deepEqual(closed.result.tree.survivors, [], "and it says so member by member")
    assert.deepEqual(await waitAllGone(children), [], "every child of the launch is really gone")
    assert.deepEqual(fixtureChildrenIn(project), [])
  })
})

test("E18: a child that moved itself out of the group is still accounted for", async () => {
  // Counterexample: `kill(-groupPid)` reaches what stayed in the group and nothing else. A child that
  // started its own session is invisible to that signal, so the only reason this case can pass is the
  // parent link — which is also why the release walks the tree rather than trusting group membership.
  await withSidecar(async ({ sidecar, project }) => {
    const { rootPid, children } = await connectedWithTree(sidecar, {
      AGENTBOX_FIXTURE_CHILDREN: "1",
      AGENTBOX_FIXTURE_CHILD_ESCAPES: "1",
    }, { project })
    assert.equal(children.length, 1)

    const closed = await sidecar.request({ op: "close" })
    assert.equal(closed.result.released, true, JSON.stringify(closed.result))
    assert.ok(closed.result.tree.members.some((member) => member.pid === children[0]),
      "the escaped child appears in the reclaimed set even though no group signal could reach it")
    assert.deepEqual(await waitAllGone([children[0]]), [], `and pid ${children[0]} is gone`)
    assert.equal(alive(rootPid), false)
    assert.deepEqual(fixtureChildrenIn(project), [])
  })
})

test("E19: an unrelated process running the same thing in the same directory is left alone", async () => {
  // Counterexample: a cleanup that swept by command line or by working directory would "reclaim"
  // this decoy, and every other test running concurrently in this checkout. Nothing in the release is
  // keyed on what a process *is* — only on whether this launch started it.
  const home = await mkdtemp(path.join(tmpdir(), "agentbox-conv-home-"))
  const project = await mkdtemp(path.join(tmpdir(), "agentbox-conv-project-"))
  const sidecar = new Sidecar()
  await sidecar.start({ home, cwd: project })
  const decoy = spawn(process.execPath,
    ["-e", "setInterval(() => undefined, 1000)", FIXTURE_CHILD_MARKER], { cwd: project, stdio: "ignore" })
  try {
    await waitFor("the decoy to appear", () => (alive(decoy.pid) ? true : null))
    assert.ok(fixtureChildrenIn(project).includes(decoy.pid),
      "the decoy is indistinguishable from a real child by command line and directory alone")

    const { rootPid, children } = await connectedWithTree(
      sidecar, { AGENTBOX_FIXTURE_CHILDREN: "1" }, { project, except: [decoy.pid] })
    const closed = await sidecar.request({ op: "close" })
    assert.equal(closed.result.released, true, JSON.stringify(closed.result))

    const reclaimed = closed.result.tree.members.map((member) => member.pid)
    assert.ok(!reclaimed.includes(decoy.pid), "the decoy is not in the reclaimed set")
    assert.deepEqual(reclaimed.sort((a, b) => a - b), [rootPid, ...children].sort((a, b) => a - b))
    assert.equal(alive(decoy.pid), true, "and it is still running: this release stops what it started")
  } finally {
    try { process.kill(decoy.pid, "SIGKILL") } catch { /* already gone */ }
    await sidecar.closeProcess()
    await sleep(50)
    for (const pid of [...harnessPidsIn(project), ...fixtureChildrenIn(project)]) {
      try { process.kill(pid, "SIGKILL") } catch { /* already gone */ }
    }
    for (const directory of [home, project, sidecar.state]) {
      await rm(directory, { recursive: true, force: true }).catch(() => undefined)
    }
  }
})

test("E20: a grandchild that left the group is found through the member it came from", async () => {
  // Counterexample, one level deeper than E18: the bridge's child stays in the launched group, so the
  // group rule files it as a member, and *that child* starts a process of its own which leaves the
  // group. Nothing but continuing the parent-link walk through an already-filed member can reach it,
  // and a walk that reads "collected" as "looked inside" returns the bridge and its child, reports
  // `released: true`, and leaves the grandchild running for the life of the machine. The process table
  // is the witness for all three claims below — the parent link, the group, and the death.
  await withSidecar(async ({ sidecar, project }) => {
    const { rootPid, children } = await connectedWithTree(sidecar, {
      AGENTBOX_FIXTURE_CHILDREN: "1",
      AGENTBOX_FIXTURE_GRANDCHILDREN: "1",
    }, { project })
    assert.equal(children.length, 2, "two marked descendants are running before anything is closed")
    const grandchild = children.find((pid) => children.includes(parentOf(pid)))
    assert.ok(grandchild !== undefined, "the process table says one of them is the child of the other")
    const child = children.find((pid) => pid !== grandchild)
    assert.equal(parentOf(grandchild), child)
    // The two halves of the shape, measured rather than assumed: the middle process is inside the
    // group the launch owns, the last one is not.
    assert.equal(groupOf(child), rootPid, "the child stayed in the launched group")
    assert.notEqual(groupOf(grandchild), rootPid, "the grandchild is out of it, so no group signal reaches it")

    const closed = await sidecar.request({ op: "close" })
    assert.equal(closed.ok, true, JSON.stringify(closed))
    assert.equal(closed.result.released, true, JSON.stringify(closed.result))
    assert.deepEqual(closed.result.tree.members.map((member) => member.pid).sort((a, b) => a - b),
      [rootPid, child, grandchild].sort((a, b) => a - b),
      "the receipt names the bridge, its child and the grandchild no group signal could reach")
    assert.ok(closed.result.tree.members.every((member) => member.state === "gone"),
      JSON.stringify(closed.result.tree.members))
    assert.deepEqual(await waitAllGone([grandchild]), [], `pid ${grandchild} really stopped answering`)
    assert.deepEqual(fixtureChildrenIn(project), [], "and nothing from this launch is left in the table")
  })
})

test("E21: a pid the OS describes as a different process is never signalled", async () => {
  // Counterexample: the number was recorded at start time "1000"; by the release, the OS says the
  // process holding that number started at "9999". The one this launch started is gone — a pid is not
  // handed out again while its holder lives — and something else occupies the number now. That other
  // process is *killable* by us, which is the point: a recycled pid does not reliably answer `EPERM`,
  // so a release that keyed its safety on that answer would signal a stranger and report a reclaim.
  const delivered = []
  const aliveAndMine = (target, name) => {
    if (name !== 0) delivered.push(target)
    return undefined
  }
  const identify = (pid) => (pid === 4545 ? "9999" : "1000")

  const rootOnly = await releaseProcessTree({
    rootPid: 4545, rootIdentity: "1000", claim: "root-only",
    graceMs: 20, forceMs: 20, pollMs: 5, wait: sleep, signal: aliveAndMine, identify,
    discover: () => [{ pid: 4545, group: null, identity: "1000" }],
  })
  assert.deepEqual(delivered, [], "no signal is aimed at a number that is demonstrably somebody else's")
  assert.deepEqual(rootOnly.tree.identityChanged, [4545], "and the report says which member it declined to touch")
  assert.deepEqual(rootOnly.tree.survivors, [], "it is not a survivor of this launch — the recorded process exited")
  assert.equal(rootOnly.released, true, JSON.stringify(rootOnly))

  // The same veto one member over, where the group is still ours: only the number that moved on is
  // left alone, and the release keeps working for everybody else in the tree.
  const both = []
  let groupHit = false
  const report = await releaseProcessTree({
    rootPid: 4545, rootIdentity: "1000", graceMs: 20, forceMs: 20, pollMs: 5, wait: sleep,
    identify: (pid) => (pid === 4546 ? "9999" : "1000"),
    discover: () => [{ pid: 4545, group: 4545, identity: "1000" }, { pid: 4546, group: null, identity: "1000" }],
    signal: (target, name) => {
      if (name === 0) {
        // The bridge answers while the group has not been hit; the stranger's number answers `ESRCH`
        // for the process this launch recorded there, which is the only part of it anybody may claim.
        if (target === 4545 && !groupHit) return undefined
        throw Object.assign(new Error("no such process"), { code: "ESRCH" })
      }
      both.push(target)
      if (target === -4545) groupHit = true
      return undefined
    },
  })
  assert.ok(!both.includes(4546), "4546 is a stranger and stays untouched")
  assert.ok(both.includes(-4545), "the group is reached as a group while its own number is still ours")
  assert.deepEqual(report.tree.identityChanged, [4546], JSON.stringify(report.tree))
  assert.deepEqual(report.tree.survivors, [])
  assert.equal(report.released, true, "a stranger is not an unreleased process of ours")
})

test("E22: a group is aimed at only while a process the launch recorded answers to that number", async () => {
  // Counterexample: `kill(-rootPid, …)` is a signal aimed at a *number*, and a number can be handed
  // out again to a process that led a group of its own. Every member this release recorded under the
  // group number has demonstrably been replaced, so the group has no witness left that this launch
  // owns it — while one process it started outside the group is still live and still ours. Firing at
  // the group would reach whoever runs there now; the release has to keep working for 4647 without it.
  const delivered = []
  const report = await releaseProcessTree({
    rootPid: 4646, rootIdentity: "1000", graceMs: 20, forceMs: 20, pollMs: 5, wait: sleep,
    identify: (pid) => (pid === 4646 ? "94646" : "1000"),
    discover: () => [{ pid: 4646, group: 4646, identity: "1000" }, { pid: 4647, group: null, identity: "1000" }],
    signal: (target, name) => {
      if (name === 0) {
        // 4646 is somebody else's now and answers for nothing; 4647 is ours and will not stop.
        if (target === 4646) throw Object.assign(new Error("no such process"), { code: "ESRCH" })
        return undefined
      }
      delivered.push(target)
      return undefined
    },
  })
  assert.ok(!delivered.includes(-4646), JSON.stringify(delivered))
  assert.ok(delivered.includes(4647), "the member that is still ours is still reached, one pid at a time")
  assert.deepEqual(report.tree.identityChanged, [4646])
  assert.deepEqual(report.tree.survivors, [4647], "and the one that outlived every signal is named as the failure")
  assert.equal(report.released, false, JSON.stringify(report))
})

test("E23: an orphan's escaped child is found by both rules at once, with no parent link left", async () => {
  // E20 and E17 together, because the combination is what shows the two collection rules are not
  // redundant. The bridge exits first: the parent link from the root now leads nowhere, so the orphan
  // is a member only by its group number — and that orphan started a child of its own which left the
  // group, so the grandchild exists in the reclaimed set only if the walk expands a process the group
  // rule filed. Seed the walk from the root alone, or refuse to descend into a member already
  // collected, and this is the case that goes red while the simpler ones stay green.
  await withSidecar(async ({ sidecar, project }) => {
    const { rootPid, children } = await connectedWithTree(sidecar, {
      AGENTBOX_FIXTURE_CHILDREN: "1",
      AGENTBOX_FIXTURE_GRANDCHILDREN: "1",
      AGENTBOX_FIXTURE_PARENT_EXITS_AFTER_MS: "120",
    }, { project })
    const grandchild = children.find((pid) => children.includes(parentOf(pid)))
    assert.ok(grandchild !== undefined, "the process table says one of the two is a child of the other")
    const child = children.find((pid) => pid !== grandchild)
    await waitFor("the bridge to exit on its own", () => (alive(rootPid) ? null : true))
    assert.equal(groupOf(child), rootPid, "the orphan still carries the number of the group this launch owns")
    assert.notEqual(groupOf(grandchild), rootPid, "and its child left that group before the parent died")
    for (const pid of [child, grandchild]) {
      assert.equal(alive(pid), true, `pid ${pid} is still running with nothing above it in the launch`)
    }

    const closed = await sidecar.request({ op: "close" })
    assert.equal(closed.ok, true, JSON.stringify(closed))
    assert.equal(closed.result.released, true, JSON.stringify(closed.result))
    assert.deepEqual(closed.result.tree.members.map((member) => member.pid).sort((a, b) => a - b),
      [rootPid, child, grandchild].sort((a, b) => a - b),
      "dead root, the orphan the group rule found, and the descendant only the parent link inside it finds")
    assert.deepEqual(await waitAllGone([child, grandchild]), [], "and both outlived nobody")
    assert.deepEqual(fixtureChildrenIn(project), [])
  })
})

test("E24: an identity that cannot be re-read is not an identity that was checked", async () => {
  // Counterexample, and it is the shape the last round left open: a member *is* recorded with an
  // identity, so nothing contradicts it, and the check that was supposed to prove the match cannot
  // read the process table right now. "Could not verify" and "verified, no problem" have to be
  // different answers here, because the one thing this release exists to prevent is treating the
  // first as the second and signalling anyway.
  //
  // No real process is used: the run needs a process that is alive, killable and unreadable in
  // `/proc` all at once, and nothing on this machine is that. What is under test is precisely the
  // verdict the release reaches from an answer it cannot get.
  const delivered = []
  const unanswerable = await releaseProcessTree({
    rootPid: 4747, rootIdentity: "1000", graceMs: 40, forceMs: 40, pollMs: 5, wait: sleep,
    identify: () => null, // the recorded process is there; what it is cannot be read
    discover: () => [{ pid: 4747, group: 4747, identity: "1000" }],
    signal: (target, name) => {
      if (name !== 0) { delivered.push(target); return undefined }
      return undefined // alive, as far as the number is concerned
    },
  })
  assert.deepEqual(delivered, [], "nothing destructive is aimed at a process this release cannot point at")
  assert.deepEqual(unanswerable.tree.unconfirmed, [{ pid: 4747, code: "IDENTITY_UNKNOWN" }],
    "the member is reported as unverified, under the reason it is unverified for")
  assert.deepEqual(unanswerable.tree.survivors, [], "and not as a survivor — that would claim a live process we saw")
  assert.equal(unanswerable.released, false, JSON.stringify(unanswerable))
  assert.deepEqual(unanswerable.tree.members.map((member) => member.check), ["unknown"],
    "the receipt says which of the four states the check landed in")

  // The exception the rule must still allow: `ESRCH` is the OS answering that the number is empty,
  // which is a fact about the recorded process whatever else is unreadable about it. An identity check
  // that refused to accept that would report an unfinished release over a tree that is demonstrably
  // gone, and the round-6 cases that prove exit this way would have to be softened to get green.
  const goneAnyway = await releaseProcessTree({
    rootPid: 4748, rootIdentity: "1000", graceMs: 40, forceMs: 40, pollMs: 5, wait: sleep,
    identify: () => null,
    discover: () => [{ pid: 4748, group: 4748, identity: "1000" }],
    signal: (target, name) => {
      if (name !== 0) delivered.push(target)
      throw Object.assign(new Error("no such process"), { code: "ESRCH" })
    },
  })
  assert.equal(goneAnyway.released, true, "an unreadable identity next to an `ESRCH` is a reclaimed process")
  assert.deepEqual(goneAnyway.tree.unconfirmed, [])
  assert.deepEqual(delivered, [], "and it was never signalled, either")

  // The veto is absolute, and the order it is applied in *is* the rule: a member whose identity cannot
  // be checked and whose probe answers `EACCES` is refused for the identity reason. Reaching for the
  // probe answer first turns "we could not identify it" into "it is ours to signal anyway", which is
  // the same mistake this round exists to close, one branch further down.
  const answeredOddly = []
  const refused = await releaseProcessTree({
    rootPid: 4750, rootIdentity: "1000", graceMs: 20, forceMs: 20, pollMs: 5, wait: sleep,
    identify: () => null,
    discover: () => [{ pid: 4750, group: 4750, identity: "1000" }],
    signal: (target, name) => {
      if (name !== 0) answeredOddly.push(target)
      throw Object.assign(new Error("the os will not say"), { code: "EACCES" })
    },
  })
  assert.deepEqual(answeredOddly, [], "an odd probe answer does not unlock a signal the identity vetoes")
  assert.deepEqual(refused.tree.unconfirmed, [{ pid: 4750, code: "IDENTITY_UNKNOWN" }],
    `and it is refused for the reason it is refused: ${JSON.stringify(refused.tree)}`)
  assert.equal(refused.released, false, JSON.stringify(refused))
})

test("E25: a member that has left the group neither proves it nor needs it", async () => {
  // The group number is only owed to this launch while a process the launch recorded is *in it now*.
  // Counterexample: the middle member of the tree called `setsid()` — the first observation saw it
  // under the launched group, the table now puts it in a group of its own, which whatever runs there
  // now shares. Recording the historical group and signalling it anyway reaches that stranger; and a
  // release that skipped the member because the group "already covered" it would leave the one
  // process this launch really still owns. So both halves: the group is never aimed at, and the
  // member is reclaimed by its own number.
  const first = [
    { pid: 4848, group: 4848, identity: "1000" },
    { pid: 4849, group: 4848, identity: "1000" },
  ]
  const later = [{ pid: 4849, group: 4849, identity: "1000" }] // the bridge died, the child left the group
  let observations = 0
  const delivered = []
  const dead = new Set()
  const report = await releaseProcessTree({
    rootPid: 4848, rootIdentity: "1000", graceMs: 100, forceMs: 100, pollMs: 5, wait: sleep,
    identify: () => "1000",
    discover: () => { observations += 1; return observations === 1 ? first : later },
    signal: (target, name) => {
      if (name !== 0) {
        delivered.push(target)
        if (target === 4849) dead.add(4849)
        return undefined
      }
      if (target === 4848 || dead.has(target)) throw Object.assign(new Error("no such process"), { code: "ESRCH" })
      return undefined
    },
  })
  assert.ok(observations > 1, "the case needs a second look at the table to be about the current one")
  assert.ok(!delivered.includes(-4848), JSON.stringify(delivered))
  assert.ok(delivered.includes(4849), "the member that left is still this launch's, and reached as itself")
  assert.equal(report.released, true, JSON.stringify(report))
  const left = report.tree.members.find((member) => member.pid === 4849)
  assert.equal(left.group, 4848, "the receipt keeps both facts apart instead of reporting one as the other")
  assert.equal(left.currentGroup, 4849)
})
