// @vitest-environment jsdom
import { act, createElement, type ComponentType, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { OwnedResources, type PluginContext } from '@ordessa/extension-api'
import { F5InteractionToken, WorkbenchToken, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import createPlugin from '../src/entry'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => { for (const cleanup of cleanups.splice(0).reverse()) await cleanup() })

async function mount(element: ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanups.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}

it('provides the public InteractionService and renders stable notifications and progress in Workbench status', async () => {
  const scope = new OwnedResources()
  cleanups.push(() => scope.dispose())
  let component: ComponentType | undefined
  const workbench = {
    forScope: () => ({ addUI(item: { component: ComponentType }) { component = item.component; return scope.add({ isDisposed: false, dispose() {} }) } }),
  } as unknown as Workbench
  const plugin = createPlugin()
  expect(plugin.id).toBe('ordessa.workbench-interactions')
  expect(plugin.provides).toBe(F5InteractionToken)
  expect(plugin.requires).toContain(WorkbenchToken)
  const service = plugin.activate({ resources: scope, root: { mount: () => ({ isDisposed: false, dispose() {} }) } } as PluginContext, workbench)
  expect(component).toBeTypeOf('function')
  const container = await mount(createElement(component!))

  let notice!: ReturnType<typeof service.notify>
  let progress!: ReturnType<typeof service.progress>
  act(() => {
    notice = service.notify({ id: 'skills:refresh', severity: 'info', text: 'Reading resources' })
    service.notify({ id: 'skills:refresh', severity: 'warning', text: 'Still reading' })
    progress = service.progress({ id: 'skills:import', text: 'Transferring' })
    progress.update(0.5, 'Halfway')
  })

  expect(container.querySelectorAll('[data-interaction-id="skills:refresh"]')).toHaveLength(1)
  expect(container.querySelector('[data-interaction-id="skills:refresh"]')?.textContent).toContain('Still reading')
  expect(container.querySelector('[data-interaction-id="skills:import"]')?.textContent).toContain('Halfway')
  expect(container.querySelector('[data-interaction-id="skills:import"] progress')?.getAttribute('value')).toBe('0.5')

  act(() => { notice.close(); progress.close() })
  expect(container.querySelector('[data-interaction-id="skills:refresh"]')).toBeNull()
  expect(container.querySelector('[data-interaction-id="skills:import"]')).toBeNull()
})
