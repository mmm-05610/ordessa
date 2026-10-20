import { describe, expect, it } from 'vitest'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawn } from 'node:child_process'
import { createFileUiAdapter } from './ui-storage.mjs'

function child(root: string, revision: string, width: number) {
  const entry = new URL('./ui-storage.mjs', import.meta.url).href
  return new Promise<any>((resolve, reject) => {
    const process = spawn(globalThis.process.execPath, ['--input-type=module', '-e',
      `import {createFileUiAdapter} from ${JSON.stringify(entry)}; const a=createFileUiAdapter(${JSON.stringify(root)}); console.log(JSON.stringify(await a.compareAndSwap('fixture','layout',${JSON.stringify(revision)},{schemaVersion:1,value:{width:${width}}})));`],
      { cwd: tmpdir(), env: { PATH: globalThis.process.env.PATH! } })
    let output = ''; let error = ''
    process.stdout.on('data', chunk => { output += chunk })
    process.stderr.on('data', chunk => { error += chunk })
    process.on('error', reject)
    process.on('close', code => code === 0 ? resolve(JSON.parse(output)) : reject(new Error(error)))
  })
}

describe('actual file UI CAS adapter', () => {
  it('two independent child clients race same revision: exactly one writes, survives restart', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ordessa-013-ui-'))
    try {
      const adapter = createFileUiAdapter(root)
      const base = await adapter.compareAndSwap('fixture', 'layout', undefined, { schemaVersion: 1, value: { width: 10 } })
      expect(base.status).toBe('written')
      const answers = await Promise.all([child(root, base.revision!, 20), child(root, base.revision!, 30)])
      expect(answers.map(x => x.status).sort()).toEqual(['conflict', 'written'])
      const reopened = createFileUiAdapter(root)
      const stored = await reopened.read('fixture', 'layout')
      expect(stored!.revision).toBe(answers.find(x => x.status === 'written').revision)
      expect(stored!.revision).not.toBe(base.revision)
      expect([20, 30]).toContain(stored!.value.width)
      expect(await reopened.read('other', 'layout')).toBeUndefined()
      await reopened.remove('fixture', 'layout')
      expect(await adapter.read('fixture', 'layout')).toBeUndefined()
      expect((await adapter.compareAndSwap('fixture', 'layout', stored!.revision, { schemaVersion:1,value:{} })).status).toBe('conflict')
    } finally { await rm(root, { recursive: true, force: true }) }
  })
})
