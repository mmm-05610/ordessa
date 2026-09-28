/** ordessa.skills — the Workbench settings section and module for Skills.
 *
 * Registration goes through the platform seams only (FR14): a settings section
 * and a module through `WorkbenchComposition`, the detail surface as a
 * contributor-owned overlay so the Workbench owns dismissal and focus
 * restoration. No host internals, no second navigation root.
 *
 * Absence of the composition surface is refused, not papered over — the
 * contract says a consumer "must reject absence rather than silently
 * substituting legacy navigation or view IDs", and a settings page with nowhere
 * to live is exactly that case.
 */
import type { PluginContext } from '@ordessa/extension-api'
import { WorkbenchToken, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import type { ChatContributionsService } from '@extensions/ordessa.chat-api/contract.js'
import type { SkillsGateway, WorkspaceListPort } from '../../contracts/src/gateway'
import type { SkillsChatSnapshotPort } from '../../contracts/src/chat'
import { attachSkillsChatContribution } from './chatContribution'
import type { WireCaller } from './gateway'
import { createSkillsSnapshotGateway, unloadedSkillsSnapshotPort } from './snapshotGateway'
import { createSkillsModel } from './model'
import { SKILLS_DETAIL_OVERLAY_ID, SKILLS_SETTINGS_SECTION_ID, SkillDetailOverlay, SkillsSection } from './view'

export interface SkillsDependencies {
  gateway: SkillsGateway
  workspaces: WorkspaceListPort
  /** Optional chat-api surface (chat checkpoint r3). When the product provides
   * the `ordessa.chat.contributions.v1` service, Skills publishes its `/` and
   * `+` rows through it. Absence is normal for this slice: the settings
   * surface ships without the chat contribution rather than importing a Chat
   * internal. */
  chat?: ChatContributionsService
  /** The real snapshot source (api-requests.md §R-Q1-2, Q1's half): a wire
   * caller for the published `skills.resolve`/`skills.previewEffective`
   * family. When present, the chat section reads the backend's confirmed
   * snapshot through `snapshotGateway.ts`. */
  wire?: WireCaller
  /** Injected-port escape hatch for tests and for a product that owns a
   * better snapshot producer: it always wins over `wire`. */
  chatSnapshot?: SkillsChatSnapshotPort
}

export const SKILLS_MODULE_ID = 'ordessa.skills'

export default function createSkillsPlugin(injected?: unknown) {
  return {
    id: SKILLS_MODULE_ID,
    autoStart: true,
    requires: [WorkbenchToken],
    provides: undefined,
    activate(context: PluginContext, workbench: Workbench) {
      const composition = workbench.composition
      if (composition === undefined) {
        throw Error('ordessa.skills requires a Workbench with composition support')
      }
      const deps = requireDependencies(injected)
      const model = createSkillsModel(deps.gateway, deps.workspaces)
      const scoped = composition.forScope(context.resources)
      const views = workbench.forScope(context.resources)
      // The chat input contribution is registered under the host-issued scope,
      // so leaving the product disposes it and withdraws exactly this source.
      // The snapshot port resolution is honest by construction: injected port
      // (tests / a better producer) → real `skills.resolve` wire gateway →
      // the unloaded port, whose every read answers "not confirmed" and which
      // therefore renders the 未确认/待解析 notice — never an empty-success
      // list (api-requests.md §R-Q1-2).
      if (deps.chat !== undefined) {
        const snapshot = deps.chatSnapshot
          ?? (deps.wire === undefined ? unloadedSkillsSnapshotPort : createSkillsSnapshotGateway(deps.wire))
        attachSkillsChatContribution(deps.chat, context.resources, { snapshot })
      }
      // The same business page, two entry points: settings section + module
      // home view. The module's default views are verified by the Workbench on
      // activation, so a missing home view is a visible error, not a fallback.
      views.addView({
        id: 'ordessa.skills.home', title: 'Skills', presentation: 'region', region: 'main',
        component: () => (
          <SkillsSection model={model} overlays={{ open: (id, options) => composition.openOverlay(id, options) }} />
        ),
      })
      scoped.addModule({ id: SKILLS_MODULE_ID, title: 'Skills', order: 40, homeViewId: 'ordessa.skills.home' })
      scoped.addOverlay({
        id: SKILLS_DETAIL_OVERLAY_ID, title: 'Skill 详情', presentation: 'dialog',
        component: ({ close }) => <SkillDetailOverlay model={model} close={close} />,
      })
      return scoped.addSettingsSection({
        id: SKILLS_SETTINGS_SECTION_ID, title: 'Skills', order: 40,
        component: () => (
          <SkillsSection model={model} overlays={{ open: (id, options) => composition.openOverlay(id, options) }} />
        ),
      })
    },
  }
}

/**
 * The transport seam, demanded not assumed.
 *
 * `SkillsGateway` speaks the published `skills.*` family and the project picker
 * is fed by the Workspace list port. The host API exposes no generic wire call
 * to extensions yet, so an un-injected activation fails loudly instead of
 * mounting an empty library that a user would read as "no Skills installed".
 * The product/integration wave passes `{ gateway, workspaces }` when it admits
 * this extension.
 */
function requireDependencies(injected: unknown): SkillsDependencies {
  const candidate = injected as Partial<SkillsDependencies> | null | undefined
  if (candidate !== null && candidate !== undefined && candidate.gateway && candidate.workspaces) {
    return {
      gateway: candidate.gateway,
      workspaces: candidate.workspaces,
      ...(candidate.chat === undefined ? {} : { chat: candidate.chat }),
      ...(candidate.wire === undefined ? {} : { wire: candidate.wire }),
      ...(candidate.chatSnapshot === undefined ? {} : { chatSnapshot: candidate.chatSnapshot }),
    }
  }
  throw Error(
    'ordessa.skills needs a skills.* gateway and the Workspace project list: '
    + 'no generic wire-call seam is published to extensions yet, so activation refuses '
    + 'rather than showing an empty library as if nothing were installed.',
  )
}
