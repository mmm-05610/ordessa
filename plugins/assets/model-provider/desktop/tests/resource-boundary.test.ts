import { expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { OwnedResources } from '@ordessa/extension-api'
import { F5InteractionToken, WorkbenchToken, WirePortToken, type Workbench, type WirePort } from '@extensions/ordessa.contracts/contract.js'
import { profileFacetEditorKey } from '@extensions/ordessa.profile-api/contract.js'
import { createUiComponentsService } from '../../../../packages/frontend/ui-components/src/index'
import createProductPlugin from '../src/entry'
import createProfileAdapter from '../../profile-contribution/src/entry'
import { createModelProviderService } from '../src/service'

it('the real Model product refuses a missing public interaction provider', () => {
  const resources = new OwnedResources()
  const wire = { ready: true, scope: 'controlled:server', call: async () => ({ kind: 'Accepted', requestId: 'list', result: { items: [] } }) } as WirePort
  const workbench = {} as Workbench
  const plugin = createProductPlugin()
  expect(plugin.requires).toEqual([WorkbenchToken, WirePortToken, F5InteractionToken])
  expect(() => plugin.activate({ resources } as never, workbench, wire)).toThrow('MODEL_PROVIDER_INTERACTION_MISSING')
  resources.dispose()
})

it('the optional Profile adapter retains product selection and unloads its own registration', () => {
  const adapterScope = new OwnedResources(), consumerScope = new OwnedResources()
  const key = profileFacetEditorKey('assets.model-provider')
  const ui = createUiComponentsService([{ componentId: key.id, major: key.major, providerId: 'ordessa.model-provider' }])
  const domain = createModelProviderService(async () => ({ items: [], nextCursor: null }))
  const binding = ui.uiComponents.forScope(consumerScope).bind(key, { required: true })
  expect(binding.getSnapshot().status).toBe('missing')
  createProfileAdapter().activate({ resources: adapterScope } as never, domain, ui.uiComponents)
  expect(binding.getSnapshot()).toMatchObject({ status: 'ready', providerId: 'ordessa.model-provider' })
  adapterScope.dispose()
  expect(binding.getSnapshot()).toMatchObject({ status: 'missing', reason: 'provider-unavailable' })
  consumerScope.dispose(); ui.dispose()
})

it('all admitted Model core source files have no Profile import, while the original product selection survives', () => {
  const root = new URL('../src/', import.meta.url)
  for (const name of readdirSync(root)) {
    if (!/\.tsx?$/.test(name)) continue
    expect(readFileSync(new URL(name, root), 'utf8'), name).not.toMatch(/(?:from|import\s*\()\s*['"][^'"]*(?:profile-api|profile-editor)/)
  }
  const product = JSON.parse(readFileSync(new URL('../../../../products/desktop/extensions.json', import.meta.url), 'utf8'))
  expect(product.enabled).toContain('ordessa.model-provider-profile')
  expect(product.config['ordessa.ui-components']).toContainEqual({ componentId: 'ordessa.profile.editor:assets.model-provider', major: 1, providerId: 'ordessa.model-provider' })
})
