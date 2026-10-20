// @vitest-environment jsdom
import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { F5InteractionToken, WorkbenchToken, WirePortToken } from '@extensions/ordessa.contracts/contract.js'
import { ChatContributionsToken } from '@extensions/ordessa.chat-api/contract.js'
import type { f5 } from '@extensions/ordessa.contracts/contract.js'
import { default as createProductPlugin } from '../src/entry'
import { createSkillsModel } from '../src/model'
import { createInteractionModel } from '../src/task-integration'
import { fakeSkillsGateway, fakeWorkspaces } from './fakes'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => { for (const cleanup of cleanups.splice(0).reverse()) await cleanup() })

function fakeInteraction() {
  const notifications: Array<{ id?: string; severity: string; text: string }> = []
  const opened: Array<{ id?: string; text: string }> = []
  const closed: string[] = []
  const interaction = {
    notify(value: { id?: string; severity: 'info' | 'warning' | 'error'; text: string }) {
      notifications.push(value)
      return { id: value.id ?? 'notice', update: vi.fn(), close: () => closed.push(value.id ?? 'notice') }
    },
    progress(value: { id?: string; text: string }) {
      opened.push(value)
      return { id: value.id ?? 'progress', update: vi.fn(), requestCancel: vi.fn(), close: () => closed.push(value.id ?? 'progress') }
    },
    quickPick: vi.fn(), confirm: vi.fn(),
  } as unknown as f5.InteractionService
  return { interaction, notifications, opened, closed }
}

it('requires the public F5 service without acquiring a Chat dependency', () => {
  const plugin = createProductPlugin()
  expect(plugin.requires).toContain(WorkbenchToken)
  expect(plugin.requires).toContain(WirePortToken)
  expect(plugin.requires).toContain(F5InteractionToken)
  expect(plugin.requires).not.toContain(ChatContributionsToken)
})

it('wraps Skills refresh as a task and closes progress while notifying a real model error', async () => {
  const broken = fakeSkillsGateway({ fail: { catalogue: 'CATALOGUE_UNAVAILABLE' } })
  const scope = new OwnedResources()
  cleanups.push(() => scope.dispose())
  const fake = fakeInteraction()
  const businessModel = createSkillsModel(broken.gateway, fakeWorkspaces([]).port)
  const model = createInteractionModel(businessModel, scope, fake.interaction)
  // Drive refresh directly to isolate task lifecycle from React scheduling.
  await act(async () => { await model.refresh() })
  expect(fake.opened.map(item => item.id)).toContain('skills:refresh')
  expect(fake.closed).toContain('skills:refresh')
  expect(fake.notifications).toContainEqual(expect.objectContaining({ id: 'skills:refresh:error', severity: 'error', text: 'Error: CATALOGUE_UNAVAILABLE' }))
})
