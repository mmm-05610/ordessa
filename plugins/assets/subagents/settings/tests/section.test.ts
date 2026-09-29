/**
 * The Settings contribution, exercised against the **real** Workbench registry
 * (`packages/workbench/src/model.ts` + `packages/workbench/shared/registry.ts`),
 * not a stand-in: section shape, duplicate-registration impossibility, unload
 * semantics and `openSettings` location all run through the host's own code.
 */
import { OwnedResources } from '@ordessa/extension-api'
import { describe, expect, it } from 'vitest'
import { createWorkbench } from '../../../../../packages/workbench/src/model'
import { SETTINGS_OVERLAY_ID } from '../../../../../packages/workbench/src/model'
import {
  addSettingsSection, createSettingsSection, installSubagentSettings, SETTINGS_SECTION_ID,
  SETTINGS_SECTION_ORDER, SETTINGS_SECTION_TITLE, SettingsRegistrationError,
} from '../src/section'
import { createSettingsStore } from '../src/store'
import { TARGET } from './fixtures'

function workbench() {
  const lifetime = new OwnedResources()
  const model = createWorkbench(lifetime)
  return { lifetime, model }
}

describe('the section object is a real WorkbenchSettingsSection', () => {
  it('carries id / title / order / component exactly as the contract declares', () => {
    const store = createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' })
    const section = createSettingsSection({ store })
    expect(section.id).toBe(SETTINGS_SECTION_ID)
    expect(section.id).toBe('assets.native-subagents.library')
    expect(section.title).toBe(SETTINGS_SECTION_TITLE)
    expect(section.order).toBe(SETTINGS_SECTION_ORDER)
    expect(typeof section.component).toBe('function')
    // overriding title/order is allowed; the id is not
    const custom = createSettingsSection({ store, title: '其它标题', order: 1 })
    expect(custom.id).toBe(SETTINGS_SECTION_ID)
    expect(custom.title).toBe('其它标题')
    expect(custom.order).toBe(1)
  })
})

