#!/usr/bin/env node
/**
 * Build the Hermes runtime artifact: the Hermes Agent distribution and exactly
 * the installed Python dependency closure it needs, with no network access and
 * no pip at build time.
 *
 * Why a builder exists at all: Hermes is a Python distribution (`hermes-agent`)
 * whose entry point is `python3 -m hermes_cli.main acp`, so the artifact is a
 * *site-packages subtree*, not one file. It is built from the distributions that
 * are already installed on this machine, is verified by a tree digest inside the
 * Worker, and is mounted read-only under `/runtime/artifacts/hermes-runtime`, so
 * what matters is that the tree is exact, reproducible, and honest about every
 * package it contains and every package it excludes.
 *
 * Rules, in the order they are enforced:
 *
 *   1. The closure starts at `hermes-agent==0.19.0` and follows its own
 *      `Requires-Dist` metadata (recursively, including requirement extras such
 *      as `httpx[socks]` and `uvicorn[standard]`). Markers are evaluated for
 *      this platform (linux/posix/cpython 3.12/x86_64), which drops the win32
 *      requirements (`tzdata`, `pywinpty`, `concurrent-log-handler`).
 *   2. The entry point's own extra (`acp`) is the one extra this artifact
 *      provides, because `acp_adapter/entry.py` imports `acp` unconditionally
 *      and only `agent-client-protocol` (declared as `extra == "acp"`) provides
 *      it. Every other extra is excluded, and the exclusion is enforced: a
 *      distribution that Hermes declares *only* under an extra this artifact
 *      does not provide may not appear in the tree.
 *   3. Sources are read-only. The primary root is the site directory that holds
 *      Hermes itself, and it is *declared*, never guessed: `--source` or the
 *      `ORDESSA_HERMES_SOURCE` environment variable, and an unset variable is a
 *      refusal rather than a fallback to some other machine's path or to a
 *      `hermes` binary on `PATH`. A requirement the primary root cannot satisfy
 *      falls back to the declared platform root (`/usr/lib/python3/dist-packages`)
 *      and the fallback is recorded per package. Nothing here writes to a source.
 *   4. Every selected distribution must be installed, must satisfy the
 *      specifier that pulled it in (`==` must match exactly, ranges record the
 *      version actually resolved), and its files come from its own installed
 *      metadata: `RECORD` for wheel installs, `top_level.txt` for the Debian
 *      `egg-info` installs in the platform root.
 *   5. Nothing unrelated may ride along: the closure of an unrelated installed
 *      distribution is computed from the same roots and refused if it appears,
 *      win32-only distributions are refused by name, and cache files never
 *      enter the tree.
 *   6. The result may contain no symlink and no special file at all - a tree
 *      that does is refused, not repaired. This is also the rule the Worker's
 *      digest enforces inside WSL, so a violation is caught here first with a
 *      better message.
 *   7. The tree is verified through the reviewed Python digest implementation,
 *      made read-only, and published atomically. A failed build leaves the
 *      output path untouched.
 *
 * Output layout: `<output>/site-packages/...` plus the plugin's artifact overlay
 * (`sitecustomize.py` + `agentbox_hermes_bootstrap.py`, see `deploy/hermes/`)
 * and an owner marker, so the adapter entry is
 * `<output>/site-packages/hermes_cli/main.py` and Python resolves the whole
 * closure from `PYTHONPATH=<output>/site-packages`. The manifest (versions,
 * roots, counts, digests) is written next to the output as
 * `<output>.manifest.json` - deliberately outside the tree, so the record does
 * not change what the digest covers. Nothing is written into the repository.
 *
 * usage: build-hermes-runtime-artifact.mjs --output ABSOLUTE_DIR [--source DIR]
 *                                        [--fallback-source DIR] [--replace] [--json]
 *
 * With no `--source`, `ORDESSA_HERMES_SOURCE` must name the site directory;
 * this build carries no machine-local default source.
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
//: The environment variable that declares the site directory holding Hermes.
//: There is deliberately no default value here: this builder must not carry one
//: developer's home directory, and it must not go looking for a `hermes` binary
//: on `PATH` either - an unverified global binary is not an installed-package
//: directory. Unset is a typed refusal, not a guess.
export const SOURCE_ENVIRONMENT_VARIABLE = "ORDESSA_HERMES_SOURCE"
//: Declared platform root, used only for requirements the primary root cannot
//: satisfy. Hermes pins `rich` (needs `markdown-it-py`), `jinja2` (needs
//: `MarkupSafe`), `openai` (hard-imports `distro`) and `croniter` (needs `pytz`),
//: none of which the primary per-user directory provides. This is a platform
//: path, not a machine-local one, and it stays overridable via
//: `--fallback-source`.
export const DEFAULT_FALLBACK_SOURCES = ["/usr/lib/python3/dist-packages"]
const OVERLAY_DIRECTORY = path.join(REPO, "deploy", "hermes")

export const MARKER_NAME = ".agentbox-hermes-runtime-artifact"
export const MARKER_CONTENT = "agentbox-hermes-runtime-artifact-r1\n"
export const ENTRY_DISTRIBUTION = "hermes-agent"
export const ENTRY_VERSION = "0.19.0"
//: The one extra this artifact provides. Evidence is asserted below: `acp` must
//: be a declared extra of the entry distribution, and the distribution it pulls
//: in must ship the module the entry point imports.
export const ENTRY_EXTRAS = ["acp"]
export const ENTRY_MODULE = "hermes_cli.main"
export const ENTRY_RELATIVE = "hermes_cli/main.py"
//: Files the plugin owns and copies into the artifact's `site-packages`. They
//: are not part of any installed distribution: `sitecustomize.py` is imported by
//: CPython at interpreter start and `agentbox_hermes_bootstrap.py` is the
//: deployment bootstrap it delegates to. Both are listed in the manifest with
//: their digests.
export const OVERLAY_FILES = [
  ["bootstrap.py", "agentbox_hermes_bootstrap.py"],
  ["sitecustomize.py", "sitecustomize.py"],
]
//: An unrelated installed distribution whose own closure must not appear here.
export const UNRELATED_REFERENCE = "flask"
//: Values the marker evaluator uses: this artifact is built for the same linux
//: cpython 3.12 ABI as the system interpreter that runs it in the sandbox.
export const MARKER_ENVIRONMENT = {
  implementation_name: "cpython",
  implementation_version: "3.12.3",
  os_name: "posix",
  platform_machine: "x86_64",
  platform_release: "6.18.33.2-microsoft-standard-WSL2",
  platform_system: "Linux",
  platform_version: "#1 SMP PREEMPT_DYNAMIC",
  platform_python_implementation: "CPython",
  python_full_version: "3.12.3",
  python_version: "3.12",
  sys_platform: "linux",
}
//: Entries (directories included) and bytes the runtime artifact contract allows.
export const MAX_ENTRIES = 32768
export const MAX_BYTES = 1024 * 1024 * 1024

/**
 * Installations that do not satisfy the specifier that pulled them in.
 *
 * A declared deviation is not a relaxed check: every other requirement in the
 * closure still has to be satisfied exactly, the deviation is reported in the
 * manifest and in the build output, and adding one requires an explicit edit
 * here plus the reason a reviewer reads.
 *
 * `root: null` means the primary source this build was told to use
 * (`--source` / `ORDESSA_HERMES_SOURCE`), never "any root": the deviation
 * applies to the site directory the operator declared, and nowhere else.
 */
