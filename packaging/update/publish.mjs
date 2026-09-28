// Sign an update manifest and publish a controlled local update source
// (PC-08, PC-14).
//
//   node packaging/update/publish.mjs --deb <path> --out <dir> [--private <pem>]
//        [--url-base https://...] [--version x.y.z] [--build b] [--notes "..."]
//        [--min-data-schema N]
//
// Writes <out>/update-manifest.json plus a copy of the deb, served over plain
// HTTP for the acceptance run. The signature covers the manifest's key metadata
// (see manifest.mjs), so the published file is only usable unmodified -- which
// is the property the update tests are there to prove.

import { writeFileSync, mkdirSync, copyFileSync, existsSync, statSync } from 'node:fs'
import path from 'node:path'
import { readFileSync } from 'node:fs'
import { buildManifest, signManifest, loadPrivateKey, signaturePayload } from './manifest.mjs'
import { sha256File } from '../lib/hash.mjs'
import { identity } from '../lib/identity.mjs'

const args = process.argv.slice(2)
const flag = name => args.includes('--' + name)
const opt = (name, fallback) => {
  const i = args.indexOf('--' + name)
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback
}

const deb = opt('deb')
const out = opt('out')
if (!deb || !out) {
  console.error('usage: node packaging/update/publish.mjs --deb <path> --out <dir> [options]')
  process.exit(2)
}
if (!existsSync(deb)) {
  console.error('deb not found: ' + deb)
  process.exit(2)
}

const privPath = opt('private', path.join(process.env.ORDESSA_KEY_DIR || 'packaging/.keys', 'update-private.pem'))
if (!existsSync(privPath)) {
  console.error('private key not found: ' + privPath + '\ngenerate one with: node packaging/update/keygen.mjs packaging/.keys')
  process.exit(2)
}

const id = identity()
const version = opt('version', id.version)
const build = opt('build', id.build)
const urlBase = opt('url-base', 'http://127.0.0.1:8788')
const minDataSchema = parseInt(opt('min-data-schema', '1'), 10)
const notes = opt('notes', 'Controlled acceptance build.')

mkdirSync(out, { recursive: true })
const debName = path.basename(deb)
const dest = path.join(out, debName)
copyFileSync(deb, dest)

const manifest = buildManifest({
  version,
  build,
  debUrl: urlBase.replace(/\/$/, '') + '/' + debName,
  debSize: statSync(dest).size,
  debSha256: sha256File(dest),
  notes,
  minDataSchema,
})
manifest.latest.deb.signature = signManifest(manifest, loadPrivateKey(readFileSync(privPath, 'utf8')))

writeFileSync(path.join(out, 'update-manifest.json'), JSON.stringify(manifest, null, 2) + '\n')

console.log(JSON.stringify({
  out,
  version,
  build,
  deb: dest,
  debSha256: manifest.latest.deb.sha256,
  debSize: manifest.latest.deb.size,
  minDataSchema,
  manifestUrl: urlBase.replace(/\/$/, '') + '/update-manifest.json',
  // Printed so the acceptance log records exactly what was signed.
  signedPayload: signaturePayload(manifest),
}, null, 2))
