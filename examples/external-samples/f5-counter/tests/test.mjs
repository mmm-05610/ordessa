/**
 * F5 fixture #1 (counter) — node:test + esbuild build-then-import, the same
 * controlled fixture harness the contract freeze uses. The platform state
 * store is built from repo source alongside the fixture (see README:
 * "Test dependencies"); the fixture's declared runtime dependency is the
 * public platform package only.
 *
 * Counterexamples pinned (F5 §2): consumers hold no write face; a published
 * snapshot is deeply immutable; batch publishes exactly one complete
 * snapshot; a released consumer never fires again.
 */
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { test } from 'node:test'

const here = path.dirname(new URL(import.meta.url).pathname)

async function loadFixture() {
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'ordessa-f5-counter-'))
  const outfile = path.join(tmp, 'counter.mjs')
  await build({
    entryPoints: [path.join(here, '../src/counter.ts')],
    outfile, bundle: true, platform: 'neutral', format: 'esm',
  })
  const mod = await import(`file://${outfile}`)
  return { mod, cleanup: () => rm(tmp, { recursive: true, force: true }) }
}

test('owner writes, two consumers read the same identity-stable snapshot', async () => {
  const { mod, cleanup } = await loadFixture()
  try {
    const owner = new mod.CounterOwner()
    const count = mod.countConsumer(owner)
    const label = mod.labelConsumer(owner)
    const countListener = { calls: 0 }
    const labelListener = { calls: 0 }
    count.subscribe(() => countListener.calls++)
    label.subscribe(() => labelListener.calls++)

    const first = owner.reader().getSnapshot()
    owner.increment()
    const second = owner.reader().getSnapshot()
    assert.notEqual(second, first) // new snapshot object on change
    assert.equal(owner.reader().getSnapshot(), second) // stable identity
    assert.equal(count.get(), 1)
    assert.equal(label.get(), 'f5-counter')
    assert.equal(countListener.calls, 1)
    assert.equal(labelListener.calls, 0) // unrelated field: zero notify (F5 §2)
  } finally {
    await cleanup()
  }
})

test('counterexample: consumers hold no write face', async () => {
  const { mod, cleanup } = await loadFixture()
  try {
    const owner = new mod.CounterOwner()
    const reader = owner.reader()
    assert.equal('update' in reader, false)
    assert.equal('updateBatched' in reader, false)
  } finally {
    await cleanup()
  }
})

test('counterexample: published snapshots are deeply immutable', async () => {
  const { mod, cleanup } = await loadFixture()
  try {
    const owner = new mod.CounterOwner()
    owner.increment()
    const snap = owner.reader().getSnapshot()
    assert.throws(() => { snap.count = 99 })
    assert.throws(() => { snap.history.push('forged') })
  } finally {
    await cleanup()
  }
})

test('batched relabel+increment publishes exactly one complete snapshot', async () => {
  const { mod, cleanup } = await loadFixture()
  try {
    const owner = new mod.CounterOwner()
    const seen = []
    owner.reader().subscribe(() => seen.push(owner.reader().getSnapshot()))
    owner.relabelAndIncrement('renamed')
    assert.equal(seen.length, 1)
    assert.equal(seen[0].label, 'renamed')
    assert.equal(seen[0].count, 1) // both changes visible in the single publish
  } finally {
    await cleanup()
  }
})

test('a released consumer never fires again (scope exit)', async () => {
  const { mod, cleanup } = await loadFixture()
  try {
    const owner = new mod.CounterOwner()
    const count = mod.countConsumer(owner)
    let calls = 0
    const handle = count.subscribe(() => calls++)
    handle.release()
    handle.release() // idempotent
    owner.increment()
    assert.equal(calls, 0)
  } finally {
    await cleanup()
  }
})