export const DECLARED_PIN_DEVIATIONS = [
  {
    project: "rich",
    declared: "==14.3.3",
    installed: "15.0.0",
    root: null,
    reason:
      "hermes-agent 0.19.0 declares rich==14.3.3; the declared source directory " +
      "installs rich 15.0.0, and no declared fallback root has 14.3.3. The " +
      "artifact carries what is installed and the production chain gate exercises Hermes on it.",
  },
]

function declaredDeviation(project, specifier, distribution, primaryRoot = undefined) {
  return DECLARED_PIN_DEVIATIONS.find((item) => {
    if (canonicalize(item.project) !== canonicalize(project)) return false
    if (item.declared !== specifier || item.installed !== distribution.version) return false
    const expected = item.root ?? primaryRoot
    // No declared root means no match: a deviation never applies to a root this
    // build was not told about.
    if (expected === undefined) return false
    return path.resolve(expected) === path.resolve(distribution.root)
  }) ?? null
}

class BuildError extends Error {
  constructor(code, message) {
    super(`${code}: ${message}`)
    this.code = code
  }
}

// -- PEP 440 subset (versions and specifiers) --------------------------------

/** Parse a version into a comparable release tuple plus ordering flags.
 *
 * Only the subset Python packaging actually emits in this closure is modelled:
 * release segments, optional pre/post/dev suffixes and an ignored local part.
 * Anything else is a typed refusal rather than a guess.
 */
export function parseVersion(text) {
  const value = String(text ?? "").trim()
  const match = /^v?(\d+(?:\.\d+)*)((?:[-_.]?(?:a|b|c|rc|alpha|beta|pre|preview|post|rev|r|dev)\d*)*)(?:\+[A-Za-z0-9._-]+)?$/i.exec(value)
  if (!match) throw new BuildError("HERMES_VERSION_UNSUPPORTED", `cannot order version ${JSON.stringify(value)}`)
  const release = match[1].split(".").map((part) => Number.parseInt(part, 10))
  let pre = null
  let post = 0
  let dev = null
  const suffix = match[2] ?? ""
  for (const token of suffix.match(/[-_.]?[A-Za-z]+\d*/g) ?? []) {
    const cleaned = token.replace(/^[-_.]/, "").toLowerCase()
    const kind = cleaned.replace(/\d+$/, "")
    const number = Number.parseInt(cleaned.replace(/^[a-z]+/, "") || "0", 10)
    if (["a", "alpha", "b", "beta", "c", "rc", "pre", "preview"].includes(kind)) pre = number
    else if (["post", "rev", "r"].includes(kind)) post = number
    else if (kind === "dev") dev = number
    else throw new BuildError("HERMES_VERSION_UNSUPPORTED", `cannot order version ${JSON.stringify(value)}`)
  }
  return { release, pre, post, dev, raw: value }
}

function compareRelease(left, right) {
  const length = Math.max(left.length, right.length)
  for (let index = 0; index < length; index += 1) {
    const a = left[index] ?? 0
    const b = right[index] ?? 0
    if (a !== b) return a < b ? -1 : 1
  }
  return 0
}

/** Total order over the parsed versions, following PEP 440's ordering rules. */
export function compareVersions(left, right) {
  const a = parseVersion(left)
  const b = parseVersion(right)
  const release = compareRelease(a.release, b.release)
  if (release !== 0) return release
  if (a.pre !== b.pre) {
    if (a.pre === null) return 1
    if (b.pre === null) return -1
    return a.pre < b.pre ? -1 : 1
  }
  if (a.dev !== b.dev) {
    if (a.dev === null) return 1
    if (b.dev === null) return -1
    return a.dev < b.dev ? -1 : 1
  }
  if (a.post !== b.post) return a.post < b.post ? -1 : 1
  return 0
}

/** One PEP 440 specifier set, evaluated against a concrete installed version. */
export function satisfies(version, specifier) {
  const text = String(specifier ?? "").trim()
  if (!text) return { ok: true, exact: false }
  let exact = false
  for (const clause of text.split(",").map((item) => item.trim()).filter(Boolean)) {
    const match = /^(==|!=|<=|>=|~=|===|<|>)?\s*(.+)$/.exec(clause)
    if (!match) throw new BuildError("HERMES_SPECIFIER_UNSUPPORTED", `cannot read specifier ${JSON.stringify(clause)}`)
    const operator = match[1] ?? "=="
    const target = match[2].trim()
    if (operator === "===") {
      if (String(version) !== target) return { ok: false, exact: true }
      exact = true
      continue
    }
    if (operator === "==" && target.endsWith(".*")) {
      const prefix = target.slice(0, -2)
      const expected = parseVersion(prefix).release
      const actual = parseVersion(version).release
      if (compareRelease(actual.slice(0, expected.length), expected) !== 0) return { ok: false, exact };
      continue
    }
    if (operator === "~=") {
      const expected = parseVersion(target).release
      if (compareVersions(version, target) < 0) return { ok: false, exact }
      if (compareRelease(parseVersion(version).release.slice(0, Math.max(expected.length - 1, 1)),
        expected.slice(0, Math.max(expected.length - 1, 1))) !== 0) return { ok: false, exact }
      continue
    }
    const order = compareVersions(version, target)
    const ok = operator === "==" ? order === 0
      : operator === "!=" ? order !== 0
        : operator === "<=" ? order <= 0
          : operator === ">=" ? order >= 0
            : operator === "<" ? order < 0
              : operator === ">" ? order > 0
                : null
    if (ok === null) throw new BuildError("HERMES_SPECIFIER_UNSUPPORTED", `unsupported operator ${operator}`)
    if (operator === "==") exact = true
    if (!ok) return { ok: false, exact }
  }
  return { ok: true, exact }
}

// -- environment markers -----------------------------------------------------

const MARKER_KEYWORDS = new Set([])
void MARKER_KEYWORDS

/** A tiny recursive-descent parser for the marker grammar `Requires-Dist` uses.
 *
 * Hand-rolled on purpose: the build must run on `node` alone, with no package
 * manager and no network, and it must refuse anything it does not understand
 * instead of quietly evaluating it as false.
 */
