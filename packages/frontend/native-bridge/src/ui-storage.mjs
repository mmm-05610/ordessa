/** Host-only file adapter. Every writer/deleter locks the same record on disk.
 * Lock absence/timeout never authorizes stealing another writer's lock. */
import { mkdir, readFile, open, rename, unlink, rmdir } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { createHash, randomUUID } from 'node:crypto'

export function createFileUiAdapter(root, { lockTimeoutMs = 2000 } = {}) {
  const directory = resolve(root)
  const recordPath = (namespace, key) => join(directory,
    createHash('sha256').update(JSON.stringify([namespace, key])).digest('hex') + '.json')
  async function read(namespace, key) {
    try {
      const record = JSON.parse(await readFile(recordPath(namespace, key), 'utf8'))
      if (typeof record.revision !== 'string' || !Number.isInteger(record.schemaVersion)
          || !Object.hasOwn(record, 'value')) throw new Error('UI_STORAGE_CORRUPT')
      return record
    } catch (error) { if (error.code === 'ENOENT') return undefined; throw error }
  }
  async function locked(namespace, key, action) {
    await mkdir(directory, { recursive: true, mode: 0o700 })
    const path = recordPath(namespace, key)
    const lock = path + '.lock'
    const deadline = Date.now() + lockTimeoutMs
    while (true) {
      try { await mkdir(lock, { mode: 0o700 }); break }
      catch (error) {
        if (error.code !== 'EEXIST') throw error
        if (Date.now() >= deadline) throw new Error('UI_STORAGE_BUSY: lock ownership is unresolved')
        await new Promise(done => setTimeout(done, 5))
      }
    }
    try { return await action(path) } finally { await rmdir(lock) }
  }
  return {
    supportsAbsentCompareAndSwap: /** @type {true} */ (true),
    read,
    compareAndSwap(namespace, key, expectedRevision, input) {
      // Capture before awaits: consumers cannot change bytes during persistence.
      const captured = JSON.parse(JSON.stringify(input))
      return locked(namespace, key, async path => {
        const previous = await read(namespace, key)
        if (expectedRevision === null ? previous !== undefined
          : expectedRevision !== undefined && previous?.revision !== expectedRevision)
          return { status: 'conflict' }
        const revision = randomUUID()
        const temporary = path + '.' + revision + '.tmp'
        const handle = await open(temporary, 'wx', 0o600)
        try {
          await handle.writeFile(JSON.stringify({ ...captured, revision }))
          await handle.sync()
        } finally { await handle.close() }
        try {
          await rename(temporary, path)
          const dirHandle = await open(directory, 'r')
          try { await dirHandle.sync() } finally { await dirHandle.close() }
        } finally { await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error }) }
        return { status: 'written', revision }
      })
    },
    remove(namespace, key) {
      return locked(namespace, key, path => unlink(path).catch(error => {
        if (error.code !== 'ENOENT') throw error
      }))
    },
  }
}
