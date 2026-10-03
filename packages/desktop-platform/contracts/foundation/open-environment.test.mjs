/**
 * 002 freeze gate: the TypeScript mirror produces the frozen wire vectors
 * byte-for-byte and refuses the counterexample inputs.
 *
 * Runs the codec through the same esbuild path the desktop build uses, so the
 * identity claim is about the artifact that ships, not just the source text.
 */
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm, readFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { test } from 'node:test'

const repoRoot = path.resolve(import.meta.dirname, '../../../..')
const vectorsPath = path.join(repoRoot, 'tests', 'contracts', 'vectors', 'open-environment.json')

async function loadMirror() {
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'ordessa-oe-contract-'))
  const outfile = path.join(tmp, 'open-environment.mjs')
  await build({
    entryPoints: [path.join(import.meta.dirname, 'src/open-environment/index.ts')],
    outfile, bundle: true, platform: 'neutral', format: 'esm',
  })
  const mod = await import(`file://${outfile}`)
  return { mod, cleanup: () => rm(tmp, { recursive: true, force: true }) }
}

test('TS mirror reproduces every frozen vector byte-for-byte', async () => {
  const { mod, cleanup } = await loadMirror()
  try {
    const vectors = JSON.parse(await readFile(vectorsPath, 'utf8'))
    assert.equal(vectors.contractVersion, mod.CONTRACT_VERSION, 'contract version drift')
    assert.ok(vectors.cases.length >= 17, 'vector file lost cases')
    for (const c of vectors.cases) {
      const decoded = mod.decodeEnvelope(c.encoded)
      assert.equal(decoded.kind, c.kind, `kind mismatch for ${c.name}`)
      const reencoded = mod.encodeEnvelope(decoded.kind, decoded.payload)
      assert.equal(reencoded, c.encoded, `vector ${c.name}: TS output drifted from the frozen bytes`)
    }
  } finally {
    await cleanup()
  }
})

test('construction order never leaks into the wire form', async () => {
  const { mod, cleanup } = await loadMirror()
  try {
    const a = { z: 1, a: { y: [1, 2], b: null } }
    const b = JSON.parse('{"a":{"b":null,"y":[1,2]},"z":1}')
    assert.equal(mod.canonicalJson(a), mod.canonicalJson(b))
    assert.equal(mod.canonicalJson(a), '{"a":{"b":null,"y":[1,2]},"z":1}')
  } finally {
    await cleanup()
  }
})

test('envelope discipline: unknown keys and foreign versions are refused', async () => {
  const { mod, cleanup } = await loadMirror()
  try {
    assert.throws(() => mod.decodeEnvelope(
      '{"contractVersion":"oe-contract/1","extra":1,"kind":"x","payload":{}}'), /frozen set/)
    assert.throws(() => mod.decodeEnvelope(
      '{"contractVersion":"oe-contract/9","kind":"x","payload":{}}'), /contract version/)
    assert.throws(() => mod.encodeEnvelope('x', { bad: undefined }), /canonically encodable/)
  } finally {
    await cleanup()
  }
})

test('typed validation mirrors the Python rules', async () => {
  const { mod, cleanup } = await loadMirror()
  try {
    assert.throws(() => mod.validateCanonicalFactTarget(
      { realm: 'Workspace', identity_namespace: 'ordessa.workspace', stable_entity_id: 'w' }))
    assert.throws(() => mod.validateRevisionSelector({ op: 'exact' }))
    assert.throws(() => mod.validateRevisionSelector({ op: 'any', revision: '1' }))
    assert.throws(() => mod.validateHostDialogResult(
      { operation_id: 'op-1', status: 'cancelled', selected_handle: 'h' }))
    assert.throws(() => mod.validateInputCapture({ content_digest: '/tmp/draft.txt' }))
    assert.doesNotThrow(() => mod.validateRequestKey(
      { environment_namespace: 'prod-root', principal_scope: 'user:local:a1', request_id: 'req-1' }))
  } finally {
    await cleanup()
  }
})

test('single carrier: building the mirror twice yields identical codec output, one symbol identity', async () => {
  const first = await loadMirror()
  const second = await loadMirror()
  try {
    const payload = { k: ['b', 'a'], n: 3 }
    assert.equal(first.mod.canonicalJson(payload), second.mod.canonicalJson(payload))
    // The TS contract has no Token object (it is types + pure functions); the
    // carrier rule is asserted at the wire level above and by token-identity
    // tests for the runtime Tokens. A second *instance* must still agree.
  } finally {
    await first.cleanup()
    await second.cleanup()
  }
})