export function evaluateMarker(expression, environment = MARKER_ENVIRONMENT) {
  const tokens = String(expression).match(/[A-Za-z_][A-Za-z0-9_.]*|"[^"]*"|'[^']*'|[()<>=!~,]+|\S/g) ?? []
  let index = 0
  const peek = () => tokens[index]
  const take = () => tokens[index++]
  const fail = (detail) => {
    throw new BuildError("HERMES_MARKER_UNSUPPORTED", `${detail}: ${expression}`)
  }
  const value = (name) => {
    if (name === "extra") return environment.extra ?? ""
    if (Object.prototype.hasOwnProperty.call(environment, name)) return String(environment[name])
    fail(`unknown marker variable ${name}`)
  }
  const comparison = () => {
    const token = take()
    if (token === "(") {
      const nested = expressionGroup()
      if (take() !== ")") fail("unbalanced parentheses")
      return nested
    }
    if (!/^[A-Za-z_]/.test(token) && !token.startsWith("'") && !token.startsWith('"')) fail(`expected operand, got ${token}`)
    const left = token.startsWith("'") || token.startsWith('"')
      ? token.slice(1, -1)
      : value(token)
    const operator = take()
    if (!["==", "!=", "<=", ">=", "<", ">", "in", "not"].includes(operator)) fail(`expected comparison, got ${operator}`)
    if (operator === "not") {
      if (take() !== "in") fail("expected 'in' after 'not'")
    }
    const rightToken = take()
    if (rightToken === undefined) fail("missing right operand")
    const right = rightToken.startsWith("'") || rightToken.startsWith('"')
      ? rightToken.slice(1, -1)
      : value(rightToken)
    const operatorText = operator === "not" ? "not in" : operator
    if (operatorText === "in") return right.includes(left)
    if (operatorText === "not in") return !right.includes(left)
    const ordered = compareLoose(left, right)
    switch (operator) {
      case "==": return ordered === 0
      case "!=": return ordered !== 0
      case "<=": return ordered <= 0
      case ">=": return ordered >= 0
      case "<": return ordered < 0
      case ">": return ordered > 0
      default: fail(`unsupported operator ${operator}`)
        return false
    }
  }
  /** Compare two marker operands: versions when both look numeric, else strings. */
  function compareLoose(left, right) {
    const numeric = /^v?\d/.test(left) && /^v?\d/.test(right)
    if (numeric) {
      try {
        return compareVersions(left, right)
      } catch {
        return left === right ? 0 : (left < right ? -1 : 1)
      }
    }
    return left === right ? 0 : (left < right ? -1 : 1)
  }
  function expressionGroup() {
    let current = conjunction()
    for (let token = peek(); token === "or"; token = peek()) {
      take()
      const right = conjunction()
      current = current || right
    }
    return current
  }
  function conjunction() {
    let current = comparison()
    for (let token = peek(); token === "and"; token = peek()) {
      take()
      const right = comparison()
      current = current && right
    }
    return current
  }
  const result = expressionGroup()
  if (index !== tokens.length) fail(`unconsumed tokens ${tokens.slice(index).join(" ")}`)
  return Boolean(result)
}

export function splitRequirements(metadataText) {
  return metadataText.split(/\r?\n/).filter((line) => line.startsWith("Requires-Dist: "))
    .map((line) => line.slice("Requires-Dist: ".length).trim())
}

/** One `Requires-Dist` value: name, requirement extras, specifier, marker. */
export function parseRequirement(text) {
  let rest = String(text).trim()
  let marker = null
  const semicolon = rest.indexOf(";")
  if (semicolon >= 0) {
    marker = rest.slice(semicolon + 1).trim() || null
    rest = rest.slice(0, semicolon).trim()
  }
  let extras = []
  const extrasMatch = /\[([^\]]*)\]/.exec(rest)
  if (extrasMatch) {
    extras = extrasMatch[1].split(",").map((item) => item.trim()).filter(Boolean)
    rest = (rest.slice(0, extrasMatch.index) + rest.slice(extrasMatch.index + extrasMatch[0].length)).trim()
  }
  // A direct reference (`name @ url`) cannot be resolved from installed
  // metadata; it is carried so an applicable one is refused explicitly.
  const direct = rest.indexOf(" @ ")
  if (direct > 0) {
    const name = rest.slice(0, direct).trim()
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(name)) {
      throw new BuildError("HERMES_REQUIREMENT_UNSUPPORTED", `cannot read requirement ${JSON.stringify(text)}`)
    }
    return { name, extras, specifier: rest.slice(direct + 1).trim(), marker, direct: true }
  }
  const parsed = /^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\(([^)]*)\)\s*)?(.*)$/.exec(rest)
  if (!parsed) throw new BuildError("HERMES_REQUIREMENT_UNSUPPORTED", `cannot read requirement ${JSON.stringify(text)}`)
  const specifier = ((parsed[2] ?? "").trim() || (parsed[3] ?? "").trim())
  if (specifier && !/^[<>=!~]/.test(specifier)) {
    throw new BuildError("HERMES_REQUIREMENT_UNSUPPORTED", `cannot read specifier in ${JSON.stringify(text)}`)
  }
  return { name: parsed[1], extras, specifier, marker, direct: false }
}

export function canonicalize(name) {
  return String(name).toLowerCase().replace(/[-_.]+/g, "-")
}

// -- installed distribution index --------------------------------------------

function metadataFile(directory) {
  for (const candidate of ["METADATA", "PKG-INFO"]) {
    const location = path.join(directory, candidate)
    if (existsSync(location)) return { path: location, text: readFileSync(location, "utf8") }
  }
  return null
}

/** Index every installed distribution under the declared roots.
 *
 * A root is scanned for `*.dist-info` (wheel installs, with `RECORD`) and
 * `*.egg-info` (Debian's platform installs, with `top_level.txt`). Root order is
 * precedence order, and within a root a `dist-info` wins over an `egg-info` for
 * the same project because only it carries a file list.
 */
