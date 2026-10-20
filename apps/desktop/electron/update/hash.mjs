// Hashing helpers for the release artefacts (C-09 D, FR-079).
//
// `SHA256SUMS` must cover the deb, the bundle manifest and the `app/` tree.
// A tree hash needs a *deterministic* definition, otherwise the same bytes
// hash differently on two machines: entries are sorted by POSIX relative path
// and hashed as `<sha256>  <relpath>\n`, and the tree hash is the sha256 of
// that listing. Symlinks hash as their target string, not their contents.

import { createHash } from 'node:crypto'
import { readFileSync, readdirSync, lstatSync, readlinkSync, existsSync } from 'node:fs'
import path from 'node:path'

export function sha256File(file) {
  return createHash('sha256').update(readFileSync(file)).digest('hex')
}

export function sha256Bytes(bytes) {
  return createHash('sha256').update(bytes).digest('hex')
}

function walk(root, base = root, out = []) {
  for (const entry of readdirSync(root).sort()) {
    const full = path.join(root, entry)
    const st = lstatSync(full)
    if (st.isDirectory()) walk(full, base, out)
    else out.push({ full, rel: path.relative(base, full) })
  }
  return out
}

// The canonical per-file listing, shared by `treeHash` and the `SHA256SUMS`
// writer so the two can never disagree about what a file's hash line is.
export function treeListing(root) {
  if (!existsSync(root)) return []
  return walk(root)
    .sort((a, b) => (a.rel < b.rel ? -1 : a.rel > b.rel ? 1 : 0))
    .map(({ full, rel }) => {
      const st = lstatSync(full)
      // A symlink is identified by its target -- hashing the resolved content
      // would make the entry depend on whether the target is present.
      const digest = st.isSymbolicLink() ? sha256Bytes(Buffer.from(readlinkSync(full))) : sha256File(full)
      return { rel: rel.split(path.sep).join('/'), sha256: digest, symlink: st.isSymbolicLink() }
    })
}

export function treeHash(root) {
  const listing = treeListing(root)
  if (listing.length === 0) return null
  const text = listing.map(e => `${e.sha256}  ${e.rel}\n`).join('')
  return sha256Bytes(Buffer.from(text, 'utf8'))
}

export function writeSumsFile(target, entries) {
  const text = entries.map(e => `${e.sha256}  ${e.rel}\n`).join('')
  return { text, write: () => text }
}
