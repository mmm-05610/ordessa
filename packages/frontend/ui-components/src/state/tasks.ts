/**
 * F5 async tasks (R7/M14 `oe-f5/1`, T008-15) — the frozen TaskScope/
 * TaskHandle/TaskResult signatures.
 *
 * A task handle is local waiting state over an accepted activity: it never
 * re-implements the Submission/Run business state machines. `cancelWait()`
 * cancels THIS waiter only and reports `cancelled-wait` — it never claims
 * the backend or native side stopped. Late results are generation-checked
 * (a stale-generation result never overwrites a newer selection) and
 * `unknown` outcomes keep their original request association for later
 * querying — never an automatic retry, never a new attempt.
 */
import type {
  TaskHandle,
  TaskResult,
  TaskScope,
} from '../../../contracts/foundation/src/open-environment/f5/types'
import { StaleGenerationError } from '../../../contracts/foundation/src/open-environment/f5/errors'

/**
 * Body signal for an unknown outcome: the task keeps its request
 * association for later querying and never auto-retries.
 */
export class TaskUnknown extends Error {
  constructor(readonly queryHint: string) { super('unknown task outcome') }
}

interface TaskRecord<R> {
  target: { activation: string; generation: number }
  requestKey: string
  promise: Promise<TaskResult<R>>
  settle: (result: TaskResult<R>) => void
  settled: boolean
  cancelledWait: boolean
  progressListeners: Set<(fraction: number | null) => void>
}

export interface TaskScopeOptions {
  /** Generation of the CURRENT owner per activation; late checks consult it. */
  currentGeneration: (activation: string) => number
}

export function createTaskScope(options: TaskScopeOptions): TaskScope {
  const records = new Map<string, TaskRecord<unknown>>()
  let seq = 0

  function run<R>(
    target: { activation: string; generation: number },
    body: (signal: AbortSignal) => Promise<R>,
  ): TaskHandle<R> {
    const taskId = `task-${++seq}`
    const controller = new AbortController()
    let settleFn: (result: TaskResult<R>) => void = () => undefined
    const promise = new Promise<TaskResult<R>>(resolve => { settleFn = resolve })
    const record: TaskRecord<R> = {
      target,
      requestKey: `req-${seq}`,
      promise,
      settle: settleFn,
      settled: false,
      cancelledWait: false,
      progressListeners: new Set(),
    }
    records.set(taskId, record as TaskRecord<unknown>)

    void (async () => {
      try {
        const value = await body(controller.signal)
        // Late-result barrier: a result from a stale generation never
        // overwrites the current owner's selection (A-vs-B case).
        const current = options.currentGeneration(target.activation)
        if (target.generation < current) {
          if (!record.settled) {
            record.settled = true
            settleFn({ kind: 'failed', reason: `stale generation ${target.generation} < ${current}` })
          }
          return
        }
        if (!record.settled) {
          record.settled = true
          settleFn({ kind: 'done', value })
        }
      } catch (cause) {
        if (!record.settled) {
          record.settled = true
          if (controller.signal.aborted && record.cancelledWait) {
            settleFn({ kind: 'cancelled-wait' })
          } else if (cause instanceof TaskUnknown) {
            settleFn({ kind: 'unknown', queryHint: cause.queryHint }) // keeps its requestKey
          } else {
            settleFn({ kind: 'failed', reason: cause instanceof Error ? cause.message : 'failed' })
          }
        }
      }
    })()

    return {
      taskId,
      target,
      requestKey: record.requestKey,
      result: () => promise as Promise<TaskResult<R>>,
      cancelWait: () => {
        // Cancels THIS waiter only: the result promise settles immediately
        // as cancelled-wait. The accepted body may still complete detached —
        // its late value is discarded (settled guard) and never overwrites
        // anything; the accepted activity keeps its real owner (F5 §4).
        record.cancelledWait = true
        controller.abort()
        if (!record.settled) {
          record.settled = true
          record.settle({ kind: 'cancelled-wait' })
        }
      },
      onProgress: cb => {
        record.progressListeners.add(cb)
        let released = false
        return {
          release: () => {
            if (released) return
            released = true
            record.progressListeners.delete(cb)
          },
        }
      },
    }
  }

  return {
    run,
    barrierLatest(): void {
      // Force-settle anything whose generation has fallen behind: the late
      // result must never overwrite a newer owner's selection.
      for (const record of records.values()) {
        const current = options.currentGeneration(record.target.activation)
        if (!record.settled && record.target.generation < current) {
          record.settled = true
          record.settle({ kind: 'failed', reason: `stale generation barrier (${record.target.generation} < ${current})` })
        }
      }
    },
    releaseAll(): void {
      for (const record of records.values()) {
        if (!record.settled) {
          record.cancelledWait = true
          record.settled = true
          record.settle({ kind: 'cancelled-wait' })
        }
      }
      records.clear()
    },
  }
}

/** Re-exported for consumers asserting the typed stale-generation refusal. */
export { StaleGenerationError }
