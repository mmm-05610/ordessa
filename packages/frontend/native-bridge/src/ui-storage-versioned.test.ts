import { describe, expect, it } from 'vitest'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawn } from 'node:child_process'
import { createFileUiAdapter } from './ui-storage.mjs'

function child(root: string, expectedRevision: string | null, width: number) {
  const entry = new URL('./ui-storage.mjs', import.meta.url).href
  return new Promise<any>((resolve, reject) => {
    const process = spawn(globalThis.process.execPath, ['--input-type=module', '-e',
      `import {createFileUiAdapter} from ${JSON.stringify(entry)}; const a=createFileUiAdapter(${JSON.stringify(root)}); console.log(JSON.stringify(await a.compareAndSwap('fixture','layout',${JSON.stringify(expectedRevision)},{schemaVersion:1,value:{width:${width}}})));`],
      { cwd: tmpdir(), env: { PATH: globalThis.process.env.PATH! } })
    let output = ''; let error = ''
    process.stdout.on('data', chunk => { output += chunk })
    process.stderr.on('data', chunk => { error += chunk })
    process.on('error', reject)
    process.on('close', code => code === 0 ? resolve(JSON.parse(output)) : reject(new Error(error)))
  })
}

describe('versioned file UI CAS adapter', () => {
  it('two independent OS processes race an absent version: exactly one writes', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ordessa-ui-if-absent-'))
    try {
      const adapter = createFileUiAdapter(root)
      const answers = await Promise.all([child(root, null, 20), child(root, null, 30)])
      expect(answers.map(x => x.status).sort()).toEqual(['conflict', 'written'])
      const winner = answers.find(x => x.status === 'written')
      expect(typeof winner.revision).toBe('string')
      const stored = await adapter.read('fixture', 'layout')
      expect(stored!.revision).toBe(winner.revision)
      expect([20, 30]).toContain(stored!.value.width)
    } finally { await rm(root, { recursive: true, force: true }) }
  })

  it('two independent OS processes racing an existing adapter revision still have one winner', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ordessa-ui-revision-'))
    try {
      const adapter = createFileUiAdapter(root)
      const base = await adapter.compareAndSwap('fixture', 'layout', undefined, { schemaVersion: 1, value: { width: 10 } })
      expect(base.status).toBe('written')
      const capturedRevision = base.revision!
      const answers = await Promise.all([child(root, capturedRevision, 20), child(root, capturedRevision, 30)])
      expect(answers.map(x => x.status).sort()).toEqual(['conflict', 'written'])
      const stored = await createFileUiAdapter(root).read('fixture', 'layout')
      expect(stored!.revision).toBe(answers.find(x => x.status === 'written').revision)
      expect(stored!.revision).not.toBe(capturedRevision)
      expect([20, 30]).toContain(stored!.value.width)
    } finally { await rm(root, { recursive: true, force: true }) }
  })
})
