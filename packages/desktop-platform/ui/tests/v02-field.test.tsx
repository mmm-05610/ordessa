// @vitest-environment jsdom
// V02 Field half (UIB004): label/description/error point at the right control
// ids; aria-describedby lists only the parts actually rendered; two Field.Root
// instances can never reuse an id; an appearing Error never steals focus; and
// Field itself saves nothing, requests nothing and validates nothing (F04).
import { act, useState, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Field, FieldRoot, FieldControl, FieldDescription, FieldError, FieldLabel, Input } from '../src/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
  vi.restoreAllMocks()
})
async function mountPair(element: ReactNode): Promise<{ container: HTMLElement; render: (el: ReactNode) => Promise<void> }> {
  const container = document.createElement('div')
  document.body.append(container)
  const root: Root = createRoot(container)
  cleanups.push(async () => {
    await act(async () => root.unmount())
    container.remove()
  })
  await act(async () => root.render(element))
  return { container, render: async (el: ReactNode) => { await act(async () => root.render(el)) } }
}

interface DemoProps { desc?: boolean; err?: boolean; invalid?: boolean; focused?: boolean }

function Demo({ desc = true, err = true, invalid = false }: DemoProps) {
  const [value, setValue] = useState('Ada')
  return (
    <Field.Root invalid={invalid}>
      <FieldLabel>Name</FieldLabel>
      <FieldControl>
        {(a11y) => <Input {...a11y} value={value} onChange={event => setValue(event.target.value)} />}
      </FieldControl>
      {desc && <FieldDescription>Given name, not family name</FieldDescription>}
      {err && <FieldError>Must not be empty</FieldError>}
    </Field.Root>
  )
}

describe('V02 Field', () => {
  it('V02 label, description and error all point at the right control ids and describedby only lists rendered parts', async () => {
    const { container } = await mountPair(<Demo />)
    const label = container.querySelector('label')!
    const input = container.querySelector('input') as HTMLInputElement
    const desc = container.querySelector('.ods-ui-field-description')!
    const error = container.querySelector('.ods-ui-field-error')!
    expect(input.id).not.toBe('')
    expect(label.htmlFor).toBe(input.id)
    expect(desc.id).not.toBe('')
    expect(error.id).not.toBe('')
    expect(desc.id).not.toBe(error.id)
    expect(input.getAttribute('aria-describedby')?.split(' ')).toEqual([desc.id, error.id])
    // removing a part must remove it from describedby, not leave a dangling id
    const { container: c2, render } = await mountPair(<Demo err={false} />)
    expect(c2.querySelector('input')!.getAttribute('aria-describedby'))
      .toBe(c2.querySelector('.ods-ui-field-description')!.id)
    await render(<Demo err={false} desc={false} />)
    expect(c2.querySelector('input')!.hasAttribute('aria-describedby')).toBe(false)
    await render(<Demo desc={false} />)
    expect(c2.querySelector('input')!.getAttribute('aria-describedby'))
      .toBe(c2.querySelector('.ods-ui-field-error')!.id)
  })

  it('V02 counterexample: two Field.Root instances on one page never reuse a control, description or error id', async () => {
    const { container } = await mountPair(
      <>
        <Demo />
        <Demo invalid />
      </>,
    )
    const roots = container.querySelectorAll('.ods-ui-field')
    expect(roots).toHaveLength(2)
    const inputs = [...container.querySelectorAll('input')]
    expect(inputs).toHaveLength(2)
    expect(inputs[0]!.id).not.toBe(inputs[1]!.id)
    const labels = [...container.querySelectorAll('label')]
    expect(labels.map(l => l.htmlFor)).toEqual([inputs[0]!.id, inputs[1]!.id])
    const partIds = [...container.querySelectorAll('.ods-ui-field-description, .ods-ui-field-error')].map(n => n.id)
    expect(partIds).toHaveLength(4)
    expect(new Set([...partIds, ...inputs.map(i => i.id)]).size).toBe(6)
    // each describedby refers to its own field parts, never the peer's
    const describedBy = inputs.map(i => (i.getAttribute('aria-describedby') ?? '').split(' '))
    expect(describedBy[0]!.every(id => partIds.includes(id))).toBe(true)
    expect(new Set(describedBy.flat()).size).toBe(4)
  })

  it('V02 invalid is a presentation state wired onto the control, default absent', async () => {
    const { container, render } = await mountPair(<Demo invalid />)
    const input = container.querySelector('input')!
    expect(input.getAttribute('aria-invalid')).toBe('true')
    await render(<Demo />)
    expect(input.hasAttribute('aria-invalid')).toBe(false)
  })

  it('V02 an appearing Error never steals focus and carries no live-region semantics of its own', async () => {
    const { container, render } = await mountPair(<Demo err={false} />)
    const input = container.querySelector('input') as HTMLInputElement
    await act(async () => { input.focus() })
    expect(document.activeElement).toBe(input)
    await render(<Demo err />)
    const error = container.querySelector('.ods-ui-field-error')
    expect(error, 'the error appeared').toBeTruthy()
    expect(document.activeElement, 'focus must stay on the control').toBe(input)
    expect(error!.hasAttribute('role')).toBe(false)
    expect(error!.hasAttribute('aria-live')).toBe(false)
  })

  it('V02 typing in a Field calls only the consumer handler and performs no validation, persistence or request', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response())
    const storeSpy = vi.spyOn(Storage.prototype, 'setItem')
    const { container } = await mountPair(<Demo />)
    const input = container.querySelector('input') as HTMLInputElement
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    await act(async () => {
      nativeSetter.call(input, 'Grace')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    // the consumer state drives the value back — but only through its own handler
    expect(input.value).toBe('Grace')
    expect(fetchSpy).toHaveBeenCalledTimes(0)
    expect(storeSpy).toHaveBeenCalledTimes(0)
    // no schema/validation engine inside Field: nothing computed, nothing hidden
    expect(container.querySelector('.ods-ui-field-error')!.textContent).toBe('Must not be empty')
  })

  it('V02 readOnly/disabled reach the control through the state bundle and Field parts enforce their ids', async () => {
    function Locked() {
      return (
        <FieldRoot disabled readOnly required>
          <FieldLabel>Pinned</FieldLabel>
          <FieldControl>
            {(a11y) => {
              expect(a11y.disabled).toBe(true)
              expect(a11y.readOnly).toBe(true)
              expect(a11y.required).toBe(true)
              return <Input {...a11y} value="x" onChange={() => undefined} />
            }}
          </FieldControl>
          <FieldDescription className="extra-desc">help</FieldDescription>
        </FieldRoot>
      )
    }
    const { container } = await mountPair(<Locked />)
    const input = container.querySelector('input')!
    expect(input.disabled).toBe(true)
    expect(input.readOnly).toBe(true)
    expect(input.required).toBe(true)
    const desc = container.querySelector('.ods-ui-field-description')!
    expect(desc.classList.contains('extra-desc'), 'className still merges').toBe(true)
    expect(input.getAttribute('aria-describedby')).toBe(desc.id)
  })

  it('V02 Field parts outside Field.Root fail with a clear error instead of rendering unassociated ids', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    await expect(
      mountPair(<Field.Label>orphan</Field.Label>),
    ).rejects.toThrow(/Field\.Label must be rendered inside a Field\.Root/)
  })
})
