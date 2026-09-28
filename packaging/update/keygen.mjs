// Generate an Ed25519 key pair for the update channel (PC-08).
//
//   node packaging/update/keygen.mjs <output-dir>
//
// Writes <dir>/update-private.pem and <dir>/update-pubkey. The public half is
// what gets embedded in the package; the private half must never enter the
// repository or the build tree -- it belongs on the release machine's secret
// store. This script refuses to overwrite an existing private key, because
// silently regenerating one silently invalidates every installed client.

import { writeFileSync, mkdirSync, existsSync, chmodSync } from 'node:fs'
import path from 'node:path'
import { generateKeyPair } from './manifest.mjs'

const dir = process.argv[2]
if (!dir) {
  console.error('usage: node packaging/update/keygen.mjs <output-dir>')
  process.exit(2)
}
const priv = path.join(dir, 'update-private.pem')
const pub = path.join(dir, 'update-pubkey')

mkdirSync(dir, { recursive: true })
if (existsSync(priv)) {
  // Overwriting would orphan every already-installed client, which cannot
  // verify a manifest signed by the new key.
  console.error('refusing to overwrite existing private key: ' + priv)
  process.exit(1)
}

const { publicKeyPem, privateKeyPem } = generateKeyPair()
writeFileSync(priv, privateKeyPem, { mode: 0o600 })
chmodSync(priv, 0o600)
writeFileSync(pub, publicKeyPem)

console.log(JSON.stringify({
  private_key: priv,
  public_key: pub,
  note: 'Keep the private key off this machine and out of the repository.',
}, null, 2))
