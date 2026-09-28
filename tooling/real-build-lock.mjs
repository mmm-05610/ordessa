// Cross-process mutex around rebuilds of the SHARED real product output
// (products/desktop/dist + extensions.lock.json). Several guard files under
// packages/workbench/tests and products/desktop/tests build the real product at
// import time, and `node --test` runs files of one directory as parallel
// processes while a developer may run two directories at once, so without
// serialization two `tooling/build-all.mjs` runs would wipe/rebuild the same
// tree concurrently and other tests could scan a half-written dist.
// Locking is an atomic mkdir in the OS temp dir keyed by repo root (the repo
// tree itself stays untouched); a lock older than STALE_MS is treated as a
// crashed holder's leftover and broken.
import { mkdir, rm, stat } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import os from 'node:os'
import path from 'node:path'

const STALE_MS = 5 * 60 * 1000
const TIMEOUT_MS = 120 * 1000
const POLL_MS = 100

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

export function realBuildLockDir(repoRoot) {
  const key = createHash('sha256').update(repoRoot).digest('hex').slice(0, 16)
  return path.join(os.tmpdir(), `ordessa-real-build-${key}.lock`)
}

/** Acquire the exclusive real-product-build lock; resolves to a release() fn. */
export async function acquireRealBuildLock(repoRoot) {
  const lockDir = realBuildLockDir(repoRoot)
  const deadline = Date.now() + TIMEOUT_MS
  for (;;) {
    try {
      await mkdir(lockDir)
      let released = false
      return async () => { if (!released) { released = true; await rm(lockDir, { recursive: true, force: true }) } }
    } catch (error) {
      if (error.code !== 'EEXIST') throw error
      // The holder can release between our failed mkdir and this stat, so the stat
      // must tolerate ENOENT: a vanished lock simply means "try again", never a
      // reason to reject and let an unhandled error reach the test runner.
      let age = 0
      try {
        age = Date.now() - (await stat(lockDir)).mtimeMs
      } catch (statError) {
        if (statError.code !== 'ENOENT') throw statError
      }
      if (age > STALE_MS) { await rm(lockDir, { recursive: true, force: true }); continue }
      if (Date.now() > deadline) throw Error(`timed out after ${TIMEOUT_MS}ms waiting for the real product build lock at ${lockDir}`)
      await sleep(POLL_MS)
    }
  }
}
