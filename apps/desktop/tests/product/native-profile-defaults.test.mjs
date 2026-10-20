import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('desktop keeps the carrier id while exposing only the read-only Agent catalog consumer', async () => {
  const product = JSON.parse(await readFile(new URL('../extensions.json', import.meta.url), 'utf8'))
  assert.ok(product.enabled.includes('ordessa.profile-api'))
  assert.ok(product.enabled.includes('ordessa.profile-frontend'))
  for (const retired of ['ordessa.profile-chat', 'ordessa.model-provider-profile'])
    assert.ok(!product.enabled.includes(retired), `${retired} must not be assembled`)
  const components = product.config['ordessa.ui-components'] ?? []
  assert.ok(!components.some(item => /profile\.(picker|editor)/.test(item.componentId)))

  const token = await readFile(new URL('../../../plugins/agents/profiles/ui/api/src/token.ts', import.meta.url), 'utf8')
  const client = await readFile(new URL('../../../plugins/agents/profiles/ui/frontend/src/wire-client.ts', import.meta.url), 'utf8')
  const manager = await readFile(new URL('../../../plugins/agents/profiles/ui/frontend/src/connected-manager.tsx', import.meta.url), 'utf8')
  assert.ok(token.includes('ordessa.agent-profile-catalog.v1'))
  for (const method of ['agents.capabilities', 'agents.profiles.list', 'agents.profiles.readEntry', 'agents.profiles.read'])
    assert.ok(client.includes(method), `missing read-only core method ${method}`)
  assert.ok(client.includes('supports.profileCatalog !== true'))
  assert.ok(client.includes('profileRef: parsed'), 'manifest reads must carry the exact ProfileRef')
  assert.ok(!/profiles\.v2|agent\.config\.(?:read|submitOperation)|chooseForSession/.test(client + manager))
  assert.ok(manager.includes('创建、编辑、归档、会话选择与配置应用目前不可用。'))
})
