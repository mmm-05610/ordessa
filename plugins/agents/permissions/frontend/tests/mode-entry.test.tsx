// T013: the per-brand mode entry for the Chat input area. The entry is built
// ONLY from a capability-attested per-pin answer; this tree exposes no such
// read surface (the permissions backend registers decide/query only, and the
// brand vocabulary in brand.py is keyed by brand name), so the shipped path is
// the honest refusal: nothing is listed unless the injected source attests it,
// and a brand name alone never produces a menu.
// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions } from '@extensions/ordessa.chat-api/contract.js'
import {
  ModeEntryKey, PermissionsModeEntry, createModeEntryContribution, resolveModeEntry,
} from '../src/mode-entry'
import type { PermissionsModeCapabilitySource, PermissionsModePin } from '../src/mode-entry'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const roots: Root[] = []
afterEach(async () => {
  for (const root of roots.splice(0)) await act(async () => { root.unmount() })
})

const pin: PermissionsModePin = { harnessId: 'claude-code', nativeVersion: '2.0.0' }

const source = (answer: Awaited<ReturnType<PermissionsModeCapabilitySource['modesForPin']>>): PermissionsModeCapabilitySource => ({
  modesForPin: async () => answer,
})

async function mount(element: React.ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  roots.push(root)
  await act(async () => { root.render(element) })
  return container
}

describe('the entry is capability-driven, never brand-name-driven (US4, ux.md §Chat)', () => {
  it('no capability data for a real brand pin => no menu is invented', async () => {
    const model = await resolveModeEntry(pin, source({ status: 'no-capability-data' }))
    expect(model.visible).toBe(false)
    const container = await mount(<PermissionsModeEntry pin={pin} source={source({ status: 'no-capability-data' })} />)
    expect(container.querySelector('select')).toBeNull()
    expect(container.textContent).toBe('')
    // the brand name alone (claude-code) does not populate anything — the
    // rendered result for an unknown pin is byte-identical:
    const other = await mount(
      <PermissionsModeEntry pin={{ harnessId: 'codex', nativeVersion: '9.9.9' }} source={source({ status: 'no-capability-data' })} />,
    )
    expect(other.textContent).toBe('')
  })

  it('attested modes are listed bound to their own pin, and other brands’ vocabularies stay out', async () => {
    const attested = source({
      status: 'attested',
      modes: [
        { name: 'plan', source: 'claude-code@2.0.0 官方模式描述 §permissions' },
        { name: 'acceptEdits', source: 'claude-code@2.0.0 官方模式描述 §permissions' },
      ],
    })
    const model = await resolveModeEntry(pin, attested)
    expect(model.visible === true && model.options.map(o => o.name)).toEqual(['plan', 'acceptEdits'])
    const container = await mount(<PermissionsModeEntry pin={pin} source={attested} />)
    const text = container.textContent ?? ''
    expect(text).toContain('claude-code')
    expect(text).toContain('plan')
    // codex vocabulary ('never', 'on-request') and the forbidden synonyms are absent
    expect(text).not.toContain('on-request')
    expect(text).not.toContain('never')
    expect(text.toLowerCase()).not.toContain('yolo')
    expect(text.toLowerCase()).not.toContain('full access')
    expect(text.toLowerCase()).not.toContain('bypass')
    expect(text).not.toContain('已生效')
  })

  it('a refused capability read says unavailable with its code — never "not installed"', async () => {
    const container = await mount(
      <PermissionsModeEntry pin={pin} source={source({ status: 'refused', code: 'POLICY_ADAPTER_MISSING', message: '适配器未能确认该 pin' })} />,
    )
    const text = container.textContent ?? ''
    expect(text).toContain('POLICY_ADAPTER_MISSING')
    expect(text).not.toContain('未安装')
    expect(text).not.toContain('not installed')
    expect(container.querySelector('select')).toBeNull()
  })

  it('selecting an attested mode records a local draft and never claims the mode changed', async () => {
    const attested = source({ status: 'attested', modes: [{ name: 'plan', source: '官方描述' }] })
    const container = await mount(<PermissionsModeEntry pin={pin} source={attested} />)
    const select = container.querySelector('select') as HTMLSelectElement
    expect(select.getAttribute('aria-label')).toContain('claude-code')
    await act(async () => {
      select.value = 'plan'
      select.dispatchEvent(new Event('change', { bubbles: true }))
    })
    const status = container.querySelector('[role="status"]')
    expect(status!.textContent).toContain('plan')
    expect(status!.textContent).toContain('未声称已生效')
  })

  it('the contribution registers through Chat’s real registry in composer.toolbar', () => {
    const registry = createChatContributions()
    const scope = new OwnedResources()
    const contribution = createModeEntryContribution({ pin, source: source({ status: 'no-capability-data' }) })
    registry.forScope(scope).addContribution(contribution)
    const views = registry.contributionsBySlot('composer.toolbar').getSnapshot()
    expect(views.map(v => v.id)).toContain('permissions.mode-entry')
    expect(views.find(v => v.id === 'permissions.mode-entry')?.keyId).toBe(ModeEntryKey.id)
    // non-composer contexts hide the entry
    const project = views.find(v => v.id === 'permissions.mode-entry')!.project!
    expect(project({ slot: 'session.actions', location: { kind: 'session', connectionId: 'c', sessionId: 's', contextRevision: 1 } }).hidden)
      .toBe(true)
  })
})
