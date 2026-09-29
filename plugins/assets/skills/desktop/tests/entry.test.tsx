// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { OwnedResources, type PluginContext, type ResourceScope } from '@ordessa/extension-api'
import type { Workbench, WorkbenchModule, WorkbenchOverlay, WorkbenchSettingsSection, View } from '@extensions/ordessa.contracts/contract.js'
import createSkillsPlugin, { SKILLS_MODULE_ID } from '../src/entry'
import { createChatContributions } from '@extensions/ordessa.chat-api/contract.js'
import { SKILLS_UNCONFIRMED_NOTICE_ID } from '../src/chatContribution'
import { SKILLS_CHAT_SOURCE_ID } from '../../contracts/src/chat'
import type { WireCaller } from '../src/gateway'
import { SKILLS_DETAIL_OVERLAY_ID, SKILLS_SETTINGS_SECTION_ID } from '../src/view'
import { fakeSkillsGateway, fakeWorkspaces } from './fakes'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

interface Harness {
  workbench: Workbench
  views: View[]
  modules: WorkbenchModule[]
  overlays: WorkbenchOverlay[]
  sections: WorkbenchSettingsSection[]
  opened: string[]
  disposals: string[]
  scope: OwnedResources
}

/** A Workbench that behaves like the platform contract: registrations are
 * scope-owned, and a module's home view must be a registered main-region view. */
function fakeWorkbench(options: { composition?: boolean } = {}): Harness {
  const harness: Harness = {
    views: [], modules: [], overlays: [], sections: [], opened: [], disposals: [],
    scope: new OwnedResources(),
    workbench: null as unknown as Workbench,
  }
  // Every handle is added to the caller's scope, exactly as the platform
  // registry does: registration is scope-owned, not global.
  const track = (label: string) => harness.scope.add({
    isDisposed: false,
    dispose() { harness.disposals.push(label) },
  })
  const composition = options.composition === false ? undefined : {
    forScope: () => ({
      addModule: (module: WorkbenchModule) => { harness.modules.push(module); return track(`module:${module.id}`) },
      addOverlay: (overlay: WorkbenchOverlay) => { harness.overlays.push(overlay); return track(`overlay:${overlay.id}`) },
      addSettingsSection: (section: WorkbenchSettingsSection) => { harness.sections.push(section); return track(`section:${section.id}`) },
    }),
    activateModule: (id: string) => {
      const module = harness.modules.find(item => item.id === id)
      if (!module) throw Error(`Module unavailable: ${id}`)
      const home = harness.views.find(view => view.id === module.homeViewId)
      if (!home || home.presentation !== 'region' || home.region !== 'main') {
        throw Error(`Module "${id}" home view must be a main-region view: ${module.homeViewId}`)
      }
    },
    openOverlay: (id: string) => { harness.opened.push(id); return track(`open:${id}`) },
    openSettings: (id?: string) => { harness.opened.push(`settings:${id ?? ''}`) },
  }
  harness.workbench = {
    forScope: () => ({
      addView: view => { harness.views.push(view); return track(`view:${view.id}`) },
      addUI: () => track('ui'),
    }),
    open: () => {},
    close: () => {},
    composition,
  }
  return harness
}

const context = (resources: ResourceScope): PluginContext => ({
  root: { mount: () => ({ isDisposed: false, dispose() {} }) },
  resources,
})

const dependencies = () => ({
  gateway: fakeSkillsGateway().gateway,
  workspaces: fakeWorkspaces([]).port,
})

let cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

async function mount(element: React.ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}