export function indexDistributions(roots) {
  const index = new Map()
  const add = (name, entry) => {
    const key = canonicalize(name)
    if (!index.has(key)) index.set(key, [])
    index.get(key).push(entry)
  }
  for (const root of roots) {
    for (const entry of readdirSync(root, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue
      const kind = entry.name.endsWith(".dist-info") ? "dist-info"
        : entry.name.endsWith(".egg-info") ? "egg-info" : null
      if (!kind) continue
      const stem = entry.name.slice(0, -1 * (kind === "dist-info" ? ".dist-info".length : ".egg-info".length))
      const separator = stem.lastIndexOf("-")
      const metadata = metadataFile(path.join(root, entry.name))
      let name = separator > 0 ? stem.slice(0, separator) : stem
      let version = separator > 0 ? stem.slice(separator + 1) : ""
      if (metadata) {
        const declaredName = /^Name: (.+)$/m.exec(metadata.text)
        const declaredVersion = /^Version: (.+)$/m.exec(metadata.text)
        if (declaredName) name = declaredName[1].trim()
        if (declaredVersion) version = declaredVersion[1].trim()
      }
      if (!version) throw new BuildError("HERMES_SOURCE_METADATA_INVALID",
        `${root}/${entry.name} declares no version`)
      add(name, {
        name, version, root, kind, directory: path.join(root, entry.name),
        metadataPath: metadata ? metadata.path : null, metadata: metadata ? metadata.text : "",
      })
    }
  }
  for (const [key, entries] of index) {
    entries.sort((left, right) => {
      const rank = (item) => (item.kind === "dist-info" ? 0 : 1)
      return rank(left) - rank(right) || roots.indexOf(left.root) - roots.indexOf(right.root)
    })
    index.set(key, entries)
  }
  return index
}

/** Resolve one requirement against the index, or refuse with a typed code. */
export function resolveRequirement(index, requirement, requiredBy, primaryRoot = undefined) {
  const key = canonicalize(requirement.name)
  if (requirement.direct) {
    throw new BuildError("HERMES_CLOSURE_DIRECT_REFERENCE_UNSUPPORTED",
      `${requiredBy} requires ${requirement.name} from ${requirement.specifier}, which cannot be resolved from installed distributions`)
  }
  const candidates = index.get(key)
  if (!candidates || candidates.length === 0) {
    throw new BuildError("HERMES_CLOSURE_DEPENDENCY_MISSING",
      `${requiredBy} requires ${requirement.name}${requirement.specifier ? requirement.specifier : ""}, which is not installed under the declared roots`)
  }
  const selected = candidates[0]
  const verdict = satisfies(selected.version, requirement.specifier)
  if (!verdict.ok) {
    const deviation = declaredDeviation(requirement.name, requirement.specifier, selected, primaryRoot)
    if (deviation) return { selected, requirement, deviation }
    throw new BuildError("HERMES_CLOSURE_VERSION_MISMATCH",
      `${requiredBy} requires ${requirement.name}${requirement.specifier}, but ${selected.version} is installed in ${selected.root}`)
  }
  return { selected, requirement, deviation: null }
}

/**
 * The full closure, keyed by canonical project name.
 *
 * `extras` are the extras *this artifact provides* for the entry distribution;
 * requirement-level extras (``httpx[socks]``) are propagated as well, because
 * they are part of what that dependency installs. Every followed requirement is
 * checked against the version actually installed - an exact pin must match
 * exactly, a range records what it resolved to.
 */
export function resolveClosure({
  index, entry = ENTRY_DISTRIBUTION, extras = ENTRY_EXTRAS, seeds = null, primaryRoot = undefined,
}) {
  const selected = new Map()
  const reasons = new Map()
  const requirements = new Map()
  const deviations = []
  const queue = seeds
    ? seeds.map((item) => [item.name, new Set(item.extras ?? []), item.requiredBy, item.specifier ?? ""])
    : [[entry, new Set(extras), "root", ""]]
  while (queue.length) {
    const [name, requestedExtras, requiredBy, specifier] = queue.shift()
    const key = canonicalize(name)
    if (selected.has(key)) continue
    const candidates = index.get(key)
    if (!candidates || candidates.length === 0) {
      throw new BuildError("HERMES_CLOSURE_DEPENDENCY_MISSING",
        `${requiredBy} requires ${name}${specifier}, which is not installed under the declared roots`)
    }
    const distribution = candidates[0]
    if (specifier) {
      const verdict = satisfies(distribution.version, specifier)
      if (!verdict.ok) {
        const deviation = declaredDeviation(name, specifier, distribution, primaryRoot)
        if (!deviation) {
          throw new BuildError("HERMES_CLOSURE_VERSION_MISMATCH",
            `${requiredBy} requires ${name}${specifier}, but ${distribution.version} is installed in ${distribution.root}`)
        }
        if (!deviations.some((item) => item.project === deviation.project)) {
          deviations.push({
            project: deviation.project, declared: deviation.declared,
            installed: deviation.installed, root: distribution.root, reason: deviation.reason,
          })
        }
      }
    }
    selected.set(key, distribution)
    reasons.set(key, requiredBy)
    requirements.set(key, specifier || null)
    for (const raw of splitRequirements(distribution.metadata)) {
      const requirement = parseRequirement(raw)
      let applies = requirement.marker === null
      if (requirement.marker !== null) {
        for (const extra of requestedExtras.size ? requestedExtras : new Set([""])) {
          let verdict
          try {
            verdict = evaluateMarker(requirement.marker, { ...MARKER_ENVIRONMENT, extra })
          } catch (error) {
            // A marker naming an extra this build does not provide is simply
            // not applicable; anything else is a refusal.
            if (error.code === "HERMES_MARKER_UNSUPPORTED" && /extra/.test(requirement.marker)) {
              verdict = false
            } else {
              throw error
            }
          }
          if (verdict) {
            applies = true
            break
          }
        }
      }
      if (!applies) continue
      // Resolve eagerly so a version that does not satisfy its pin is refused
      // here, with the requirement that asked for it - not later at dequeue.
      const resolved = resolveRequirement(index, requirement, distribution.name, primaryRoot)
      queue.push([resolved.selected.name, new Set(requirement.extras), distribution.name, requirement.specifier])
    }
  }
  return { selected, reasons, requirements, deviations }
}

// -- source file selection ---------------------------------------------------

const CACHE_SEGMENT = new Set(["__pycache__"])
const TEST_SEGMENTS = new Set(["tests"])

export function isCachePath(relativePath) {
  const segments = relativePath.split("/")
  if (segments.some((segment) => CACHE_SEGMENT.has(segment))) return true
  return relativePath.endsWith(".pyc") || relativePath.endsWith(".pyo")
}

/** Every file one installed distribution contributes, with the reason it was
 * skipped when it contributes none.
 *
 * Two installed shapes exist on this machine and both are read from the
 * distribution's own metadata: a wheel install lists its files in `RECORD`, and
 * a platform (Debian) install that ships no `RECORD` names its top-level modules
 * in `top_level.txt`. Nothing is guessed from a directory listing.
 */
export function distributionFiles(distribution) {
  const files = []
  const skipped = []
  const record = path.join(distribution.directory, "RECORD")
  const topLevel = path.join(distribution.directory, "top_level.txt")
  if (existsSync(record)) {
    const metadataName = path.basename(distribution.directory)
    for (const line of readFileSync(record, "utf8").split(/\r?\n/)) {
      if (!line.trim()) continue
      const relative = line.split(",")[0]
      if (!relative || relative.endsWith("/")) continue
      if (relative === metadataName || relative.startsWith(`${metadataName}/`)) {
        // RECORD lists the metadata directory's own files; that directory is
        // copied whole from its contents, so listing it twice would collide.
        skipped.push({ path: relative, reason: "metadata" })
        continue
      }
      if (isCachePath(relative)) {
        skipped.push({ path: relative, reason: "cache" })
        continue
      }
      if (path.isAbsolute(relative) || relative.split("/").includes("..")) {
        skipped.push({ path: relative, reason: "outside-source" })
        continue
      }
      const source = path.join(distribution.root, relative)
      if (!existsSync(source)) {
        throw new BuildError("HERMES_SOURCE_FILE_MISSING",
          `${metadataName} records ${relative}, which is not installed`)
      }
      files.push({ relative, source })
    }
    return { files, skipped, enumeratedBy: "record" }
  }
  if (!existsSync(topLevel)) {
    throw new BuildError("HERMES_SOURCE_RECORD_MISSING",
      `${distribution.directory} has neither RECORD nor top_level.txt`)
  }
  const names = readFileSync(topLevel, "utf8").split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
  if (!names.length) throw new BuildError("HERMES_SOURCE_RECORD_MISSING", `${topLevel} lists no modules`)
  for (const name of names) {
    const module = path.join(distribution.root, `${name}.py`)
    const packageDirectory = path.join(distribution.root, name)
    if (existsSync(module)) {
      files.push({ relative: `${name}.py`, source: module })
      continue
    }
    if (!existsSync(packageDirectory)) {
      throw new BuildError("HERMES_SOURCE_FILE_MISSING", `${topLevel} names ${name}, which is not installed`)
    }
    const walk = (directory, prefix) => {
      for (const child of readdirSync(directory, { withFileTypes: true })) {
        const source = path.join(directory, child.name)
        const relative = `${prefix}/${child.name}`
        if (child.isSymbolicLink()) {
          throw new BuildError("HERMES_ARTIFACT_SHAPE_INVALID", `${source} is a symlink in the source closure`)
        }
        if (child.isDirectory()) {
          if (isCachePath(relative) || (TEST_SEGMENTS.has(child.name) && prefix === name)) {
            skipped.push({ path: relative, reason: CACHE_SEGMENT.has(child.name) ? "cache" : "tests" })
            continue
          }
          walk(source, relative)
          continue
        }
        if (!child.isFile()) {
          throw new BuildError("HERMES_ARTIFACT_SHAPE_INVALID", `${source} is not a regular file`)
        }
        if (isCachePath(relative)) {
          skipped.push({ path: relative, reason: "cache" })
          continue
        }
        files.push({ relative, source })
      }
    }
    walk(packageDirectory, name)
  }
  return { files, skipped, enumeratedBy: "top-level" }
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
      throw new BuildError("HERMES_ARTIFACT_OUTSIDE_BOUNDS", diagnostic.slice(-300))
    }
    throw new BuildError("HERMES_ARTIFACT_DIGEST_UNAVAILABLE",
      `the reviewed digest implementation refused the tree: ${diagnostic.slice(-400)}`)
  }
  return JSON.parse(result.stdout)
}

