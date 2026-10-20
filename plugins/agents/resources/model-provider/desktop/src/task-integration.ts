/**
 * Adds scoped F5 waiter/progress/notification presentation around the existing
 * Model Provider domain service. It owns no provider values or wire semantics.
 */
import type { IDisposable, ResourceScope } from '@ordessa/extension-api'
import { createTaskScope } from '@ordessa/extension-runtime/tasks'
import type { f5 } from '@extensions/ordessa.contracts/contract.js'
import { ModelProviderWireError, type ModelProviderService } from '../../contracts/index'

interface OperationView {
  readonly id: string
  readonly label: string
}

const OPERATIONS: Readonly<Record<string, OperationView>> = Object.freeze({
  list: { id: 'list', label: '读取模型资源' },
  testConnection: { id: 'test-connection', label: '测试连接' },
  fetchModels: { id: 'fetch-models', label: '读取模型' },
  save: { id: 'save', label: '保存模型配置' },
  importApiKey: { id: 'import-api-key', label: '导入 API Key' },
  queryApiKeyImport: { id: 'query-api-key-import', label: '查询密钥导入结果' },
})

type Captured<T> =
  | { readonly kind: 'value'; readonly value: T }
  | { readonly kind: 'error'; readonly error: unknown }

/**
 * The returned facade preserves each domain method's arguments, promise value,
 * and rejection object. F5 tasks only observe the waiter; they never cancel a
 * Model Provider operation or reinterpret its request identity.
 */
export function createInteractionService(
  service: ModelProviderService,
  resources: ResourceScope,
  interaction: f5.InteractionService,
): ModelProviderService {
  let generation = 1
  let disposed = false
  const activeTasks = new Set<ReturnType<typeof createTaskScope>>()
  const progressHandles = new Map<string, f5.ProgressHandle>()
  const notifications = new Map<string, f5.NotificationHandle>()

  const lifetime: IDisposable = {
    get isDisposed() { return disposed },
    dispose() {
      if (disposed) return
      disposed = true
      generation += 1
      for (const tasks of activeTasks) tasks.releaseAll()
      activeTasks.clear()
      for (const handle of progressHandles.values()) safeClose(handle)
      progressHandles.clear()
      for (const handle of notifications.values()) safeClose(handle)
      notifications.clear()
    },
  }
  resources.add(lifetime)

  function safeClose(handle: { close(): void }): void {
    try { handle.close() } catch { /* presentation teardown cannot change domain outcome */ }
  }

  function notify(operation: OperationView, error: unknown): void {
    if (disposed) return
    const unknown = error instanceof ModelProviderWireError && error.outcome === 'Unknown'
    const id = `model-provider:${operation.id}:outcome`
    try {
      // Never put arbitrary exception text or request arguments into UI: key
      // material is accepted by importApiKey and must remain transient.
      notifications.set(id, interaction.notify({
        id,
        severity: unknown ? 'warning' : 'error',
        text: unknown ? `${operation.label}结果未知，请查询状态后再决定下一步。` : `${operation.label}失败。`,
      }))
    } catch { /* a revoked presenter cannot change the domain error */ }
  }

  function observe<T>(operation: OperationView, result: Promise<T>): Promise<T> {
    if (disposed) return result

    const id = `model-provider:${operation.id}:progress`
    const previous = progressHandles.get(id)
    if (previous) safeClose(previous)

    let tasks: ReturnType<typeof createTaskScope> | undefined
    let cancelWait: () => void = () => undefined
    let progress: f5.ProgressHandle | undefined
    try {
      progress = interaction.progress({
        id,
        text: `正在${operation.label}`,
        cancel: () => cancelWait(), // cancels this observer only, never the wire operation
      })
      progressHandles.set(id, progress)
    } catch { /* task observation still works if presentation is unavailable */ }

    // There is no provider-side progress stream, so the public progress stays
    // indeterminate. The observer captures errors without replacing them.
    const captured: Promise<Captured<T>> = result.then(
      value => ({ kind: 'value', value }),
      error => ({ kind: 'error', error }),
    )
    tasks = createTaskScope({ currentGeneration: () => generation })
    activeTasks.add(tasks)
    const taskGeneration = generation
    const task = tasks.run(
      { activation: 'ordessa.model-provider', generation: taskGeneration },
      async () => captured,
    )
    cancelWait = () => task.cancelWait()

    void task.result().then(result => {
      if (disposed || generation !== taskGeneration || result.kind !== 'done') return
      if (result.value.kind === 'error') notify(operation, result.value.error)
    }).finally(() => {
      tasks?.releaseAll()
      if (tasks) activeTasks.delete(tasks)
      if (progress) {
        // A newer same-operation call replaces and closes this handle when it
        // starts. Its late completion must not dismiss the newer row by id.
        if (progressHandles.get(id) === progress) {
          progressHandles.delete(id)
          safeClose(progress)
        }
      }
    })

    // Return the original promise: callers retain exact values and exact errors.
    return result
  }

  return new Proxy(service, {
    get(target, property) {
      const value = Reflect.get(target, property, target) as unknown
      const operation = typeof property === 'string' ? OPERATIONS[property] : undefined
      if (!operation || typeof value !== 'function') return value
      return (...args: unknown[]) => {
        // Keep synchronous throws and the original promise intact.
        const result = Reflect.apply(value, target, args) as Promise<unknown>
        return observe(operation, result)
      }
    },
  })
}