describe('ordessa.skills registration', () => {
  it('contributes a settings section, a module with a valid main home view, and a dialog overlay', async () => {
    const harness = fakeWorkbench()
    const disposables: { dispose(): void }[] = []
    const plugin = createSkillsPlugin(dependencies())
    expect(plugin.id).toBe(SKILLS_MODULE_ID)
    expect(plugin.requires.length).toBe(1)
    await act(async () => {
      disposables.push(plugin.activate(context(harness.scope), harness.workbench) as unknown as { dispose(): void })
    })
    expect(disposables).toHaveLength(1)
    // The section the page is reached from (Workbench owns the settings page).
    expect(harness.sections.map(section => section.id)).toEqual([SKILLS_SETTINGS_SECTION_ID])
    expect(harness.sections[0].title).toBe('Skills')
    // The module entry, whose default views satisfy the platform's own check.
    expect(harness.modules.map(module => module.id)).toEqual([SKILLS_MODULE_ID])
    expect(() => harness.workbench.composition?.activateModule(SKILLS_MODULE_ID)).not.toThrow()
    // The detail surface is contributor-owned, dismissed by the platform.
    expect(harness.overlays.map(overlay => [overlay.id, overlay.presentation])).toEqual([[SKILLS_DETAIL_OVERLAY_ID, 'dialog']])
    const overlayContainer = await mount(<div>{actOverlay(harness)}</div>)
    expect(overlayContainer.textContent).toContain('只读预览')
    // Registrations are scope-owned: closing the extension scope disposes them.
    await act(async () => { harness.scope.dispose() })
    for (const label of ['module:ordessa.skills', 'overlay:ordessa.skills.detail', 'section:ordessa.skills', 'view:ordessa.skills.home']) {
      expect(harness.disposals, label).toContain(label)
    }
    void disposables
  })

  it('refuses a Workbench without composition support instead of substituting legacy navigation', async () => {
    const harness = fakeWorkbench({ composition: false })
    const plugin = createSkillsPlugin(dependencies())
    expect(() => plugin.activate(context(harness.scope), harness.workbench))
      .toThrow('requires a Workbench with composition support')
    expect(harness.sections).toEqual([])
  })

  it('refuses to mount without the skills.* transport instead of showing an empty library', async () => {
    const harness = fakeWorkbench()
    // This is what the host hands the factory: the extension-api namespace,
    // which carries no gateway. Activation must say so loudly (C0 seam).
    const plugin = createSkillsPlugin({})
    expect(() => plugin.activate(context(harness.scope), harness.workbench))
      .toThrow('needs a skills.* gateway and the Workspace project list')
    expect(harness.sections).toEqual([])
    expect(harness.modules).toEqual([])
  })

  it('the contributed section renders the three areas through the public seams only', async () => {
    const harness = fakeWorkbench()
    const plugin = createSkillsPlugin(dependencies())
    await act(async () => { plugin.activate(context(harness.scope), harness.workbench) })
    const Section = harness.sections[0].component
    const container = await mount(<Section />)
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    for (const testId of ['skills-library', 'default-assignments', 'project-assignments', 'native-discovery']) {
      expect(container.querySelector(`[data-testid="${testId}"]`), testId).not.toBeNull()
    }
    // No global Assets super-navigation was invented (ux.md §Settings).
    expect(container.querySelectorAll('[data-region]').length).toBe(0)
  })

  it('registers the chat source on the REAL wire-backed snapshot port when a wire caller is provided', async () => {
    const harness = fakeWorkbench()
    const chat = createChatContributions()
    const wire: WireCaller = {
      async call(method: string) {
        if (method === 'skills.resolve') {
          return {
            target: { projectId: null, harnessId: 'pi', profileId: null, sessionRef: 'session:c1|-|s1', runtimeGeneration: 7 },
            serverScope: 'scope:local',
            resolvedSkills: [{
              assetId: 'alpha', revision: 3, nativeName: 'alpha-doc', description: '处理 PDF', treeDigest: null,
              originScope: 'public', originOwner: null,
              selectedBy: { layer: 'user_global_any', scopeKind: 'user_global', scopeId: '', harnessId: null, rowVersion: 2 },
              excludedBy: null, layerDecisions: [], capabilityEvidence: { effect: 'selected' },
            }],
            excludedSkills: [], diagnostics: [], assignmentRevisions: {}, profileRevision: null,
          }
        }
        // `service.py invoke_descriptor`: today every brand answers unknown/browse-only.
        return { harnessId: 'pi', invocation: 'unknown', browseOnly: true, reason: 'no verified route' }
      },
    }
    const plugin = createSkillsPlugin({ ...dependencies(), chat, wire })
    await act(async () => { plugin.activate(context(harness.scope), harness.workbench) })
    const view = chat.queryInputSources({
      location: { kind: 'session', connectionId: 'c1', sessionId: 's1', harnessId: 'pi', contextRevision: 1 },
      query: '', surface: 'plus', signal: new AbortController().signal,
    })
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
    const rows = view.getSnapshot().find(item => item.source.id === SKILLS_CHAT_SOURCE_ID)?.entries ?? []
    // The panel paints the backend row (no test fake crossed the entry seam).
    expect(rows.map(row => row.id)).toEqual(['ordessa.skills:alpha:public'])
    expect(rows[0]!.description).toContain('处理 PDF')
  })

  it('chat without any wire gateway stays 未确认/待解析 through the entry seam, never empty-success', async () => {
    const harness = fakeWorkbench()
    const chat = createChatContributions()
    const plugin = createSkillsPlugin({ ...dependencies(), chat })
    await act(async () => { plugin.activate(context(harness.scope), harness.workbench) })
    const view = chat.queryInputSources({
      location: { kind: 'session', connectionId: 'c1', sessionId: 's1', harnessId: 'pi', contextRevision: 1 },
      query: '', surface: 'slash', signal: new AbortController().signal,
    })
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
    const rows = view.getSnapshot().find(item => item.source.id === SKILLS_CHAT_SOURCE_ID)?.entries ?? []
    expect(rows.map(row => row.id)).toEqual([SKILLS_UNCONFIRMED_NOTICE_ID])
    expect(rows[0]!.description).toContain('未确认')
  })
})

function actOverlay(harness: Harness) {
  const overlay = harness.overlays.find(item => item.id === SKILLS_DETAIL_OVERLAY_ID)!
  const Component = overlay.component
  return <Component close={() => {}} />
}
