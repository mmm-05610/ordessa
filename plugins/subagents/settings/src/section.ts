/**
 * The Settings contribution for the definition library (FR11: registered
 * through the public composition API, nothing else).
 *
 * The section object is a real `WorkbenchSettingsSection` from the platform
 * contract (`packages/workbench/api/workbench.ts:25`, registered at `:41`,
 * located by `openSettings` at `:45`), and
 * the `IDisposable` handed back is the host's own handle, wrapped so that a
 * second live registration of the same section id in the same scope is
 * impossible rather than merely discouraged.
 *
 * §C2 unload semantics: disposing the handle removes *this contribution's* UI.
 * The store — drafts, selections, already-read rows — is owned by the caller and
 * is never cleared here; hiding is not deleting.
 */
import type { IDisposable, ResourceScope } from '@ordessa/extension-api'
import type { WorkbenchComposition, WorkbenchSettingsSection } from '@extensions/ordessa.contracts/contract.js'
import { FACET_ID } from './contract'
import { createSettingsComponent } from './component'
import { createSettingsStore, type SettingsStore, type StoreDependencies } from './store'

/**
 * Section id. It carries the frozen facet id (ruling L1: the facet/line identity
 * is `assets.native-subagents`); renaming it would need a migration note.
 */
export const SETTINGS_SECTION_ID = `${FACET_ID}.library`
export const SETTINGS_SECTION_TITLE = '子代理定义库'
export const SETTINGS_SECTION_ORDER = 30

export class SettingsRegistrationError extends Error {
  readonly sectionId: string
  constructor(sectionId: string, detail: string) {
    super(`子代理定义库设置区注册失败（${sectionId}）：${detail}`)
    this.name = 'SettingsRegistrationError'
    this.sectionId = sectionId
  }
}

/** Live registrations per scope, so a duplicate is refused *before* the host throws. */
const liveRegistrations = new WeakMap<ResourceScope, Map<string, IDisposable>>()

export interface SubagentSettingsSectionInput {
  readonly store: SettingsStore
  readonly title?: string
  readonly order?: number
}

/** Build the section object the Workbench contract expects (id/title/order/component). */
export function createSettingsSection(input: SubagentSettingsSectionInput): WorkbenchSettingsSection {
  return {
    id: SETTINGS_SECTION_ID,
    title: input.title ?? SETTINGS_SECTION_TITLE,
    order: input.order ?? SETTINGS_SECTION_ORDER,
    component: createSettingsComponent(input.store),
  }
}

/**
 * Register the section through the public composition surface and hand back a
 * faithful `IDisposable`: idempotent, and it releases the duplicate guard.
 */
export function addSettingsSection(
  composition: WorkbenchComposition,
  scope: ResourceScope,
  section: WorkbenchSettingsSection,
): IDisposable {
  if (scope.isDisposed) throw new SettingsRegistrationError(section.id, '注册作用域已关闭')
  const claimed = liveRegistrations.get(scope) ?? new Map<string, IDisposable>()
  liveRegistrations.set(scope, claimed)
  if (claimed.has(section.id)) {
    throw new SettingsRegistrationError(section.id, '同一作用域内已有一个存活的注册；重复注册不可能发生')
  }
  // The host's own duplicate check (`Contributions.add`) still applies on top of
  // this guard, so a cross-scope double registration is rejected by the registry.
  const handle = composition.forScope(scope).addSettingsSection(section)
  let released = false
  const disposable: IDisposable = {
    get isDisposed() { return released },
    dispose() {
      if (released) return
      released = true
      claimed.delete(section.id)
      if (claimed.size === 0) liveRegistrations.delete(scope)
      handle.dispose()
    },
  }
  claimed.set(section.id, disposable)
  return disposable
}

export interface InstalledSettings {
  readonly section: WorkbenchSettingsSection
  readonly store: SettingsStore
  readonly handle: IDisposable
}

/** One-call install: build the store, build the section, register it. */
export function installSubagentSettings(
  composition: WorkbenchComposition,
  scope: ResourceScope,
  deps: StoreDependencies,
  initial: { readonly loadOnInstall?: boolean } = {},
): InstalledSettings {
  const store = createSettingsStore(deps)
  const section = createSettingsSection({ store })
  const handle = addSettingsSection(composition, scope, section)
  if (initial.loadOnInstall !== false) store.reload()
  return { section, store, handle }
}