// -- source resolution -------------------------------------------------------

/**
 * The site directory this build reads, from an explicit argument or the
 * environment.
 *
 * An explicit source always wins. Without one, `ORDESSA_HERMES_SOURCE` must
 * name the directory: unset or blank is a typed refusal whose message names the
 * variable. There is no fallback default and no `PATH` lookup, so the builder
 * cannot silently build from another machine's site directory, from `$HOME`,
 * from a guessed prefix, or from whatever `hermes` happens to be on `PATH`.
 */
export function resolveSource(explicit = undefined, { env = process.env } = {}) {
  const given = explicit === undefined || explicit === null ? "" : String(explicit).trim()
  if (given) return given
  const declared = String(env[SOURCE_ENVIRONMENT_VARIABLE] ?? "").trim()
  if (declared) return declared
  throw new BuildError("HERMES_SOURCE_UNSET",
    `no source directory: set ${SOURCE_ENVIRONMENT_VARIABLE} to the installed-package directory that holds ` +
    `${ENTRY_DISTRIBUTION}, or pass --source DIR. This build has no machine-local default source and ` +
    "never falls back to a guessed path or to a hermes binary on PATH")
}

/**
 * Refuse a source root this build cannot vouch for, and return it resolved.
 *
 * The root must be an absolute, traversal-free, non-root, non-home, real
 * directory: a symlinked root could be repointed between the check and the
 * read, a `..` segment states an escape, and `/` or `$HOME` would sweep a whole
 * filesystem or a user's private tree into the closure index. A root that is
 * simply absent stays the `HERMES_SOURCE_INVALID` refusal the build already had.
 */
export function assertSourcePolicy(source, { env = process.env, role = "--source" } = {}) {
  if (!path.isAbsolute(source)) {
    throw new BuildError("HERMES_SOURCE_NOT_ABSOLUTE", `${role} must be an absolute path`)
  }
  if (source.split(path.sep).includes("..")) {
    throw new BuildError("HERMES_SOURCE_ESCAPES_ROOT",
      `${role} must not contain a ".." segment: ${source}`)
  }
  const resolved = path.resolve(source)
  if (resolved === path.parse(resolved).root) {
    throw new BuildError("HERMES_SOURCE_UNSAFE", `${role} must not be a filesystem root`)
  }
  const home = env.HOME
  if (home && resolved === path.resolve(home)) {
    throw new BuildError("HERMES_SOURCE_UNSAFE", `${role} must not be the home directory itself`)
  }
  const stats = lstatSync(resolved, { throwIfNoEntry: false })
  if (stats === undefined) {
    throw new BuildError("HERMES_SOURCE_INVALID",
      `the ${role} root ${resolved} is not a readable installed-package directory`)
  }
  if (stats.isSymbolicLink()) {
    throw new BuildError("HERMES_SOURCE_SYMLINK",
      `the ${role} root ${resolved} is a symlink; declare the real installed-package directory it points at, `
      + "because a symlink can be repointed between this check and the read")
  }
  if (!stats.isDirectory()) {
    throw new BuildError("HERMES_SOURCE_INVALID",
      `the ${role} root ${resolved} is not a readable installed-package directory`)
  }
  return resolved
}

// -- output policy -----------------------------------------------------------

const RESERVED_ROOTS = [".config", ".local", ".hermes", ".agentbox", ".ssh", ".gnupg"]

