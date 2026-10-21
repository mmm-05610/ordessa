/**
 * The ACP transport handle — what "a connection" means in this plugin.
 *
 * `openAcpConnection()` starts the Harness process and wires its three pipes. It sends **no ACP
 * frame**: `initialize`, `authenticate` and `session/new` belong to whoever owns the conversation,
 * and the entry that hands out this handle is a relay, not a client. The process is reached through
 * the reused bridge's `AcpClient` in its transport-only mode (see
 * `third_party/harness_remote/PATCHES.md` §8), so framing, line buffering, stderr reporting, exit
 * reporting and the restart-residue fixes stay in one implementation rather than being rewritten
 * here.
 *
 * What this module owns is exactly the four things a handle needs and nothing else: where the bytes
 * go, what state the connection is in, and how to stop it.
 */
import { randomUUID } from "node:crypto"
import { existsSync, readdirSync, readFileSync } from "node:fs"

/** Names the wire this handle speaks, so a caller can tell it from any other channel. */
export const ACP_TRANSPORT_ID = "acp-stdio-jsonrpc/1"

/**
 * The release policy, stated once and measured in the OS rather than in intent.
 *
 * `close()` claims a release only after the process is gone. A signal that was merely delivered is
 * not a death: a Harness that traps `SIGTERM` keeps running and keeps its pipes, and the caller that
 * was told `released: true` has now lost the only handle that could have stopped it. So: graceful
 * window, then `SIGKILL` (which a normal process cannot trap), then a deadline after which the
 * honest answer is `released: false` with the process identity preserved for a retry.
 */
export const RELEASE_GRACE_MS = 2_000
export const RELEASE_FORCE_MS = 2_000
export const RELEASE_POLL_MS = 20

/**
 * Whether a launch on this platform can be given a process group of its own — that is, whether
 * "everything this launch started" is a set the OS will signal for us in one call.
 *
 * One constant, because the launch and the release have to agree about it: `detached` at spawn and
 * `claim: "tree"` at close describe the same fact from opposite ends, and a release that claimed tree
 * ownership over a launch that never got a group would be promising something nobody set up.
 */
export const PROCESS_GROUP_OWNERSHIP = process.platform !== "win32"

/**
 * Ask the OS about one pid, and keep the three answers distinct.
 *
 * `ESRCH` is the only code that proves a process is not there any more. `EPERM` proves the opposite
 * — something is running under that number and we are merely not allowed to reach it. Anything else
 * (`EACCES` from a security module, `EINVAL`, an unexpected `ENOSPC`) says nothing about whether the
 * process exited, so it is reported as `unconfirmed` rather than folded into "gone": a release that
 * counted an odd error as a death would hand the caller `released: true` over a Harness it can no
 * longer name or stop.
 */
function probeProcess(pid, signal) {
  try {
    signal(pid, 0)
    return { state: "alive", code: null }
  } catch (error) {
    const code = error?.code ?? "UNKNOWN"
    if (code === "ESRCH") return { state: "gone", code }
    if (code === "EPERM") return { state: "alive", code }
    return { state: "unconfirmed", code }
  }
}

/**
 * The processes launched for one connection, as the OS currently sees them.
 *
 * Ownership is claimed at spawn time by putting the launch in a process group of its own, and a
 * group is exactly the thing the OS will signal for us: every descendant that stayed in it is reached
 * by `kill(-groupPid, …)` whether or not we ever saw it. Two identities are therefore collected:
 * everything whose group is the launched root (including orphans whose parent already exited — the
 * group number survives as long as any member does), and everything reachable from the root through
 * the parent link, which catches a child that moved itself out of the group. Nothing outside those
 * two is ever signalled, which is what keeps a sibling process that happens to run the same command
 * in the same directory alive.
 *
 * The two ways of finding a member are used for different things and must not be used to skip each
 * other. Group membership answers "may the OS be signalled for this one in bulk"; the parent link
 * answers "who else did this process start", and it has to be followed *through* a member rather than
 * stopping at it — a child that stayed in the group and a grandchild that left it are found by two
 * different rules, so a member filed by the group rule is precisely a node the parent-link walk still
 * owes an expansion to. Each member carries the identity the OS records for it alongside the number.
 */
