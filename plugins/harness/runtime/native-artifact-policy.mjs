/** Native installed assets trust root administration plus content verification.
 * This is a separate guarantee from the sidecar's read-only mount policy.
 */
import fs from "node:fs"
import path from "node:path"
import { createHash } from "node:crypto"

const MAX_ENTRIES = 32768
const MAX_BYTES = 1024 * 1024 * 1024
const DIGEST = /^sha256:[0-9a-f]{64}$/
const NATIVE_PROFILE = {
  'codex-runtime': { packageName: '@agentclientprotocol/codex-acp', version: '1.1.14',
    id: 'codex-profile', source: '9634b5457e44d55471d0969bcc5a2a1d4cbb83ba637eaf023d34d2e975fd7db8' },
  'claude-runtime': { packageName: '@agentclientprotocol/claude-agent-acp', version: '0.81.2',
    id: 'claude-code-profile', source: '36a33a984624541ea013c085f5bd1d982294cfe70beb42826752f62bdc538d64' },
}

function trustedStat(file, directory = false) {
  const stat = fs.lstatSync(file)
  if (stat.uid !== 0 || (stat.mode & 0o022) !== 0 || stat.isSymbolicLink()
      || (directory ? !stat.isDirectory() : !stat.isFile())) throw new Error("untrusted installed asset")
  return stat
}

function trustedAncestors(directory) {
  let current = directory
  for (;;) {
    trustedStat(current, true)
    const parent = path.dirname(current)
    if (parent === current) return
    current = parent
  }
}

function readTrustedFile(file, stat, consume) {
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW)
  try {
    const opened = fs.fstatSync(fd)
    if (!opened.isFile() || opened.uid !== 0 || (opened.mode & 0o022) !== 0
        || opened.ino !== stat.ino || opened.dev !== stat.dev || opened.size !== stat.size) {
      throw new Error("installed asset changed")
    }
    const result = consume(fd)
    const after = fs.fstatSync(fd)
    if (after.size !== opened.size || after.mtimeMs !== opened.mtimeMs || after.ctimeMs !== opened.ctimeMs) {
      throw new Error("installed asset changed")
    }
    return result
  } finally { fs.closeSync(fd) }
}

function trustedJson(file) {
  const stat = trustedStat(file)
  if (stat.size > 1024 * 1024) throw new Error("installed manifest outside bounds")
  return readTrustedFile(file, stat, (fd) => JSON.parse(fs.readFileSync(fd, "utf8")))
}

/** Same v1 encoding as runtime_artifact_tree_summary, including case/path bounds. */
export function installedArtifactSummary(root) {
  trustedStat(root, true)
  const entries = []
  const seen = new Set()
  let bytes = 0
  function walk(directory, prefix = "") {
    for (const name of fs.readdirSync(directory)) {
      const relative = prefix ? `${prefix}/${name}` : name
      const encoded = Buffer.from(relative)
      if (encoded.length > 4096 || !/^[\x21-\x7e]+$/.test(relative)
          || relative.split("/").some((part) => !part || part === "." || part === "..")) {
        throw new Error("installed artifact path invalid")
      }
      const key = relative.toLowerCase()
      if (seen.has(key) || seen.size >= MAX_ENTRIES) throw new Error("installed artifact entries invalid")
      seen.add(key)
      const file = path.join(directory, name)
      const stat = fs.lstatSync(file)
      if (stat.isDirectory()) {
        trustedStat(file, true)
        entries.push({ kind: "d", encoded })
        walk(file, relative)
      } else {
        trustedStat(file)
        bytes += stat.size
        if (!Number.isSafeInteger(stat.size) || bytes > MAX_BYTES) throw new Error("installed artifact bytes invalid")
        const content = readTrustedFile(file, stat, (fd) => {
          const hash = createHash("sha256")
          const chunk = Buffer.alloc(64 * 1024)
          let length
          while ((length = fs.readSync(fd, chunk, 0, chunk.length, null)) > 0) hash.update(chunk.subarray(0, length))
          return hash.digest()
        })
        entries.push({ kind: "f", encoded, size: stat.size, content })
      }
    }
  }
  walk(root)
  entries.sort((left, right) => Buffer.compare(left.encoded, right.encoded))
  const hash = createHash("sha256").update("agentbox-runtime-artifact-tree-v1\n")
  const count = Buffer.alloc(8); count.writeBigUInt64BE(BigInt(entries.length)); hash.update(count)
  for (const entry of entries) {
    const length = Buffer.alloc(4); length.writeUInt32BE(entry.encoded.length)
    hash.update(entry.kind).update(length).update(entry.encoded)
    if (entry.kind === "f") {
      const size = Buffer.alloc(8); size.writeBigUInt64BE(BigInt(entry.size))
      hash.update(size).update(entry.content)
    }
  }
  return { digest: `sha256:${hash.digest("hex")}`, entries: entries.length, bytes }
}