export function assertOutputPolicy(output, { repo = REPO } = {}) {
  if (!path.isAbsolute(output)) throw new BuildError("HERMES_OUTPUT_NOT_ABSOLUTE", "--output must be an absolute path")
  const resolved = path.resolve(output)
  if (resolved === repo || resolved.startsWith(repo + path.sep)) {
    throw new BuildError("HERMES_OUTPUT_INSIDE_REPOSITORY", "--output must be outside the repository")
  }
  if (resolved === "/" || resolved === path.parse(resolved).root) {
    throw new BuildError("HERMES_OUTPUT_UNSAFE", "--output must not be a filesystem root")
  }
  const home = process.env.HOME
  if (home) {
    for (const reserved of RESERVED_ROOTS) {
      const forbidden = path.join(home, reserved)
      if (resolved === forbidden || resolved.startsWith(forbidden + path.sep)) {
        throw new BuildError("HERMES_OUTPUT_RESERVED", "--output must not be a user configuration directory")
      }
    }
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

function makeReadOnly(root) {
  const walk = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const location = path.join(directory, entry.name)
      if (entry.isDirectory()) walk(location)
      else chmodSync(location, 0o444)
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
    throw new BuildError("HERMES_OUTPUT_NOT_OWNED", `${output} is a symlink; refusing to touch it`)
  }
  if (!stats.isDirectory()) {
    throw new BuildError("HERMES_OUTPUT_NOT_OWNED", `${output} is not a directory; refusing to touch it`)
  }
  if (isOwnedArtifact(output)) {
    if (!replace) {
      throw new BuildError("HERMES_OUTPUT_EXISTS", `${output} is an existing artifact; pass --replace to rebuild it`)
    }
    makeWritable(output)
    rmSync(output, { recursive: true, force: true })
    return
  }
  if (readdirSync(output).length === 0) {
    rmdirSync(output)
    return
  }
  throw new BuildError("HERMES_OUTPUT_NOT_OWNED",
    `${output} is non-empty and carries no builder marker; refusing to overwrite it`)
}

// -- build -------------------------------------------------------------------

const PORTABLE_PATH = /^[\x21-\x7e]+$/

function assertPlainTree(root) {
  const problems = []
  const walk = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const location = path.join(directory, entry.name)
      const stats = lstatSync(location)
      const relative = path.relative(root, location)
      if (stats.isSymbolicLink()) problems.push(`symlink ${relative}`)
      else if (stats.isDirectory()) walk(location)
      else if (!stats.isFile()) problems.push(`special ${relative}`)
    }
  }
  walk(root)
  if (problems.length) {
    throw new BuildError("HERMES_ARTIFACT_SHAPE_INVALID",
      `the tree is not a plain file tree: ${problems.slice(0, 5).join(", ")}`)
  }
}

/** Copy one artifact file, refusing anything the tree digest would.
 *
 * `artifactPath` is the path *as it will appear in the artifact* (used for the
 * portability and collision rules); `destination` is where it is written, which
 * for overlay files deliberately differs from the review-time name.
 */
function copyOne(source, destination, artifactPath, counters, seen) {
  if (!PORTABLE_PATH.test(artifactPath)) {
    throw new BuildError("HERMES_ARTIFACT_PATH_UNPORTABLE", `${artifactPath} is not printable ASCII`)
  }
  const folded = artifactPath.toLowerCase()
  if (seen.has(folded)) {
    throw new BuildError("HERMES_ARTIFACT_PATH_CONFLICT", `${artifactPath} duplicates another artifact path`)
  }
  seen.add(folded)
  const stats = lstatSync(source)
  if (stats.isSymbolicLink()) {
    throw new BuildError("HERMES_ARTIFACT_SHAPE_INVALID", `${source} is a symlink in the source closure`)
  }
  if (!stats.isFile()) {
    throw new BuildError("HERMES_ARTIFACT_SHAPE_INVALID", `${source} is not a regular file`)
  }
  mkdirSync(path.dirname(destination), { recursive: true })
  copyFileSync(source, destination)
  chmodSync(destination, 0o644)
  counters.files += 1
  counters.bytes += stats.size
}

function copyMetadataDirectory(distribution, destination, counters, seen) {
  const metadataName = path.basename(distribution.directory)
  const walk = (from, to, prefix) => {
    for (const entry of readdirSync(from, { withFileTypes: true })) {
      const source = path.join(from, entry.name)
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name
      if (entry.isSymbolicLink()) {
        throw new BuildError("HERMES_ARTIFACT_SHAPE_INVALID", `${source} is a symlink in the source closure`)
      }
      if (entry.isDirectory()) {
        if (CACHE_SEGMENT.has(entry.name)) {
          counters.skippedFiles += 1
          continue
        }
        walk(source, path.join(to, entry.name), relative)
        continue
      }
      if (!entry.isFile()) {
        throw new BuildError("HERMES_ARTIFACT_SHAPE_INVALID", `${source} is not a regular file`)
      }
      if (isCachePath(relative)) {
        counters.skippedFiles += 1
        continue
      }
      copyOne(source, path.join(to, entry.name), `${metadataName}/${relative}`, counters, seen)
    }
  }
  walk(distribution.directory, destination, "")
}

function win32OnlyDistributions(index) {
  const win32 = { ...MARKER_ENVIRONMENT, sys_platform: "win32", os_name: "nt", platform_system: "Windows" }
  const names = new Set()
  for (const distribution of index.values()) {
    for (const raw of splitRequirements(distribution[0].metadata)) {
      const requirement = parseRequirement(raw)
      if (!requirement.marker) continue
      let onWindows = false
      let onLinux = false
      try {
        onWindows = evaluateMarker(requirement.marker, { ...win32, extra: "" })
      } catch { onWindows = false }
      try {
        onLinux = evaluateMarker(requirement.marker, { ...MARKER_ENVIRONMENT, extra: "" })
      } catch { onLinux = false }
      if (onWindows && !onLinux) names.add(canonicalize(requirement.name))
    }
  }
  return names
}

