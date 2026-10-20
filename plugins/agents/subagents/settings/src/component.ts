/**
 * The React renderer for the Settings definition library.
 *
 * It is deliberately thin: it turns the pure `view.ts` node tree into React
 * elements and binds every interaction to `store.activate(action, attrs)`. It
 * holds **no** logic of its own — no filtering, no stamping, no capability
 * wording — so the headless tests of `view.ts`/`model.ts`/`store.ts` cover the
 * real behaviour rather than a screenshot of it.
 *
 * There is no `dangerouslySetInnerHTML` path in this file: source text can only
 * ever reach React as a child string, which is what `sanitize.ts` guarantees.
 */
import { createElement, useSyncExternalStore, type ReactNode } from 'react'
import type { SettingsStore } from './store'
import { buildSettingsView, type ViewAttrs, type ViewElement, type ViewNode } from './view'

type Activate = (action: string, attrs: ViewAttrs) => void

type Props = Record<string, unknown>

function bind(node: ViewElement, activate: Activate): Props {
  const attrs: ViewAttrs = { ...node.attrs }
  const props: Props = { ...attrs }
  const action = typeof attrs['data-action'] === 'string' ? attrs['data-action'] : null
  const field = typeof attrs['data-field'] === 'string' ? attrs['data-field'] : null
  const path = typeof attrs['data-path'] === 'string' ? attrs['data-path'] : null

  if (node.tag === 'button' && action !== null) {
    props.onClick = () => { activate(action, attrs) }
  }
  if ((node.tag === 'input' || node.tag === 'textarea') && field !== null && field !== 'sourceRef') {
    props.onChange = (event: { target: { value: string } }) => { activate('draft-edit', { ...attrs, 'data-value': event.target.value }) }
  }
  if (node.tag === 'input' && field === 'sourceRef') {
    props.onChange = (event: { target: { value: string } }) => { activate('import-source', { ...attrs, 'data-value': event.target.value }) }
  }
  if (node.tag === 'input' && path !== null) {
    props.onChange = () => { activate('toggle-import-path', { ...attrs }) }
  }
  return props
}

export function toReactNode(node: ViewNode, activate: Activate): ReactNode {
  if (node.kind === 'text') return node.text
  const props: Props = { key: node.key, ...bind(node, activate) }
  const children = node.children.map(child => toReactNode(child, activate))
  return createElement(node.tag, props, children.length === 0 ? null : children)
}

export function renderSettings(store: SettingsStore): ReactNode {
  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState)
  const view = buildSettingsView(state)
  const activate: Activate = (action, attrs) => { store.activate(action, attrs) }
  return toReactNode(view.root, activate)
}

/** The component handed to `WorkbenchSettingsSection`. */
export function createSettingsComponent(store: SettingsStore) {
  return function SubagentSettingsComponent(): ReactNode {
    return renderSettings(store)
  }
}
