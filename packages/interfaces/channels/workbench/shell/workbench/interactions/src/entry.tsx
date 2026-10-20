import { useSyncExternalStore, type ComponentType } from 'react'
import type { PluginContext, IDisposable } from '@ordessa/extension-api'
import { F5InteractionToken, WorkbenchToken, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import { createInteractionService, type InteractionPresenter } from '@ordessa/workbench/interactions'

interface PresentedInteraction {
  readonly id: string
  readonly kind: 'notification' | 'progress'
  readonly text: string
  readonly severity?: 'info' | 'warning' | 'error'
  readonly fraction?: number | null
  readonly requestCancel?: () => void
}

function createPresenter() {
  let snapshot: readonly PresentedInteraction[] = Object.freeze([])
  const listeners = new Set<() => void>()
  const publish = () => {
    snapshot = Object.freeze([...rows.values()])
    for (const listener of [...listeners]) listener()
  }
  const rows = new Map<string, PresentedInteraction>()
  const presenter: InteractionPresenter = {
    show(kind, view) {
      rows.set(view.id, Object.freeze({
        id: view.id, kind, text: view.text, severity: view.severity,
        fraction: view.fraction,
        ...(view.cancellable ? { requestCancel: view.requestCancel } : {}),
      }))
      publish()
    },
    dismiss(id) {
      if (rows.delete(id)) publish()
    },
  }
  const subscribe = (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener) }
  const getSnapshot = () => snapshot
  const component: ComponentType = function WorkbenchInteractionStatus() {
    const items = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
    if (items.length === 0) return null
    return <div className="wb-interactions" aria-label="任务与通知" data-testid="workbench-interactions">
      {items.map(item => <div key={item.id} role={item.severity === 'error' ? 'alert' : 'status'}
        data-interaction-id={item.id} data-interaction-kind={item.kind} data-severity={item.severity}>
        <span>{item.text}</span>
        {item.kind === 'progress' && <progress aria-label={item.text}
          {...(item.fraction === null || item.fraction === undefined ? {} : { value: item.fraction, max: 1 })} />}
        {item.requestCancel && <button type="button" aria-label={`停止等待：${item.text}`}
          onClick={item.requestCancel}>停止等待</button>}
      </div>)}
    </div>
  }
  return { presenter, component, clear() { rows.clear(); publish() } }
}

/** The separate provider keeps Workbench's existing single WorkbenchToken intact. */
export default function createPlugin() {
  return {
    id: 'ordessa.workbench-interactions',
    autoStart: true,
    provides: F5InteractionToken,
    requires: [WorkbenchToken],
    activate(context: PluginContext, workbench: Workbench) {
      const view = createPresenter()
      const generation = { value: 1 }
      const registration = workbench.forScope(context.resources).addUI({
        id: 'ordessa.workbench.interactions', kind: 'component', slot: 'statusbar', component: view.component,
      })
      const service = createInteractionService({
        presenter: view.presenter,
        scopeGeneration: () => generation.value,
      })
      const lifecycle: IDisposable = {
        get isDisposed() { return generation.value !== 1 },
        dispose() {
          if (generation.value !== 1) return
          generation.value += 1
          view.clear()
          registration.dispose()
        },
      }
      context.resources.add(lifecycle)
      return service
    },
  }
}
