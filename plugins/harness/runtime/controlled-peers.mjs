/**
 * Controlled-peer allowlist — locked content, not locked location (spec 019).
 *
 * The controlled-test-peer route of `access-entry.mjs` may launch exactly two
 * fixture files. Before this module that decision was a path comparison
 * against constants pointing into the repository's test trees — production
 * code naming `tests/` locations, broken by every relocation of those trees.
 * The allowlist is now a set of **content digests**: a candidate file is
 * accepted when its sha256 equals a pinned entry, wherever the file sits, and
 * refused the moment its content differs. The path never decides anything.
 *
 * Each entry keeps a `file` label and, where it applies, a `harness` binding:
 *
 *   - `file` is a **diagnostic label only**. It is never resolved, never read
 *     and never compared — it names the peer in refusal details so an operator
 *     can tell which allowlisted content was (or was not) matched. It is
 *     deliberately a bare filename: the allowlist carries no path into any
 *     test tree (the boundary test `tests/src_boundary_no_tests_paths.test.mjs`
 *     pins that).
 *   - `harness` binds an entry to one brand when the peer is brand-specific
 *     (the orchestration peer only ever serves `pi`). An entry without the
 *     field serves any discovered brand, exactly as before.
 *
 * **Injection port (assembly side).** The assembly layer may replace this
 * table wholesale for the entry process it spawns by setting
 * `AGENTBOX_CONTROLLED_PEER_ALLOWLIST` to a JSON array of entries with the
 * same schema (`sha256` required; `file`/`harness` optional). An injected
 * table **takes precedence over the built-in one** — an empty array allows
 * nothing. The variable is read only in the controlled-test-peer mode, and an
 * entry is still a *file* descriptor: the schema has no command, no arguments
 * and no driver fields, so injection cannot turn this surface into an
 * execution channel beyond "launch this exact content with this entry's own
 * node". A variable that does not parse, or carries an invalid entry, is
 * fail-closed: it allows nothing, and the refusal names
 * `CONTROLLED_PEER_ALLOWLIST_INVALID` rather than silently falling back to the
 * built-in table — a broken declaration must not resurrect the defaults.
 */
import { createHash } from "node:crypto"
import { readFileSync, realpathSync } from "node:fs"

/**
 * The environment variable of the injection port. Empty string counts as
 * unset — shells and process supervisors export empty values freely, and an
 * empty value is a cleared declaration, not a broken one.
 */
export const CONTROLLED_PEER_ALLOWLIST_ENV = "AGENTBOX_CONTROLLED_PEER_ALLOWLIST"

/**
 * The built-in allowlist, pinned as build-time constants. When a fixture
 * changes, recompute the digest (see the package README's "controlled-peer
 * allowlist" section) and update the entry here — the controlled-peer tests
 * fail until the table matches the fixtures again.
 *
 * The two pinned contents are the plugin's own access-test harness (serves any
 * discovered brand) and the root orchestration bidirectional peer (bound to
 * `pi`). Their digests are re-proven against the committed files by
 * `tests/controlled_peer_allowlist.test.mjs`; this comment deliberately carries
 * no path into any test tree — that is the boundary the same test pins.
 */
export const BUILTIN_CONTROLLED_PEERS = Object.freeze([
  Object.freeze({
    sha256: "63b4e9f1aed81794eb1715b2ee974f553f7787f4ed7d555dc27980a7c10dd060",
    file: "controlled_harness.mjs",
  }),
  Object.freeze({
    sha256: "45ebf370de499df9cc371875435f7b4269f5d8c864cde1b3b3fa9bfd08a70841",
    file: "bidirectional_acp_peer.mjs",
    harness: "pi",
  }),
])

const SHA256_PATTERN = /^[0-9a-f]{64}$/

/**
 * Read the effective allowlist for this entry process.
 *
 * Returns `{ peers, injected: false }` for the built-in table, or
 * `{ peers, injected: true }` for a valid injection. An invalid injection
 * returns `{ peers: [], injected: true, error }` — fail-closed, with the
 * reason for the refusal detail. `peers` is always a plain array of plain
 * entries, so the caller never branches on which table it got.
 */
export function resolveControlledPeerAllowlist(environment = process.env) {
  const raw = environment[CONTROLLED_PEER_ALLOWLIST_ENV]
  if (raw === undefined || raw === "") {
    return { peers: BUILTIN_CONTROLLED_PEERS, injected: false }
  }
  let parsed
  try {
    parsed = JSON.parse(raw)
  } catch (error) {
    return { peers: [], injected: true, error: `not JSON: ${error?.message ?? error}` }
  }
  if (!Array.isArray(parsed)) {
    return { peers: [], injected: true, error: "not an array" }
  }
  const peers = []
  for (const entry of parsed) {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
      return { peers: [], injected: true, error: "entry is not an object" }
    }
    const unknown = Object.keys(entry).filter((key) => key !== "sha256" && key !== "file" && key !== "harness")
    if (unknown.length) {
      return { peers: [], injected: true, error: `entry field unknown: ${unknown.join(", ")}` }
    }
    if (typeof entry.sha256 !== "string" || !SHA256_PATTERN.test(entry.sha256.toLowerCase())) {
      return { peers: [], injected: true, error: "entry sha256 is not a hex sha256 digest" }
    }
    // `file` is diagnostic output only — bounded so it cannot smuggle control
    // characters or unbounded text into a refusal detail.
    if (entry.file !== undefined
        && (typeof entry.file !== "string" || entry.file.length > 256 || /[\x00-\x1f\x7f]/.test(entry.file))) {
      return { peers: [], injected: true, error: "entry file label is not a bounded plain string" }
    }
    if (entry.harness !== undefined
        && (typeof entry.harness !== "string" || !entry.harness || entry.harness.length > 64)) {
      return { peers: [], injected: true, error: "entry harness binding is not a brand name" }
    }
    peers.push({
      sha256: entry.sha256.toLowerCase(),
      ...(entry.file !== undefined ? { file: entry.file } : {}),
      ...(entry.harness !== undefined ? { harness: entry.harness } : {}),
    })
  }
  return { peers, injected: true }
}

/**
 * Match one requested peer file against the allowlist by content.
 *
 * `requestedPath` must be the single launch argument (the caller has already
 * enforced exactly-one-string-arg). Returns the matched entry plus the
 * realpath the caller should launch, or `null` when nothing matches. Reading
 * failures (absent file, unreadable path) are mismatches, not errors: an
 * absent file cannot present its content.
 */
export function matchControlledPeer(peers, harness, requestedPath) {
  let requested
  let digest
  try {
    requested = realpathSync(requestedPath)
    digest = createHash("sha256").update(readFileSync(requested)).digest("hex")
  } catch {
    return null
  }
  const peer = peers.find((candidate) => candidate.sha256 === digest
    && (candidate.harness === undefined || candidate.harness === harness)) ?? null
  return peer === null ? null : { peer, requested, digest }
}
