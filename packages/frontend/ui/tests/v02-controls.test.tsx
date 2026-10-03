// @vitest-environment jsdom
// V02 controls half (UIB004): native button/form semantics. Plain Buttons
// default to type="button" and never submit by accident; busy is a repeat-fire
// guard with aria-busy and no auto-retry; disabled/busy accept zero handler
// calls even under forced dispatch; values are controlled by the consumer and
// `0`/`''` are values, not falsy gaps.
import { act, useState, type ChangeEvent, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Button, Checkbox, IconButton, Input, Select, Textarea } from '../src/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
  vi.restoreAllMocks()
})
async function mount(element: ReactNode): Promise<HTMLElement> {
  return (await mountPair(element)).container
}
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
function forceClick(el: Element): void {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
}
/** Real "user typing" for React: go through the native value setter (bypassing
 * React's value tracker) and dispatch the input event it watches. */
function typeInto(input: HTMLInputElement, text: string): void {
  const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  nativeSetter.call(input, text)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('V02 controls', () => {
  it('V02 a plain Button inside a form keeps type=button and never submits; the form still submits on demand', async () => {
    const onSubmit = vi.fn()
    const onClick = vi.fn()
    const container = await mount(
      <form onSubmit={onSubmit}>
        <Button onClick={onClick}>Plain</Button>
      </form>,
    )
    const button = container.querySelector('button.ods-ui-button') as HTMLButtonElement
    expect(button.type).toBe('button')
    await act(async () => { button.click() })
    expect(onClick).toHaveBeenCalledTimes(1)
    expect(onSubmit, 'type=button must not submit the form').toHaveBeenCalledTimes(0)
    // positive control: the handler is real — an explicit submit does fire it
    const form = container.querySelector('form') as HTMLFormElement
    await act(async () => { form.requestSubmit() })
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('V02 type stays overridable so an intentional submit button still submits', async () => {
    const onSubmit = vi.fn()
    const container = await mount(
      <form onSubmit={onSubmit}>
        <Button type="submit">Send</Button>
      </form>,
    )
    const button = container.querySelector('button') as HTMLButtonElement
    expect(button.type).toBe('submit')
    await act(async () => { button.click() })
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('V02 busy prevents repeat firing with aria-busy and never auto-retries once cleared', async () => {
    const clickSpy = vi.fn()
    const BusyDemo = ({ busy }: { busy: boolean }) => <Button busy={busy} onClick={clickSpy}>Save</Button>
    const { container, render } = await mountPair(<BusyDemo busy />)
    const button = () => container.querySelector('button') as HTMLButtonElement
    expect(button().getAttribute('aria-busy')).toBe('true')
    await act(async () => { forceClick(button()); forceClick(button()); forceClick(button()) })
    expect(clickSpy, 'busy must swallow every click while busy').toHaveBeenCalledTimes(0)
    // no state machine, no auto-retry: after busy clears, one click = one call
    await render(<BusyDemo busy={false} />)
    expect(button().hasAttribute('aria-busy')).toBe(false)
    await act(async () => { forceClick(button()) })
    expect(clickSpy).toHaveBeenCalledTimes(1)
    await act(async () => { forceClick(button()) })
    expect(clickSpy).toHaveBeenCalledTimes(2)
  })

  it('V02 disabled buttons accept zero handler calls even when the click event is forced in', async () => {
    const onClick = vi.fn()
    const container = await mount(<Button disabled onClick={onClick}>Nope</Button>)
    const button = container.querySelector('button') as HTMLButtonElement
    expect(button.disabled).toBe(true)
    await act(async () => { forceClick(button) })
    expect(onClick).toHaveBeenCalledTimes(0)
  })

  it('V02 controlled Input reflects the consumer value, calls only the provided handler, and persists or requests nothing', async () => {
    const seen: string[] = []
    const onChange = vi.fn((event: ChangeEvent<HTMLInputElement>) => { seen.push(event.target.value) })
    const onKeyDown = vi.fn()
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response())
    const storeSpy = vi.spyOn(Storage.prototype, 'setItem')
    const container = await mount(<Input value="alpha" onChange={onChange} onKeyDown={onKeyDown} />)
    const input = container.querySelector('input.ods-ui-input') as HTMLInputElement
    expect(input.value).toBe('alpha')
    await act(async () => {
      typeInto(input, 'typed text')
    })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(seen, 'the handler must observe the typed value').toEqual(['typed text'])
    expect(onKeyDown, 'no other handler may fire').toHaveBeenCalledTimes(0)
    // consumer owns the value: without a state write the DOM snaps back
    expect(input.value).toBe('alpha')
    expect(fetchSpy, 'UI must not issue requests').toHaveBeenCalledTimes(0)
    expect(storeSpy, 'UI must not persist').toHaveBeenCalledTimes(0)
  })

  it('V02 the empty string and 0 are values, never swallowed by falsy checks', async () => {
    const { container, render } = await mountPair(<Input value="" readOnly onChange={() => undefined} />)
    const input = container.querySelector('input') as HTMLInputElement
    expect(input.value).toBe('')
    await render(<Input value={0} readOnly onChange={() => undefined} />)
    expect(input.value).toBe('0')
    expect(input.isConnected).toBe(true)
    // and through a stateful consumer: '' must still re-render as '', not fall
    // back to an uncontrolled default
    function Demo() {
      const [value, setValue] = useState<'' | 5>('')
      return (
        <>
          <Input value={value === '' ? '' : String(value)} onChange={() => setValue('')} />
          <button type="button" onClick={() => setValue(5)}>five</button>
        </>
      )
    }
    const second = await mount(<Demo />)
    const demoInput = second.querySelector('input') as HTMLInputElement
    expect(demoInput.value).toBe('')
    await act(async () => { [...second.querySelectorAll('button')][0]!.click() })
    expect(demoInput.value).toBe('5')
    await act(async () => { typeInto(demoInput, 'x') })
    expect(demoInput.value).toBe('')
  })

  it('V02 Textarea, Select and Checkbox stay native: values reflect, multiple stays usable, events fire the handler once', async () => {
    const onSelect = vi.fn()
    const onCheck = vi.fn()
    const container = await mount(
      <>
        <Textarea value={'multi\nline'} readOnly onChange={() => undefined} />
        <Select value="b" onChange={onSelect}>
          <option value="a">A</option>
          <option value="b">B</option>
        </Select>
        <Select multiple size={2} value={['a', 'b']} onChange={() => undefined}>
          <option value="a">A</option>
          <option value="b">B</option>
        </Select>
        <Checkbox checked onChange={onCheck} />
      </>,
    )
    expect((container.querySelector('textarea') as HTMLTextAreaElement).value).toBe('multi\nline')
    const single = container.querySelectorAll('select')[0]!
    expect(single.value).toBe('b')
    await act(async () => {
      single.value = 'a'
      single.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(onSelect).toHaveBeenCalledTimes(1)
    const multi = container.querySelectorAll('select')[1]!
    expect(multi.multiple).toBe(true)
    expect([...multi.options].filter(o => o.selected).map(o => o.value)).toEqual(['a', 'b'])
    const check = container.querySelector('input[type="checkbox"]') as HTMLInputElement
    expect(check.checked).toBe(true)
    await act(async () => { check.click() })
    expect(onCheck).toHaveBeenCalledTimes(1)
    // controlled: the consumer value survives the native toggle attempt
    expect(check.checked).toBe(true)
  })

  it('V02 IconButton carries its accessible name onto the native button and keeps the safe default type', async () => {
    const container = await mount(<IconButton aria-label="Close dialog">✕</IconButton>)
    const button = container.querySelector('button') as HTMLButtonElement
    expect(button.getAttribute('aria-label')).toBe('Close dialog')
    expect(button.type).toBe('button')
    expect(button.className).toContain('ods-ui-icon-button')
  })

  it('V02 controls forward their ref to the native element', async () => {
    const inputRef: { current: HTMLInputElement | null } = { current: null }
    const buttonRef: { current: HTMLButtonElement | null } = { current: null }
    await mount(
      <>
        <Input ref={inputRef} value="" readOnly onChange={() => undefined} />
        <Button ref={buttonRef}>B</Button>
      </>,
    )
    expect(inputRef.current).toBeInstanceOf(HTMLInputElement)
    expect(buttonRef.current).toBeInstanceOf(HTMLButtonElement)
  })
})
