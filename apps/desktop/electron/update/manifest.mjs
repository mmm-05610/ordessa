// Update manifest construction, signing and verification (C-09 §C1).
//
// The single most important property here is what the signature COVERS. Signing
// only the deb hash would let an attacker who controls the update channel
// repoint `deb.url` at a payload of their choosing, or raise `minDataSchema` to
// lock users out, while the hash still "verifies". So the signed payload is the
// serialised form of the key metadata:
//
//   {schemaVersion, channel, version, build, deb.url, deb.size, deb.sha256, minDataSchema}
//
// with a fixed key order and no incidental whitespace. Change ANY one of those
// and verification fails. `notes` is deliberately outside the payload: it is
// prose for humans and carries no authority.
//
// Ed25519 keys come from Node's crypto, so there is no dependency to keep
// current. The private key is only ever read at signing time on the release
// machine; the public key ships in the package.

import { createHash, createPrivateKey, createPublicKey, verify as verifySignature, sign as signBytes, generateKeyPairSync } from 'node:crypto'

// Fixed order, fixed shape. Adding a key here is a contract change: every
// already-installed client verifies with this function, so a new key must be
// added in a way that keeps old payloads verifiable.
export const SIGNED_FIELDS = [
  ['schemaVersion', m => m.schemaVersion],
  ['channel', m => m.channel],
  ['version', m => m.latest && m.latest.version],
  ['build', m => m.latest && m.latest.build],
  ['deb.url', m => m.latest && m.latest.deb && m.latest.deb.url],
  ['deb.size', m => m.latest && m.latest.deb && m.latest.deb.size],
  ['deb.sha256', m => m.latest && m.latest.deb && m.latest.deb.sha256],
  ['minDataSchema', m => m.latest && m.latest.minDataSchema],
]

// The canonical serialisation. Two structurally identical manifests must produce
// byte-identical payloads, or a legitimately signed manifest would fail its own
// verification after a round-trip through JSON.
export function signaturePayload(manifest) {
  return SIGNED_FIELDS.map(([key, get]) => JSON.stringify(key) + ':' + JSON.stringify(get(manifest) ?? null)).join('\n')
}

export function payloadDigest(manifest) {
  return createHash('sha256').update(signaturePayload(manifest), 'utf8').digest()
}

export function loadPrivateKey(pemOrPath) {
  return createPrivateKey(pemOrPath)
}

export function loadPublicKey(pem) {
  return createPublicKey(pem)
}

export function signManifest(manifest, privateKey) {
  return signBytes(null, payloadDigest(manifest), privateKey).toString('base64')
}

// Returns { ok, reason, remedy }. Never throws on a bad signature -- callers
// show the reason to the user, so it has to be a sentence they can act on.
export function verifyManifest(manifest, publicKey) {
  const signature = manifest && manifest.latest && manifest.latest.deb && manifest.latest.deb.signature
  if (!signature) {
    return {
      ok: false,
      reason: 'UPDATE_SIGNATURE_MISSING: the update manifest carries no signature.',
      remedy: 'Contact your administrator: the update source is not correctly configured.',
    }
  }
  let ok = false
  try {
    ok = verifySignature(null, payloadDigest(manifest), publicKey, Buffer.from(signature, 'base64'))
  } catch (err) {
    return {
      ok: false,
      reason: 'UPDATE_SIGNATURE_INVALID: the update signature could not be checked.',
      remedy: 'Do not install. Re-download the update, or contact your administrator.',
    }
  }
  if (!ok) {
    // Deliberately does not say WHICH field differs. Naming the field would
    // tell an attacker exactly which single byte to flip next.
    return {
      ok: false,
      reason: 'UPDATE_SIGNATURE_MISMATCH: the update manifest does not match its signature.',
      remedy: 'Refusing to install. The update may have been tampered with; contact your administrator.',
    }
  }
  return { ok: true }
}

export function generateKeyPair() {
  const { publicKey, privateKey } = generateKeyPairSync('ed25519')
  return {
    publicKeyPem: publicKey.export({ type: 'spki', format: 'pem' }).toString(),
    privateKeyPem: privateKey.export({ type: 'pkcs8', format: 'pem' }).toString(),
  }
}

export function buildManifest({ version, build, debUrl, debSize, debSha256, notes = '', minDataSchema = 1, channel = 'stable', schemaVersion = 1 }) {
  return {
    schemaVersion,
    channel,
    latest: {
      version,
      build,
      deb: { url: debUrl, size: debSize, sha256: debSha256, signature: '' },
      notes,
      minDataSchema,
    },
  }
}