export function discoverProcessTree(rootPid, readProc = readLinuxProc) {
  const table = readProc()
  if (table === null) return null
  const member = (pid) => ({ pid, group: table.groups.get(pid) ?? null, identity: table.identities.get(pid) ?? null })
  const members = new Map([[rootPid, member(rootPid)]])
  for (const pid of table.groups.keys()) if (table.groups.get(pid) === rootPid) members.set(pid, member(pid))
  const expanded = new Set()
  const queue = [...members.keys()]
  while (queue.length) {
    const pid = queue.pop()
    // Deduplicated against what this walk has already *expanded*, never against what it has filed as
    // a member: the two facts coincide only by accident.
    if (expanded.has(pid)) continue
    expanded.add(pid)
    for (const child of table.children.get(pid) ?? []) {
      if (child === process.pid || child <= 1) continue
      if (!members.has(child)) members.set(child, member(child))
      queue.push(child)
    }
  }
  members.delete(process.pid)
  return [...members.values()]
}

function readLinuxProc() {
  if (!existsSync("/proc")) return null
  const groups = new Map()
  const children = new Map()
  const identities = new Map()
  for (const entry of readdirSync("/proc")) {
    if (!/^\d+$/.test(entry)) continue
    const pid = Number(entry)
    let stat
    try {
      stat = readFileSync(`/proc/${pid}/stat`, "utf8")
    } catch {
      continue // it exited while we were looking, or it is not ours to read
    }
    // The second field is the command name: it is parenthesised and may contain spaces and closing
    // parentheses, so the fixed fields are counted back from the last `)` rather than split forward.
    const fields = stat.slice(stat.lastIndexOf(")") + 1).trim().split(/\s+/)
    const parent = Number(fields[1])
    const group = Number(fields[2])
    if (!Number.isInteger(parent) || !Number.isInteger(group)) continue
    groups.set(pid, group)
    // Field 22 of the whole record is the process start time, which is what distinguishes this
    // process from whatever else occupies the same number after it exits.
    identities.set(pid, fields[19] ?? null)
    if (!children.has(parent)) children.set(parent, [])
    children.get(parent).push(pid)
  }
  return { groups, children, identities }
}

/**
 * The identity the OS currently records for one pid, or `null` when it records nothing readable.
 *
 * A pid is a number that gets handed out again, so it is not an identity: by the time a release
 * reaches for a member it saw earlier, the number can belong to a process this launch never started,
 * and — same user, same privileges — a signal aimed at it will succeed. The start time is the thing
 * that cannot be the same for two different processes using one number.
 *
 * `null` is the absence of an answer, never an answer of its own: it means the process is no longer
 * there, or is not ours to read, or this platform has no such record (see {@link
 * PROCESS_IDENTITY_AVAILABLE}). A release may treat it as "cannot confirm" and hold back; a release
 * that read it as "no contradiction, go ahead" would be turning its own blind spot into permission.
 */
export function readProcessIdentity(pid, readProc = readLinuxProcIdentity) {
  if (pid === null || pid === undefined) return null
  return readProc(pid)
}

/** Whether this platform keeps a per-process identity a release can record and later re-read. */
const PROCESS_IDENTITY_AVAILABLE = existsSync("/proc")

/** The start time of one process, or `null` when there is nothing to compare — see {@link readProcessIdentity}. */
function readLinuxProcIdentity(pid) {
  let stat
  try {
    stat = readFileSync(`/proc/${pid}/stat`, "utf8")
  } catch {
    return null // gone, or not ours to read
  }
  const fields = stat.slice(stat.lastIndexOf(")") + 1).trim().split(/\s+/)
  return fields[19] ?? null
}

/**
 * Signal the launched process tree until the OS answers `ESRCH` for every member of it.
 *
 * Injectable on purpose twice over. `released: false` needs a process that survives both signals and
 * no ordinary process does, and an `unconfirmed` probe needs an OS that returns a code it should not;
 * a test that reached either branch with a real process would be claiming something it cannot build.
 * `signal` is `process.kill`, `discover` is the `/proc` walk and `identify` one process's start time.
 *
 * `claim` states how much this release is entitled to account for, and it is derived from the same
 * fact as the launch's `detached`: `"tree"` where the launch owns a group, `"root-only"` where it does
 * not and only the spawned process can be answered for. Under a tree claim an unreadable process table
 * makes the release `false` — the root vanishing proves the root vanished, and nothing about the
 * children it started — rather than quietly becoming a root-only claim that reads as a full one.
 *
 * Nothing destructive is aimed at a process this release cannot point at, and the aiming is decided by
 * an identity *check* with three possible answers rather than a yes/no: a check that came back
 * unreadable is not a check that came back clean, and reading it as one is how a release that never
 * aims at strangers ends up aiming at strangers anyway. So `"matched"` alone licenses a signal — and a
 * group, being only a number, is licensed solely by a member that matches right now *and* is in that
 * group in the current table, never by the group number this release happened to record earlier.
 *
 * `identityAvailable` is what separates an unreadable recording from a platform that keeps no such
 * record at all: the first stops the release and reports it, the second narrows it to its claim.
 */
