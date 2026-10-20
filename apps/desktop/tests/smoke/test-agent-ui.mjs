import assert from 'node:assert/strict'
import { mkdtemp, mkdir, cp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchSmoke } from '../support/launch-smoke.mjs'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..')
const home = await mkdtemp(path.join(tmpdir(), 'ordessa-agent-ui-'))
try {
  await mkdir(path.join(home, 'extensions'))
  await cp(path.join(root, 'examples/dist/example.agent-ui'), path.join(home, 'extensions/example.agent-ui'), { recursive: true })
  await writeFile(path.join(home, 'extensions.json'), JSON.stringify({ enabled: ['ordessa.contracts', 'ordessa.commands', 'ordessa.workbench', 'example.agent-ui'] }))
  const result = await launchSmoke(home, { ORDESSA_EMPTY_HOST: '0', MODULAR_AGENT_SMOKE: '1', ...(process.env.MODULAR_SCREENSHOT ? { MODULAR_SCREENSHOT: process.env.MODULAR_SCREENSHOT } : {}) })
  assert.deepEqual(result.errors, [])
  assert.equal(result.pages.includes('Agent UI 验证'), true)
  assert.equal(Object.keys(result.agent).length, 9)
  for (const [name, passed] of Object.entries(result.agent)) assert.equal(passed, true, name)
  console.log(JSON.stringify(result, null, 2))
} finally { await rm(home, { recursive: true, force: true }) }
