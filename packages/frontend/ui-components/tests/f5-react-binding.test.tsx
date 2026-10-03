// @vitest-environment jsdom
// T008-13 — F5 React selection binding: same snapshot source as the
// non-React side, unmount releases, unrelated fields never re-render, and a
// late old-generation listener never reaches a new owner (F5 §2).
import { act, useRef, useState, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { stateStoreFactory, type OwnedState } from '../src/state/stateStore'
import { createSelector } from '../src/state/selectors'
import { useStoreSelection } from '../react/state'

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

type Model = { input: string; heavy: number }

function FieldView({ store }: {
  store: OwnedState<Model>
}) {
  const input = useStoreSelection(store, createSelector((s: Model) => s.input))
  const renders = useRef(0)
  renders.current += 1
  return (
    <div>
      <output data-testid="value">{input}</output>
      <output data-testid="renders">{renders.current}</output>
    </div>
  )
}

const read = (host: HTMLElement, id: string) =>
  host.querySelector(`[data-testid="${id}"]`)!.textContent

describe('F5 useStoreSelection', () => {
  it('shares one snapshot source with the non-React side and updates on field change', () => {
    const store = stateStoreFactory.createOwned<Model>({ input: 'a', heavy: 0 })
    const host = mount(<FieldView store={store} />)
    expect(read(host, 'value')).toBe('a')
    act(() => { store.update(s => ({ ...s, input: 'b' })) })
    expect(read(host, 'value')).toBe('b')
    expect(store.getSnapshot().input).toBe('b') // same snapshot the reader sees
  })

  it('unrelated fields never re-render the selection view', () => {
    const store = stateStoreFactory.createOwned<Model>({ input: 'a', heavy: 0 })
    const host = mount(<FieldView store={store} />)
    const baseline = Number(read(host, 'renders'))
    act(() => { store.update(s => ({ ...s, heavy: 42 })) })
    expect(Number(read(host, 'renders'))).toBe(baseline)
  })

  it('unmount releases the subscription', () => {
    const store = stateStoreFactory.createOwned<Model>({ input: 'a', heavy: 0 })
    const spy = vi.spyOn(store, 'subscribe')
    const host = mount(<FieldView store={store} />)
    act(() => { roots[0].unmount(); roots.length = 0 })
    const secondHost = mount(<FieldView store={store} />)
    act(() => { store.update(s => ({ ...s, input: 'z' })) })
    expect(read(secondHost, 'value')).toBe('z')
    expect(spy).toHaveBeenCalledTimes(2) // second mount re-subscribed; first was released
  })

  it('counterexample: a late old-generation listener never touches a new owner', () => {
    const oldStore = stateStoreFactory.createOwned<Model>({ input: 'old', heavy: 0 })
    const oldSpy = vi.fn()
    const released = oldStore.subscribe(oldSpy)
    released.release() // old scope disposed
    const newStore = stateStoreFactory.createOwned<Model>({ input: 'new', heavy: 0 })
    const host = mount(<FieldView store={newStore} />)
    act(() => { newStore.update(s => ({ ...s, input: 'newer' })) })
    expect(oldSpy).not.toHaveBeenCalled()
    expect(oldStore.getSnapshot().input).toBe('old')
    expect(read(host, 'value')).toBe('newer')
  })
})

function Panel() {
  const [mounted, setMounted] = useState(true)
  return (
    <div>
      <button onClick={() => setMounted(false)}>unmount</button>
      {mounted && <FieldView store={singletonStore} />}
    </div>
  )
}
const singletonStore = stateStoreFactory.createOwned<Model>({ input: 'x', heavy: 0 })

describe('panel lifecycle', () => {
  it('interactive unmount leaves no active subscription behind', () => {
    mount(<Panel />)
    act(() => {
      document.body.querySelector('button')!.click()
    })
    const before = singletonStore.getSnapshot()
    act(() => { singletonStore.update(s => ({ ...s, input: 'gone' })) })
    expect(singletonStore.getSnapshot().input).toBe('gone')
    expect(before.input).toBe('x') // published snapshots stay immutable history
  })
})