export async function releaseProcessTree({
  rootPid, rootIdentity = null, claim = PROCESS_GROUP_OWNERSHIP ? "tree" : "root-only",
  identityAvailable = PROCESS_IDENTITY_AVAILABLE,
  graceMs = RELEASE_GRACE_MS, forceMs = RELEASE_FORCE_MS, pollMs = RELEASE_POLL_MS,
  discover = (pid) => discoverProcessTree(pid), signal = process.kill,
  identify = (pid) => readProcessIdentity(pid),
  wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
} = {}) {
  const empty = {
    available: false, scope: claim, reason: null, groupPid: rootPid ?? null,
    members: [], survivors: [], unconfirmed: [], identityChanged: [],
  }
  if (rootPid === null || rootPid === undefined) {
    // Nothing was ever launched, so there is nothing this handle can leave running.
    return { released: true, processId: null, signalUsed: null, tree: empty }
  }

  /** pid -> what this release first saw there: the group and identity it is claiming to reclaim. */
  const seen = new Map()
  /** pid -> what the OS says right now, refreshed by every observation and the only basis for aiming. */
  const current = new Map()
  let available = true
  const observe = () => {
    const found = discover(rootPid)
    current.clear()
    if (found === null) {
      // No process table: the root is all that can be accounted for, and nothing about it is current.
      available = false
      if (!seen.has(rootPid)) seen.set(rootPid, { group: null, identity: rootIdentity })
      return
    }
    for (const member of found) {
      if (member.pid === process.pid) continue
      current.set(member.pid, { group: member.group ?? null, identity: member.identity ?? null })
      if (seen.has(member.pid)) continue
      // The claimed identity is recorded once and then held. Re-reading it from a later observation
      // would let a process that arrived after the death describe itself as the one that was always there.
      seen.set(member.pid, {
        group: member.group ?? null,
        identity: member.pid === rootPid ? (rootIdentity ?? member.identity ?? null) : (member.identity ?? null),
      })
    }
  }

  /**
   * What the OS says, right now, about the process claimed at this number.
   *
   * `"matched"` is the only state that licenses a signal. `"changed"` is positive evidence the claimed
   * process exited — a pid is not handed out again while its holder lives — and equally evidence that
   * whatever holds the number now is somebody else's. `"unknown"` is the verification failing: a
   * recording that cannot be checked against the live table. `"unavailable"` is a platform that keeps
   * no such record at all, which is a different fact and says why the release narrows to its claim
   * there rather than stopping dead.
   */
  const identityState = (pid) => {
    const recorded = seen.get(pid)?.identity
    if (recorded === null || recorded === undefined) return identityAvailable ? "unknown" : "unavailable"
    const now = identify(pid)
    if (now === null || now === undefined) return "unknown"
    return String(recorded) === String(now) ? "matched" : "changed"
  }
  const inGroupNow = (pid) => current.get(pid)?.group === rootPid

  /** One member's verdict: what the OS answered, and what the identity check licenses claiming. */
  const classify = (pid) => {
    let probe = probeProcess(pid, signal)
    const check = identityState(pid)
    // `ESRCH` answers for the process itself, whoever holds the number now: a gone process has no
    // claim left to confuse with another one's.
    if (probe.state === "gone") return { pid, ...probe, check, verdict: "gone" }
    // The identity veto comes before anything the probe says about the member's *liveness*: an answer
    // of "alive" or "I cannot say" describes whatever occupies the number, and a number that is
    // demonstrably somebody else's — or that this release cannot point at at all — is never aimed at.
    // Leaving this ordering to be rediscovered per call site is how a veto becomes a suggestion.
    if (check === "changed") return { pid, ...probe, check, verdict: "replaced" }
    if (check === "unknown") {
      // The number can answer for itself and not be readable in the same instant — a process dies in
      // between. Asking it twice before concluding keeps that race an honest `gone` rather than
      // turning it into a release nobody confirmed.
      probe = probeProcess(pid, signal)
      if (probe.state === "gone") return { pid, ...probe, check, verdict: "gone" }
      return { pid, ...probe, check, verdict: "unverified" }
    }
    // An odd probe answer is not a death, and the member is still attempted: the conservative
    // direction is to keep trying and to refuse the claim, not to leave it alone and call it clean.
    if (probe.state === "unconfirmed") return { pid, ...probe, check, verdict: "unconfirmed" }
    return { pid, ...probe, check, verdict: "survivor" }
  }
  /** Members the release has no further action for, so a sweep stops polling on them. */
  const settled = (entry) => entry.verdict === "gone" || entry.verdict === "replaced" || entry.verdict === "unverified"
  const outstanding = () => [...seen.keys()].filter((pid) => !settled(classify(pid)))
  const deliver = (target, name) => { try { signal(target, name) } catch { /* the probe reports the outcome */ } }

  /** One round of signals: the group as a whole, then individually what the group does not cover. */
  const sweep = (name) => {
    observe()
    // A group is a number too, so it needs a witness that is answering to it *now*: the current group
    // from the current table, on a member whose identity matches right now. A historically-in-group
    // member that has since led a session of its own proves nothing about the group and is not in it.
    const groupSignal = available
      && [...seen.keys()].some((pid) => inGroupNow(pid) && identityState(pid) === "matched")
    if (groupSignal) deliver(-rootPid, name)
    for (const pid of seen.keys()) {
      // The group was just aimed at on the evidence of this member being in it now, so the group
      // covers it; a member that left the group is nobody's business but this release's, one pid at
      // a time.
      if (groupSignal && inGroupNow(pid)) continue
      if (settled(classify(pid))) continue
      deliver(pid, name)
    }
  }
  const within = async (name, budgetMs) => {
    sweep(name)
    const startedAt = Date.now()
    for (;;) {
      if (!outstanding().length) return true
      if (Date.now() - startedAt > budgetMs) return false
      await wait(pollMs)
      sweep(name)
    }
  }

  observe()
  let signalUsed = null
  if (outstanding().length) {
    if (await within("SIGTERM", graceMs)) signalUsed = "SIGTERM"
    else signalUsed = "SIGKILL", await within("SIGKILL", forceMs)
  }

  observe()
  const outcomes = [...seen.keys()].map((pid) => ({ ...classify(pid), group: seen.get(pid).group }))
  const survivors = outcomes.filter((entry) => entry.verdict === "survivor")
  const unconfirmed = outcomes.filter((entry) => entry.verdict === "unconfirmed" || entry.verdict === "unverified")
  // The two facts a member can carry at once: the OS no longer answers for the number, and the
  // process that last answered for it was not the one recorded. `identityChanged` is the second, read
  // straight off the check rather than off a verdict, so a number that is both gone and demonstrably
  // somebody else's is still named — that combination is the ordinary end of a recycled pid.
  const identityChanged = outcomes.filter((entry) => entry.check === "changed").map(({ pid }) => pid)
  // Every member has to be positively answered `ESRCH`: a survivor is a failure, so is a probe that
  // returned a code which tells us nothing, and so is a member whose identity could not be checked.
  const unaccounted = available === false && claim === "tree"
  return {
    released: !unaccounted && survivors.length === 0 && unconfirmed.length === 0,
    processId: rootPid,
    signalUsed,
    tree: {
      available,
      // What this release set out to account for, so a `true` can never be read as more than it is:
      // `"root-only"` answers for one process, and `reason` names the fact that defeated a tree claim.
      scope: claim,
      reason: unaccounted ? "PROCESS_TABLE_UNAVAILABLE" : null,
      groupPid: rootPid,
      members: outcomes.map(({ pid, group, state, code, check }) => ({
        // `group` is the number this release claimed the member under, `currentGroup` where the table
        // puts it now; a member whose two differ has left the launch, and `check` says whether the
        // process at that number is still demonstrably the one recorded.
        pid, group, currentGroup: current.get(pid)?.group ?? null,
        state, code, check, identity: seen.get(pid).identity,
      })),
      survivors: survivors.map(({ pid }) => pid),
      unconfirmed: unconfirmed.map(({ pid, verdict, code }) => ({
        pid, code: verdict === "unconfirmed" ? code : "IDENTITY_UNKNOWN",
      })),
      identityChanged,
    },
  }
}

