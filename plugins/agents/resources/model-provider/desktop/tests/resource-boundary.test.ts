import { expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { OwnedResources } from '@ordessa/extension-api'
import { F5InteractionToken, WorkbenchToken, WirePortToken, type Workbench, type WirePort } from '@extensions/ordessa.contracts/contract.js'
import { createUiComponentsService } from '../../../../../../packages/interfaces/channels/workbench/extension-runtime/ui-components/src/index'
import createProductPlugin from '../src/entry'

it('the real Model product refuses a missing public interaction provider', () => {
  const resources = new OwnedResources()
  const wire = { ready: true, scope: 'controlled:server', call: async () => ({ kind: 'Accepted', requestId: 'list', result: { items: [] } }) } as WirePort
  const workbench = {} as Workbench
  const plugin = createProductPlugin()
  expect(plugin.requires).toEqual([WorkbenchToken, WirePortToken, F5InteractionToken])
  expect(() => plugin.activate({ resources } as never, workbench, wire)).toThrow('MODEL_PROVIDER_INTERACTION_MISSING')
  resources.dispose()
})

it('all admitted Model core source files have no Profile import, and retired Profile contributions are absent', () => {
  const root = new URL('../src/', import.meta.url)
  for (const name of readdirSync(root)) {
    if (!/\.tsx?$/.test(name)) continue
    expect(readFileSync(new URL(name, root), 'utf8'), name).not.toMatch(/(?:from|import\s*\()\s*['"][^'"]*(?:profile-api|profile-editor)/)
  }
  const product = JSON.parse(readFileSync(new URL('../../../../../apps/desktop/packaging/product/extensions.json', import.meta.url), 'utf8'))
  expect(product.enabled).not.toContain('ordessa.model-provider-profile')
  expect(product.enabled).not.toContain('ordessa.profile-chat')
  expect(product.config['ordessa.ui-components']).not.toContainEqual(expect.objectContaining({ providerId: 'ordessa.model-provider-profile' }))
})