export function build({
  output, source = undefined, fallbackSources = DEFAULT_FALLBACK_SOURCES, replace = false,
  env = process.env,
}) {
  const resolved = assertOutputPolicy(output)
  const roots = [
    assertSourcePolicy(resolveSource(source, { env }), { env }),
    ...fallbackSources.map((item) => assertSourcePolicy(item, { env, role: "--fallback-source" })),
  ]
  const index = indexDistributions(roots)
  const entryKey = canonicalize(ENTRY_DISTRIBUTION)
  const entryCandidates = index.get(entryKey)
  if (!entryCandidates || entryCandidates.length === 0) {
    throw new BuildError("HERMES_CLOSURE_ENTRY_MISSING",
      `${ENTRY_DISTRIBUTION} is not installed under ${roots.join(", ")}`)
  }
  const entry = entryCandidates[0]
  if (entry.version !== ENTRY_VERSION) {
    throw new BuildError("HERMES_ENTRY_VERSION_MISMATCH",
      `${ENTRY_DISTRIBUTION} must be ${ENTRY_VERSION}, found ${entry.version}`)
  }
  // (2) the entry point's extra must exist, and must be the one that provides
  // the module the ACP entry imports.
  for (const extra of ENTRY_EXTRAS) {
    if (!new RegExp(`^Provides-Extra: ${extra}$`, "m").test(entry.metadata)) {
      throw new BuildError("HERMES_CLOSURE_ENTRY_EXTRA_UNKNOWN",
        `${ENTRY_DISTRIBUTION} declares no extra ${extra}`)
    }
  }
  const { selected, reasons, requirements, deviations } = resolveClosure({
    index, extras: ENTRY_EXTRAS, primaryRoot: roots[0],
  })
  const baseClosure = resolveClosure({ index, extras: [], primaryRoot: roots[0] })
  const entryModuleFiles = distributionFiles(entry).files.map((item) => item.relative)
  if (!entryModuleFiles.includes(ENTRY_RELATIVE)) {
    throw new BuildError("HERMES_CLOSURE_ENTRY_MISSING",
      `${ENTRY_DISTRIBUTION} does not install ${ENTRY_RELATIVE}`)
  }
  const entrySource = readFileSync(path.join(entry.root, ENTRY_RELATIVE), "utf8")
  if (!/from acp_adapter\.entry import|import acp\b/.test(entrySource)) {
    throw new BuildError("HERMES_CLOSURE_ENTRY_EXTRA_UNUSED",
      `${ENTRY_RELATIVE} does not import the ACP module the ${ENTRY_EXTRAS.join(",")} extra provides`)
  }
  // The extra's delta must be exactly the transitive closure of the entry
  // point's own extra requirements: a distribution that entered only because an
  // extra was evaluated, and that the provided extras do not require, is a
  // packaged dependency nobody asked for.
  const extraSeeds = []
  for (const raw of splitRequirements(entry.metadata)) {
    const requirement = parseRequirement(raw)
    if (!requirement.marker || !/\bextra\b/.test(requirement.marker)) continue
    let applies = false
    for (const extra of ENTRY_EXTRAS) {
      try {
        if (evaluateMarker(requirement.marker, { ...MARKER_ENVIRONMENT, extra })) applies = true
      } catch {
        applies = false
      }
    }
    if (applies) {
      extraSeeds.push({
        name: requirement.name, extras: requirement.extras,
        requiredBy: `${entry.name}[${ENTRY_EXTRAS.join(",")}]`, specifier: requirement.specifier,
      })
    }
  }
  if (extraSeeds.length === 0) {
    throw new BuildError("HERMES_CLOSURE_EXTRA_UNUSED",
      `the ${ENTRY_EXTRAS.join(",")} extra requires nothing in ${ENTRY_DISTRIBUTION}'s metadata`)
  }
  const extraClosure = resolveClosure({ index, seeds: extraSeeds, primaryRoot: roots[0] })
  const extrasDelta = [...selected.keys()].filter((key) => !baseClosure.selected.has(key)).sort()
  const extrasDeltaExpected = [...extraClosure.selected.keys()]
    .filter((key) => !baseClosure.selected.has(key)).sort()
  const unexpected = extrasDelta.filter((key) => !extrasDeltaExpected.includes(key))
  const missing = extrasDeltaExpected.filter((key) => !extrasDelta.includes(key))
  if (unexpected.length) {
    throw new BuildError("HERMES_ARTIFACT_UNRELATED_DISTRIBUTION",
      `${unexpected.join(", ")} is reachable only through an extra this artifact provides but did not expect`)
  }
  if (missing.length) {
    throw new BuildError("HERMES_CLOSURE_EXTRA_UNUSED",
      `the ${ENTRY_EXTRAS.join(",")} extra did not resolve ${missing.join(", ")}`)
  }
  // (5) nothing unrelated may ride along.
  const win32Only = [...win32OnlyDistributions(index)].filter((key) => selected.has(key)).sort()
  if (win32Only.length) {
    throw new BuildError("HERMES_ARTIFACT_UNRELATED_DISTRIBUTION",
      `win32-only distributions entered the closure: ${win32Only.join(", ")}`)
  }
  const unrelatedClosure = resolveClosure({
    index, entry: UNRELATED_REFERENCE, extras: [], primaryRoot: roots[0],
  })
  const unrelatedOnly = [...unrelatedClosure.selected.keys()]
    .filter((key) => !selected.has(key)).sort()
  if (unrelatedOnly.length === 0) {
    throw new BuildError("HERMES_ARTIFACT_UNRELATED_PROBE_EMPTY",
      `the ${UNRELATED_REFERENCE} closure shares every distribution with Hermes; the exclusion probe proves nothing`)
  }
  // Distributions the entry point requires *only* through extras this artifact
  // does not provide. They are the "an extra rode along" canary: a name here
  // that is not reachable without any extra at all can only be present because a
  // non-entry extra was evaluated.
  const baseNames = new Set(baseClosure.selected.keys())
  const extrasOnlyNames = new Set()
  const declaredExtras = [...entry.metadata.matchAll(/^Provides-Extra: (.+)$/gm)]
    .map((match) => match[1].trim())
  for (const raw of splitRequirements(entry.metadata)) {
    const requirement = parseRequirement(raw)
    if (!requirement.marker) continue
    for (const extra of declaredExtras) {
      if (ENTRY_EXTRAS.includes(extra)) continue
      let applies = false
      try {
        applies = evaluateMarker(requirement.marker, { ...MARKER_ENVIRONMENT, extra })
      } catch {
        applies = false
      }
      if (applies) extrasOnlyNames.add(canonicalize(requirement.name))
    }
  }
  const extrasOnly = [...extrasOnlyNames].sort()
  const extrasLeaked = extrasOnly.filter((key) => selected.has(key) && !baseNames.has(key))
  if (extrasLeaked.length) {
    throw new BuildError("HERMES_ARTIFACT_UNRELATED_DISTRIBUTION",
      `${extrasLeaked.join(", ")} is reachable only through an extra this artifact does not provide`)
  }

  const packages = [...selected.entries()].map(([key, distribution]) => ({
    name: distribution.name,
    version: distribution.version,
    root: distribution.root,
    metadata: distribution.kind,
    reason: reasons.get(key) ?? null,
    requires: requirements.get(key) ?? null,
    fallback: distribution.root !== roots[0],
    metadataSha256: createHash("sha256").update(distribution.metadata).digest("hex"),
  })).sort((left, right) => left.name.localeCompare(right.name))
  for (const item of packages) {
    if (item.fallback && !roots.slice(1).includes(item.root)) {
      throw new BuildError("HERMES_SOURCE_INVALID", `${item.name} was resolved outside the declared roots`)
    }
  }

  clearTarget(resolved, { replace })
  mkdirSync(path.dirname(resolved), { recursive: true })
  const staging = mkdtempSync(path.join(path.dirname(resolved), `${path.basename(resolved)}.building-`))
  writeFileSync(path.join(staging, MARKER_NAME), MARKER_CONTENT)
  const counters = { files: 0, bytes: 0, skippedFiles: 0, skippedDirectories: 0 }
  const seen = new Set()
  const skipped = []
  const enumeratedBy = new Map()
  try {
    const sitePackages = path.join(staging, "site-packages")
    mkdirSync(sitePackages, { recursive: true })
    for (const [key, distribution] of [...selected.entries()].sort(([left], [right]) => left.localeCompare(right))) {
      const { files, skipped: distributionSkipped, enumeratedBy: how } = distributionFiles(distribution)
      enumeratedBy.set(canonicalize(distribution.name), how)
      for (const item of distributionSkipped) {
        skipped.push({ package: distribution.name, path: item.path, reason: item.reason })
        if (item.reason === "cache") counters.skippedFiles += 1
      }
      for (const item of files) {
        copyOne(item.source, path.join(sitePackages, item.relative), item.relative, counters, seen)
      }
      copyMetadataDirectory(
        distribution, path.join(sitePackages, path.basename(distribution.directory)), counters, seen,
      )
    }
    const overlays = []
    for (const [relative, destinationName] of OVERLAY_FILES) {
      const overlaySource = path.join(OVERLAY_DIRECTORY, relative)
      if (!existsSync(overlaySource)) {
        throw new BuildError("HERMES_ARTIFACT_OVERLAY_MISSING", `${overlaySource} is not present`)
      }
      const content = readFileSync(overlaySource)
      copyOne(overlaySource, path.join(sitePackages, destinationName), destinationName, counters, seen)
      overlays.push({
        name: destinationName, source: `deploy/hermes/${relative}`,
        sha256: "sha256:" + createHash("sha256").update(content).digest("hex"),
      })
    }
    for (const item of packages) item.filesFrom = enumeratedBy.get(canonicalize(item.name)) ?? null
    const unrelatedSelected = [...selected.keys()].filter((key) => unrelatedOnly.includes(key))
    if (unrelatedSelected.length) {
      throw new BuildError("HERMES_ARTIFACT_UNRELATED_DISTRIBUTION",
        `${unrelatedSelected.join(", ")} is reachable only from ${UNRELATED_REFERENCE}`)
    }
    assertPlainTree(staging)
    const summary = treeSummary(staging)
    if (Number(summary.entries) > MAX_ENTRIES || Number(summary.bytes) > MAX_BYTES) {
      throw new BuildError("HERMES_ARTIFACT_OUTSIDE_BOUNDS",
        `${summary.entries} entries / ${summary.bytes} bytes exceed the runtime artifact bounds`)
    }
    makeReadOnly(staging)
    const resolutionDigest = "sha256:" + createHash("sha256").update(JSON.stringify({
      entry: { name: ENTRY_DISTRIBUTION, version: ENTRY_VERSION, extras: ENTRY_EXTRAS },
      packages: packages.map((item) => [item.name, item.version, item.root, item.metadataSha256]),
      overlays,
    })).digest("hex")
    const manifest = {
      schemaVersion: 1,
      kind: "agentbox-hermes-runtime-artifact",
      entry: {
        package: ENTRY_DISTRIBUTION, version: ENTRY_VERSION, extras: ENTRY_EXTRAS,
        module: ENTRY_MODULE, relative: `site-packages/${ENTRY_RELATIVE}`,
        sourceRoots: roots,
      },
      packages,
      overlays,
      pinDeviations: deviations,
      excluded: {
        extrasDeclared: declaredExtras,
        extrasProvided: ENTRY_EXTRAS,
        extrasOnlyNames: extrasOnly,
        extrasDelta,
        win32OnlyRequirements: [...win32OnlyDistributions(index)].sort(),
        unrelatedReference: UNRELATED_REFERENCE,
        unrelatedOnlyPackages: unrelatedOnly,
        rules: ["cache", "tests", "non-printable-paths"],
        skippedFiles: counters.skippedFiles,
        skippedDirectories: counters.skippedDirectories,
        skipped: skipped.slice(0, 50),
        skippedTotal: skipped.length,
      },
      entries: Number(summary.entries),
      bytes: Number(summary.bytes),
      treeDigest: summary.digest,
      resolutionDigest,
    }
    renameSync(staging, resolved)
    writeFileSync(`${resolved}.manifest.json`, JSON.stringify(manifest, null, 2) + "\n")
    return { ...manifest, output: resolved, sources: roots }
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

// -- dependency self-check (the artifact alone must satisfy the interpreter) ---

export function selfCheck(output) {
  const sitePackages = path.join(output, "site-packages")
  const program = [
    "import json, sys",
    "modules = ['hermes_cli.main', 'acp_adapter.entry', 'acp', 'openai', 'distro', 'markupsafe', 'pytz', 'six', 'markdown_it', 'mdurl', 'rich', 'jinja2', 'croniter']",
    "resolved = {}",
    "for name in modules:",
    "    module = __import__(name)",
    "    resolved[name] = getattr(module, '__file__', '')",
    "print(json.dumps(resolved))",
  ].join("\n")
  // `-S` disables the site machinery, so neither the per-user directory nor the
  // platform `dist-packages` can satisfy an import: only the artifact can.
  const result = spawnSync("/usr/bin/python3", ["-S", "-c", program], {
    env: { PATH: "/usr/bin:/bin", PYTHONPATH: sitePackages, PYTHONDONTWRITEBYTECODE: "1" },
    encoding: "utf8",
  })
  if (result.status !== 0) {
    throw new BuildError("HERMES_ARTIFACT_NOT_SELF_CONTAINED",
      `the artifact cannot import its own entry point: ${(result.stderr ?? "").trim().slice(-300)}`)
  }
  const resolved = JSON.parse(result.stdout)
  const outside = Object.entries(resolved)
    .filter(([, location]) => !String(location).startsWith(sitePackages + "/"))
    .map(([name, location]) => `${name}=${location}`)
  if (outside.length) {
    throw new BuildError("HERMES_ARTIFACT_NOT_SELF_CONTAINED",
      `imports resolved outside the artifact: ${outside.slice(0, 5).join(", ")}`)
  }
  return resolved
}

function argument(name) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : undefined
}

function main() {
  const output = argument("--output")
  // Left undefined when --source is absent, so build() resolves the declared
  // environment variable and refuses when that is unset too.
  const source = argument("--source")
  const fallback = argument("--fallback-source")
  const json = process.argv.includes("--json")
  if (!output) {
    process.stdout.write(JSON.stringify({
      result: "HERMES_RUNTIME_BUILD_FAILED", code: "HERMES_USAGE",
      error: "usage: build-hermes-runtime-artifact.mjs --output ABSOLUTE_DIR [--source DIR] "
        + `[--fallback-source DIR] [--replace] [--json]; with no --source, ${SOURCE_ENVIRONMENT_VARIABLE} must name the source directory`,
    }) + "\n")
    return 2
  }
  try {
    const result = build({
      output, source,
      fallbackSources: fallback ? fallback.split(":") : DEFAULT_FALLBACK_SOURCES,
      replace: process.argv.includes("--replace"),
    })
    const selfChecked = process.argv.includes("--no-self-check") ? null : selfCheck(result.output)
    process.stdout.write(JSON.stringify({
      result: "HERMES_RUNTIME_ARTIFACT_BUILT",
      output: result.output, treeDigest: result.treeDigest,
      entries: result.entries, bytes: result.bytes,
      entry: result.entry, packages: result.packages.length,
      fallbackPackages: result.packages.filter((item) => item.fallback).map((item) => item.name),
      resolutionDigest: result.resolutionDigest,
      overlays: result.overlays,
      selfCheckModules: selfChecked ? Object.keys(selfChecked).length : null,
      manifest: `${result.output}.manifest.json`,
    }) + "\n")
    return 0
  } catch (error) {
    process.stdout.write(JSON.stringify({
      result: "HERMES_RUNTIME_BUILD_FAILED",
      code: error.code ?? "HERMES_RUNTIME_BUILD_ERROR",
      error: String(error.message ?? error).slice(0, 500),
      ...(json ? { stack: String(error.stack ?? "").split("\n").slice(0, 4).join(" | ") } : {}),
    }) + "\n")
    return 1
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  process.exitCode = main()
}