export async function openAcpConnection({
  harness, launch, directory = null, spawnProcess,
  redact = (value, maximum) => String(value).slice(0, maximum),
} = {}) {
  if (!launch?.command) throw new Error("ADAPTER_LAUNCH_REQUIRED")
  const { AcpClient } = await import("../transport/vendor/harness_remote/bridge/src/acp-client.js")
  const client = new AcpClient({
    command: launch.command,
    args: Array.isArray(launch.args) ? launch.args : [],
    cwd: directory,
    spawnProcess,
    transportOnly: true,
  })

  const frameListeners = []
  const endListeners = []
  const stderrListeners = []
  const malformedListeners = []
  let ended = null
  let framesFromAgent = 0
  let framesToAgent = 0
  const connectionId = randomUUID()
  // The pid this handle is responsible for, recorded for the OS rather than read back from the
  // client: the reused client drops its own child reference the moment the process exits, so after a
  // crash `processId` is null and a release could not be checked at all. This stays set until the
  // process is confirmed gone, including across a release that could not be confirmed.
  let ownedPid = null

  client.on("frame", (message, line) => {
    framesFromAgent += 1
    for (const listener of frameListeners) listener(message, line)
  })
  client.on("stderr", (line) => {
    // Redaction is the one thing this relay does to a peer's output, and only to the diagnostic
    // stream: a credential value must not reach the host because it happened to be printed. ACP
    // frames are never touched — see `frame` above.
    for (const listener of stderrListeners) listener(redact(line, 2000))
  })
  client.on("protocol-error", (error) => {
    for (const listener of malformedListeners) listener(redact(error?.message ?? error, 500))
  })
  client.on("exit", (error) => {
    if (ended) return
    ended = { reason: "adapter_exit", message: redact(error?.message ?? error, 500), at: new Date().toISOString() }
    for (const listener of endListeners) listener(ended)
  })

  // Transport-only: this resolves once the process is up and the pipes are wired. A spawn failure
  // surfaces as the `exit` event (`ENOENT` etc. in its message) rather than a rejected start, so
  // the caller sees one honest end-of-transport report either way.
  await client.start()
  ownedPid = client.processID ?? null
  // The identity is read at the one moment the number is certainly ours. Recorded later — at the
  // release — it could only be the impostor's own account of itself, which is exactly the check that
  // has to be able to fail.
  const ownedIdentity = ownedPid === null ? null : readProcessIdentity(ownedPid)

  return {
    connectionId,
    harness,
    transport: ACP_TRANSPORT_ID,
    launch,

    get processId() {
      return client.processID ?? ownedPid ?? null
    },

    status() {
      return {
        connectionId,
        harness,
        transport: ACP_TRANSPORT_ID,
        connected: !ended && Boolean(client.processID),
        state: ended ? "ended" : client.processID ? "running" : "stopped",
        processId: client.processID ?? ownedPid ?? null,
        framesToAgent,
        framesFromAgent,
        ended,
      }
    },

    /** Forward one frame the caller composed, as written. */
    writeLine(line) {
      if (ended) throw new Error("ACP_CHANNEL_DEAD")
      client.writeLine(line)
      framesToAgent += 1
    },

    /** Forward one frame object; `writeLine` is what a byte-transparent relay uses. */
    write(message) {
      if (ended) throw new Error("ACP_CHANNEL_DEAD")
      client.write(message)
      framesToAgent += 1
    },

    onFrame: (listener) => frameListeners.push(listener),
    onEnd: (listener) => endListeners.push(listener),
    onStderr: (listener) => stderrListeners.push(listener),
    onMalformed: (listener) => malformedListeners.push(listener),

    /**
     * Release what this handle owns: the launched process group, everything still in it, and the pipes.
     *
     * Two things make this async rather than a one-line signal. First, the end is reported to
     * listeners here rather than left to the process `exit`, because the caller's own close is a
     * different fact from a crash and the difference must survive: `reason` says who ended the
     * transport. A later `exit` is suppressed by the `ended` guard in the listener above, so exactly
     * one `transport_end` is reported per connection either way. Second, `released` is a claim about
     * the OS, not about intent: a delivered `SIGTERM` is not a death, and the bridge exiting is not
     * either — a `npx`-style bridge normally has a real Agent behind it that keeps running when its
     * parent is killed. `policy` can shorten the grace/force windows.
     */
    async close(policy = {}) {
      const rootPid = ownedPid
      if (!ended) {
        ended = { reason: "closed_by_caller", at: new Date().toISOString() }
        for (const listener of endListeners) listener(ended)
      }
      const release = await releaseProcessTree({ rootPid, rootIdentity: ownedIdentity, ...policy })
      if (!release.released) {
        // The pipes, the child reference and the process identity all stay: the caller still holds
        // the only handle that can keep trying, `status()` still reports a live pid, and the report
        // says which members the OS still answers for.
        return { connectionId, ...release }
      }
      // `client.close()` drops the child reference and signals the root only. It is still the right
      // way to hand the pipes back, but it can no longer be the release: a bridge that exits first
      // leaves its own children running in the group this entry owns, and the tree sweep above is
      // what accounted for them.
      if (client.processID !== undefined) client.close()
      ownedPid = null
      return { connectionId, ...release }
    },
  }
}