export function verifyInstalledArtifact({ artifactBase, artifact, packageName, version, variant = "default" }) {
  // This is a bounded variant, not a caller-supplied entry override.
  const profileBridge = variant === "pi-profile"
  const nativeProfile = variant === 'native-profile' ? NATIVE_PROFILE[artifact] : null
  if ((variant !== "default" && !profileBridge && !nativeProfile)
      || (nativeProfile && (packageName !== nativeProfile.packageName || version !== nativeProfile.version))
      || (profileBridge && (artifact !== "pi-profile-runtime" || packageName !== "@automatalabs/pi-acp"))) {
    throw new Error("installed artifact variant invalid")
  }
  if (typeof artifactBase !== "string" || !path.isAbsolute(artifactBase)
      || path.resolve(artifactBase) !== artifactBase || artifactBase.includes("\0")) {
    throw new Error("installed artifact base invalid")
  }
  trustedAncestors(artifactBase)
  const root = path.join(artifactBase, artifact)
  trustedStat(root, true)
  const manifest = trustedJson(`${root}.manifest.json`)
  const relativeEntry = `node_modules/${packageName}/dist/${profileBridge || nativeProfile ? "ordessa-profile.mjs" : "index.js"}`
  // sourceLockDigest records builder provenance; no source lock is bound here,
  // so validate its format without claiming to compare the original lock bytes.
  if (manifest.schemaVersion !== 1 || manifest.kind !== `agentbox-${profileBridge ? "pi-runtime" : artifact}-artifact`
      || manifest.adapter?.package !== packageName || manifest.adapter?.version !== version
      || manifest.adapter?.entry !== relativeEntry || !DIGEST.test(manifest.treeDigest)
      || !DIGEST.test(manifest.sourceLockDigest) || !Number.isSafeInteger(manifest.entries)
      || !Number.isSafeInteger(manifest.bytes)) throw new Error("installed manifest invalid")
  if (profileBridge) {
    const extension = manifest.ordessaExtension
    if (!extension || Object.keys(extension).length !== 4 || extension.id !== "pi-profile"
        || extension.version !== 1 || extension.configurationQuery !== "_ordessa/session/configuration"
        || extension.instanceDirectoryRequired !== true) throw new Error("installed extension invalid")
  }
  if (nativeProfile) {
    const extension = manifest.extension
    const managedScope = extension && Object.hasOwn(extension, 'managedAccountScope')
    if (!extension || Object.keys(extension).length !== (managedScope ? 6 : 5)
        || (managedScope && (artifact !== 'codex-runtime' || extension.managedAccountScope !== true))
        || extension.id !== nativeProfile.id
        || extension.version !== 1 || extension.configurationQuery !== '_ordessa/session/configuration'
        || extension.instanceDirectoryRequired !== true
        || extension.upstreamSourceDigest !== `sha256:${nativeProfile.source}`
        || Object.hasOwn(manifest, 'ordessaExtension')) throw new Error('installed extension invalid')
  } else if (Object.hasOwn(manifest, 'extension')
      || (!profileBridge && Object.hasOwn(manifest, 'ordessaExtension'))) {
    // Never silently adopt enhanced behaviour on the ordinary route, even
    // if a manifest is altered to select the upstream entry filename.
    throw new Error('installed extension requires explicit variant')
  }
  const summary = installedArtifactSummary(root)
  if (summary.digest !== manifest.treeDigest || summary.entries !== manifest.entries
      || summary.bytes !== manifest.bytes) throw new Error("installed artifact digest mismatch")
  const packageManifest = trustedJson(path.join(root, "node_modules", packageName, "package.json"))
  if (packageManifest.name !== packageName || packageManifest.version !== version) throw new Error("installed package pin mismatch")
  const entry = path.join(root, relativeEntry)
  trustedStat(entry)
  return entry
}
