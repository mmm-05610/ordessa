// @vitest-environment jsdom
/**
 * F5 fixture #2 (react panel) — the panel consumes the F5 selection binding
 * as a standalone UI plugin: two views on one owner store, unrelated-field
 * silence, unmount release, old-generation listeners never touch new owners.
 */
import { act, useRef, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PanelOwner, NoteView, TickView, TitleView } from '../src/panel'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const roots: Root[] = []
const hosts: HTMLElement[] = []
afterEach(async () => {
  for (const root of roots.splice(0)) await act(() => root.unmount())
  for (const host of hosts.splice(0)) host.remove()
})

function mount(node: ReactNode): HTMLElement {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  roots.push(root)
  hosts.push(host)
  act(() => { root.render(node) })
  return host
}

const read = (host: HTMLElement, id: string) =>
  host.querySelector(`[data-testid="${id}"]`)!.textContent

describe('f5-react-panel', () => {
  it('two views share one owner store snapshot', () => {
    const owner = new PanelOwner()
    const host = mount(<div><TitleView owner={owner} /><NoteView owner={owner} /></div>)
    expect(read(host, 'title')).toBe('F5 panel')
    act(() => { owner.setNote('hello') })
    expect(read(host, 'note')).toBe('hello')
  })

  it('unrelated field changes never re-render the title view', () => {
    const owner = new PanelOwner()
    const renders = { title: 0 }
    function CountingTitle() {
      const ref = useRef(0)
      ref.current += 1
      renders.title = ref.current
      return <TitleView owner={owner} />
    }
    mount(<div><CountingTitle /><TickView owner={owner} /></div>)
    const baseline = renders.title
    act(() => { owner.bump() }) // tick changes; title selection unchanged
    expect(renders.title).toBe(baseline)
  })

  it('counterexample: late old-generation listener never reaches the new owner', () => {
    const oldOwner = new PanelOwner()
    const oldSpy = vi.fn()
    const released = oldOwner.store.subscribe(oldSpy)
    released.release()
    const newOwner = new PanelOwner()
    mount(<div><NoteView owner={newOwner} /></div>)
    act(() => { newOwner.setNote('fresh') })
    expect(oldSpy).not.toHaveBeenCalled()
    expect(oldOwner.store.getSnapshot().note).toBe('')
  })
})
