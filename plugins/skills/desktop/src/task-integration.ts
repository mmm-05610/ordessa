/** Bridges Skills' existing asynchronous model operations to F5's public task
 * and interaction services. Task handles are waiter state only: disposing the
 * Skills scope releases waiters and closes progress, without claiming that an
 * accepted Server/native operation was stopped.
 */
import type { ResourceScope, IDisposable } from '@ordessa/extension-api'
import { createTaskScope } from '@ordessa/extension-runtime/tasks'
import type { f5 } from '@extensions/ordessa.contracts/contract.js'
import type { SkillsModel, SkillsSnapshot } from './model'

const TASKS: Readonly<Record<string, string>> = Object.freeze({
  refresh: 'Reading Skills resources',
  setHarness: 'Changing the Skills Harness scope',
  setProject: 'Changing the Skills project scope',
  loadPreview: 'Reading Skill preview',
  checkUpdate: 'Checking for Skill updates',
  approveRevision: 'Approving Skill revision',
  importPicked: 'Importing Skill files',
  confirmImport: 'Saving imported Skill',
  cancelImport: 'Cancelling prepared Skill import',
  save: 'Saving Skill assignment',
  reRead: 'Refreshing Skill assignment',
  previewDraft: 'Resolving Skill assignment preview',
  loadNative: 'Reading native Skill availability',
})
const ASYNC_METHODS = new Set(Object.keys(TASKS))

function errorTexts(snapshot: SkillsSnapshot): string[] {
  const values = [
    snapshot.error,
    snapshot.library.error,
    snapshot.sources.error,
    snapshot.projects.error,
    snapshot.native.error,
    snapshot.global.error,
    snapshot.project.error,
    snapshot.detail?.error ?? null,
    snapshot.importPhase.kind === 'failed' ? snapshot.importPhase.message : null,
  ]
  return [...new Set(values.filter((value): value is string => typeof value === 'string' && value.length > 0))]
}

/** Wraps the model's real methods; it does not introduce another Skills state owner. */
export function createInteractionModel(
  model: SkillsModel,
  resources: ResourceScope,
  interaction: f5.InteractionService,
): SkillsModel {
  const tasks = createTaskScope({ currentGeneration: () => 1 })
  const progress = new Set<f5.ProgressHandle>()
  let disposed = false
  const lifetime: IDisposable = {
    get isDisposed() { return disposed },
    dispose() {
      if (disposed) return
      disposed = true
      tasks.releaseAll() // cancels waiting only; it does not stop accepted work
      for (const handle of progress) handle.close()
      progress.clear()
    },
  }
  resources.add(lifetime)

  const run = async (name: string, operation: (...args: unknown[]) => Promise<void>, args: unknown[]) => {
    if (disposed) throw new Error('Skills task scope is closed')
    const label = TASKS[name] ?? 'Working with Skills'
    const handle = interaction.progress({ id: `skills:${name}`, text: label })
    progress.add(handle)
    const previousErrors = new Set(errorTexts(model.getSnapshot()))
    const stopImportProgress = name === 'importPicked' ? model.subscribe(() => {
      const phase = model.getSnapshot().importPhase
      if (phase.kind === 'transferring') {
        const fraction = phase.total > 0 ? Math.min(1, Math.max(0, phase.sent / phase.total)) : null
        handle.update(fraction, `Importing Skill files (${phase.sent}/${phase.total})`)
      }
    }) : undefined
    const task = tasks.run({ activation: 'ordessa.skills', generation: 1 }, async () => {
      await operation(...args)
    })
    try {
      const outcome = await task.result()
      if (outcome.kind === 'failed') throw new Error(outcome.reason)
      if (outcome.kind === 'unknown') {
        interaction.notify({ id: `skills:${name}:unknown`, severity: 'warning', text: 'Skills operation outcome is unknown; refresh to reconcile.' })
        return
      }
      if (outcome.kind === 'cancelled-wait') return
      const freshError = errorTexts(model.getSnapshot()).find(value => !previousErrors.has(value))
      if (freshError) interaction.notify({ id: `skills:${name}:error`, severity: 'error', text: freshError })
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      interaction.notify({ id: `skills:${name}:error`, severity: 'error', text: message })
      throw cause
    } finally {
      stopImportProgress?.()
      handle.close()
      progress.delete(handle)
    }
  }

  return new Proxy(model, {
    get(target, property, receiver) {
      const value = Reflect.get(target, property, receiver) as unknown
      if (typeof property !== 'string' || !ASYNC_METHODS.has(property) || typeof value !== 'function') return value
      return (...args: unknown[]) => run(property, value.bind(target), args)
    },
  })
}
