/**
 * T008-03 gates: host surfaces present through the Workbench containers
 * (settings/overlay registration) while business values stay with their
 * owners, absent Workbench is an honest fallback, and host service
 * snapshots are identity-stable (uSES safe).
 */
import { describe, expect, it, vi } from 'vitest'

import { registerHostSurfaces } from '../renderer/host-workbench-registration'
import { buildHostServices } from '../renderer/host-services'

function fakeWorkbench() {
  const sections: string[] = []
  const overlays: string[] = []
  const disposed: string[] = []
  return {
    workbench: {
      composition: {
        forScope: () => ({
          addSettingsSection(section: { id: string }) {
            sections.push(section.id)
            return { dispose: () => disposed.push(`section:${section.id}`) }
          },
          addOverlay(overlay: { id: string }) {
            overlays.push(overlay.id)
            return { dispose: () => disposed.push(`overlay:${overlay.id}`) }
          },
        }),
      },
    } as never,
    sections,
    overlays,
    disposed,
  }
}

describe('host surface registration', () => {
  it('presents host settings and panels through the Workbench containers', () => {
    const wb = fakeWorkbench()
    const registration = registerHostSurfaces(wb.workbench, {
      settings: [{ id: 'host.data-root', title: 'Data root', component: null }] as never,
      overlays: [{ id: 'host.settings', title: 'Settings', component: null, presentation: 'page' }] as never,
    }, {} as never)
    expect(registration.presented).toBe(true)
    expect(wb.sections).toEqual(['host.data-root'])
    expect(wb.overlays).toEqual(['host.settings'])
    registration.release()
    expect(wb.disposed.sort()).toEqual(['overlay:host.settings', 'section:host.data-root'])
  })

  it('counterexample: an absent Workbench is honest fallback, never a fake container', () => {
    const registration = registerHostSurfaces(undefined, { settings: [], overlays: [] })
    expect(registration.presented).toBe(false)
    expect(registration.disposers).toEqual([])
  })

  it('release is idempotent and unregisters exactly what was registered', () => {
    const wb = fakeWorkbench()
    const registration = registerHostSurfaces(wb.workbench, {
      settings: [{ id: 'a', title: 'A', component: null }] as never,
      overlays: [],
    }, {} as never)
    registration.release()
    registration.release() // idempotent
    expect(wb.disposed).toEqual(['section:a'])
  })
})

describe('host service snapshots (T008-03)', () => {
  it('settings getSnapshot is identity-stable until a registration changes', () => {
    const services = buildHostServices()
    const first = services.settings.getSnapshot()
    expect(services.settings.getSnapshot()).toBe(first) // same frozen array
    const off = services.settings.register({ id: 's1', title: 'S1', component: null } as never)
    const second = services.settings.getSnapshot()
    expect(second).not.toBe(first) // changed list, new identity
    expect(services.settings.getSnapshot()).toBe(second) // stable again
    off()
    const third = services.settings.getSnapshot()
    expect(third).not.toBe(second)
    expect(third).toEqual(first) // same content as the empty start
  })

  it('diagnostics getSnapshot is identity-stable until a registration changes', () => {
    const services = buildHostServices()
    const first = services.diagnostics.getSnapshot()
    expect(services.diagnostics.getSnapshot()).toBe(first)
    const off = services.diagnostics.register({ collect: async () => ({}) } as never)
    expect(services.diagnostics.getSnapshot()).not.toBe(first)
    off()
  })
})