describe('registration through the public composition API', () => {
  it('appears in the host snapshot and is locatable via openSettings', () => {
    const { lifetime, model } = workbench()
    const scope = new OwnedResources()
    const installed = installSubagentSettings(model.composition, scope, { port: null, target: TARGET, viewerPrincipal: 'principal-1' })
    expect(model.sections.getSnapshot().map(s => s.id)).toEqual([SETTINGS_SECTION_ID])
    // the settings page is Workbench-owned; openSettings must accept this section id
    expect(() => model.composition.openSettings(SETTINGS_SECTION_ID)).not.toThrow()
    const stack = model.getOverlayStack()
    expect(stack.some(o => o.overlayId === SETTINGS_OVERLAY_ID && o.sectionId === SETTINGS_SECTION_ID)).toBe(true)
    expect(() => model.composition.openSettings('assets.native-subagents.nope')).toThrow(/unavailable/)
    scope.dispose()
    lifetime.dispose()
  })

  it('a duplicate live registration in the same scope is impossible (own guard, host error on top)', () => {
    const { lifetime, model } = workbench()
    const scope = new OwnedResources()
    const section = createSettingsSection({ store: createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' }) })
    const handle = addSettingsSection(model.composition, scope, section)
    expect(() => addSettingsSection(model.composition, scope, section)).toThrow(SettingsRegistrationError)
    // and the guard did not corrupt the registry: exactly one entry is live
    expect(model.sections.getSnapshot()).toHaveLength(1)
    handle.dispose()
    expect(() => addSettingsSection(model.composition, scope, section)).not.toThrow()
    scope.dispose()
    lifetime.dispose()
  })

  it('the host registry itself still refuses a cross-scope duplicate id', () => {
    const { lifetime, model } = workbench()
    const a = new OwnedResources()
    const b = new OwnedResources()
    const section = createSettingsSection({ store: createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' }) })
    addSettingsSection(model.composition, a, section)
    expect(() => addSettingsSection(model.composition, b, section)).toThrow(/Duplicate contribution/)
    expect(model.sections.getSnapshot()).toHaveLength(1)
    a.dispose()
    b.dispose()
    lifetime.dispose()
  })

  it('an empty id can never be registered at all (host validation)', () => {
    const { lifetime, model } = workbench()
    const scope = new OwnedResources()
    const store = createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' })
    const blank = { ...createSettingsSection({ store }), id: '  ' }
    expect(() => addSettingsSection(model.composition, scope, blank)).toThrow(/Contribution id is required/)
    scope.dispose()
    lifetime.dispose()
  })

  it('registering into a disposed scope fails explicitly, not silently', () => {
    const { lifetime, model } = workbench()
    const scope = new OwnedResources()
    scope.dispose()
    const section = createSettingsSection({ store: createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' }) })
    expect(() => addSettingsSection(model.composition, scope, section)).toThrow(SettingsRegistrationError)
    lifetime.dispose()
  })
})

describe('unload hides the contribution but keeps the data (§C2)', () => {
  it('disposing the handle removes only this section and never touches the store', () => {
    const { lifetime, model } = workbench()
    const scope = new OwnedResources()
    const store = createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' })
    const handle = addSettingsSection(model.composition, scope, createSettingsSection({ store }))

    store.dispatch({ type: 'draft/edit', field: 'roleBody', value: '未保存的正文' })
    store.dispatch({ type: 'filter/origin', filter: 'project' })
    const draftBefore = store.getState().draft
    const filterBefore = store.getState().originFilter

    expect(handle.isDisposed).toBe(false)
    handle.dispose()
    expect(handle.isDisposed).toBe(true)
    expect(model.sections.getSnapshot()).toHaveLength(0)
    // a second dispose is a no-op, and hiding did not delete anything
    expect(() => handle.dispose()).not.toThrow()
    expect(store.getState().draft).toEqual(draftBefore)
    expect(store.getState().originFilter).toBe(filterBefore)

    // the rest of the surface still works with this section gone
    expect(() => model.composition.openSettings()).not.toThrow()
    scope.dispose()
    lifetime.dispose()
  })

  it('scope disposal (extension unload) hides the section and keeps drafts', () => {
    const { lifetime, model } = workbench()
    const scope = new OwnedResources()
    const store = createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' })
    addSettingsSection(model.composition, scope, createSettingsSection({ store }))
    store.dispatch({ type: 'draft/edit', field: 'description', value: '未保存说明' })
    scope.dispose()
    expect(model.sections.getSnapshot()).toHaveLength(0)
    expect(store.getState().draft?.description).toBe('未保存说明')
    lifetime.dispose()
  })

  it('registering the same id again after unload works and shows one entry', () => {
    const { lifetime, model } = workbench()
    const scope = new OwnedResources()
    const store = createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' })
    const section = createSettingsSection({ store })
    const first = addSettingsSection(model.composition, scope, section)
    first.dispose()
    const second = addSettingsSection(model.composition, scope, section)
    expect(model.sections.getSnapshot()).toHaveLength(1)
    second.dispose()
    expect(model.sections.getSnapshot()).toHaveLength(0)
    scope.dispose()
    lifetime.dispose()
  })
})

describe('one missing contribution must not break other domains (FR11)', () => {
  it('a section that never registers leaves modules/overlays/settings intact', () => {
    const { lifetime, model } = workbench()
    const scope = new OwnedResources()
    const views = model.service.forScope(scope)
    views.addView({ id: 'home', title: 'Home', presentation: 'region', region: 'main', component: () => null })
    model.composition.forScope(scope).addModule({ id: 'm', title: 'M', homeViewId: 'home' })
    model.composition.activateModule('m')
    expect(model.getSelection().main).toBe('home')
    expect(() => model.composition.openSettings()).not.toThrow()
    expect(model.sections.getSnapshot()).toHaveLength(0)
    scope.dispose()
    lifetime.dispose()
  })
})
