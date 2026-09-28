// Single source of version + build number (C-09 A4, FR-001).
//
// The version value itself lives in `apps/desktop/package.json` -- that file
// belongs to P-A and P-C only reads it. Every other place the release reports a
// version (about panel, diagnostics `meta.json`, update manifest, deb control
// file) is *derived* from here, so drift is impossible by construction rather
// than by convention. `checkVersionConsistency` then reads the derived
// artefacts back off disk and fails if any of them disagrees.

import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

const FALLBACK = {
  name: 'Ordessa',
  description: 'Ordessa desktop product',
  author: 'Ordessa',
  homepage: 'https://github.com/mmm-05610/agent-box',
  license: 'SEE LICENSE IN /opt/ordessa/licenses/LICENSE',
}

// P-A owns `apps/desktop/package.json` and has not yet delivered the product
// metadata block (PA-02 is not in this worktree yet). Debian requires
// Maintainer/Homepage, so until P-A lands the real values we substitute
// constants and record it as a controlled stub. The real fields win the moment
// they exist -- `metaStubs` is reported by the build so the report can say so.
export function readProductMeta() {
  const pkg = JSON.parse(readFileSync(path.join(repoRoot, 'apps/desktop/package.json'), 'utf8'))
  const pick = key => (pkg[key] && String(pkg[key]).trim()) || FALLBACK[key] || ''
  const stubs = ['productName', 'description', 'author', 'homepage', 'license']
    .filter(key => !pkg[key] || !String(pkg[key]).trim())
  return {
    pkgName: 'ordessa',
    name: FALLBACK.name,
    productName: pick('productName'),
    version: pkg.version,
    description: pick('description'),
    author: pick('author'),
    homepage: pick('homepage'),
    license: pick('license'),
    metaStubs: stubs,
  }
}

function shortSha() {
  try {
    return execFileSync('git', ['rev-parse', '--short=9', 'HEAD'], {
      cwd: repoRoot, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
  } catch {
    return 'unknown000'
  }
}

// Build number = build date + short SHA (C-09 A4). `SOURCE_DATE_EPOCH` pins the
// date so a rebuild of the same commit reproduces the same build number.
export function buildNumber(now = new Date()) {
  const epoch = process.env.SOURCE_DATE_EPOCH
  const date = epoch ? new Date(Number(epoch) * 1000) : now
  return `${date.toISOString().slice(0, 10).replace(/-/g, '')}-${shortSha()}`
}

export function identity(now = new Date()) {
  return { ...readProductMeta(), build: buildNumber(now) }
}
