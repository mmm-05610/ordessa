import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { launchSmoke } from '../support/launch-smoke.mjs'

// FC-0034 item 2 / FC-0035: one fixed MODULAR_USER_DATA across two real Electron
// processes proves the non-secret project selection survives restart and that a
// changed serverId never restores the previous key. Fixture values only, no tokens.
const PROBE = { MODULAR_STORAGE_RESTART_SMOKE: '1' }
const payload = JSON.stringify({ workspaceId: 'ws-fixture-A', normalizedPath: '/fixture/project-A' })
const home = await mkdtemp(path.join(tmpdir(), 'ordessa-restart-'))
const fresh = await mkdtemp(path.join(tmpdir(), 'ordessa-restart-fresh-'))
try {
  const cold = await launchSmoke(fresh, PROBE)
  const write = await launchSmoke(home, { ...PROBE, ORDESSA_SMOKE_STORAGE_MODE: 'write' })
  const reboot = await launchSmoke(home, PROBE)
  const checks = {
    coldEmpty: cold.storage.valueA === null && cold.storage.valueB === null,
    wrote: write.storage.wrote === 'ordessa.cp-project|http://127.0.0.1:4471|srv-A' && write.storage.echo === payload,
    survivedRestart: reboot.storage.valueA === payload,
    serverIdIsolated: reboot.storage.valueB === null,
    noSecrets: !JSON.stringify([cold, write, reboot]).includes('token'),
  }
  console.log('STORAGE_RESTART ' + JSON.stringify(checks))
  if (Object.values(checks).some(ok => !ok)) throw Error('storage restart fixture failed: ' + JSON.stringify(checks))
} finally {
  await rm(home, { recursive: true, force: true })
  await rm(fresh, { recursive: true, force: true })
}
