// T013: the short per-brand mode entry for the Chat input area (ux.md §Chat:
// 「输入区可以显示一个简短的该品牌模式选择入口」), contributed through Chat's
// real `composer.toolbar` slot.
//
// The entry lists ONLY what the capability source attests for this exact pin
// (harnessId + nativeVersion). It is deliberately NOT driven by the brand name:
// the tree's only brand-keyed vocabulary (`api/brand.py BRAND_NATIVE_MODES`)
// is a static per-brand table, not per-pin proven capability, and the
// permissions backend registers only `permissions.approvals.decide/query` —
// there is no per-pin mode capability READ surface and no mode WRITE wire
// method (registered gap, see README). So the honest path shipped here is the
// refusal one: without an attested answer the entry renders nothing, and a
// brand name alone never invents a menu. Nothing here claims a mode was
// applied — selecting records a local draft and says so.
import { createElement, useEffect, useState, type FunctionComponent } from 'react'
import {
  chatContribution, defineChatComponentKey,
  type ChatContributionContext, type ChatContributionRegistration,
} from '@extensions/ordessa.chat-api/contract.js'

export interface PermissionsModePin {
  readonly harnessId: string
  readonly nativeVersion: string
}

export interface PermissionsModeOption {
  /** The brand-native name, shown verbatim and bound to its own pin. */
  readonly name: string
  /** Where this claim comes from; displayed with the option (FR-09 transparency). */
  readonly source: string
}

/** `no-capability-data` = nothing in this composition proves what this pin
 * supports (the common case today); `refused` = a present source that refused
 * — a local error, never "not installed"; `attested` = per-pin proven modes. */
export type PermissionsModeCapabilityAnswer =
  | { readonly status: 'no-capability-data' }
  | { readonly status: 'refused'; readonly code: string; readonly message: string }
  | { readonly status: 'attested'; readonly modes: readonly PermissionsModeOption[] }

export interface PermissionsModeCapabilitySource {
  modesForPin(pin: PermissionsModePin): Promise<PermissionsModeCapabilityAnswer>
}

export type ModeEntryModel =
  | { readonly visible: false; readonly reason: 'no-capability-data' | 'no-attested-modes' | 'refused'; readonly notice: string | null }
  | { readonly visible: true; readonly pin: PermissionsModePin; readonly options: readonly PermissionsModeOption[] }

/** The whole honesty of T013 in one pure function: options exist only when the
 * injected source attests them for this pin. No branch here reads a brand name
 * to look a vocabulary up, and an attestation with zero modes lists nothing. */
export function modeEntryModel(pin: PermissionsModePin, answer: PermissionsModeCapabilityAnswer): ModeEntryModel {
  if (answer.status === 'no-capability-data') {
    return { visible: false, reason: 'no-capability-data', notice: null }
  }
  if (answer.status === 'refused') {
    return {
      visible: false, reason: 'refused',
      // A present-but-failing source: the wording never speaks of installation.
      notice: `模式能力当前不可读（${answer.code}）：能力来源在场，但未能确认该 pin 的模式集，此处不提供候选。`,
    }
  }
  if (answer.modes.length === 0) {
    return { visible: false, reason: 'no-attested-modes', notice: null }
  }
  return { visible: true, pin, options: answer.modes }
}

export async function resolveModeEntry(
  pin: PermissionsModePin, source: PermissionsModeCapabilitySource,
): Promise<ModeEntryModel> {
  return modeEntryModel(pin, await source.modesForPin(pin))
}

// ---------------------------------------------------------------------------
// Chat contribution (real registry; composer.toolbar is Chat's own input-area
// position — no new container, no popover, no merged sandbox/permissions button)
// ---------------------------------------------------------------------------

export interface ModeEntryProps {
  readonly pin: PermissionsModePin
  readonly source: PermissionsModeCapabilitySource
}

export const ModeEntryKey = defineChatComponentKey<ModeEntryProps>('ordessa.permissions.mode-entry', 1)

const isComposerToolbar = (context: ChatContributionContext): context is
  Extract<ChatContributionContext, { slot: 'composer.toolbar' }> => context.slot === 'composer.toolbar'

/** The host composes one contribution per known pin — the pin travels in
 * construction, so the component never has to guess it from anything else. */
export function createModeEntryContribution(deps: ModeEntryProps): ChatContributionRegistration {
  return chatContribution<ModeEntryProps>({
    id: 'permissions.mode-entry',
    slot: 'composer.toolbar',
    order: 30,
    key: ModeEntryKey,
    project: context => isComposerToolbar(context)
      ? { hidden: false, props: deps }
      : { hidden: true },
  })
}

export const PermissionsModeEntry: FunctionComponent<ModeEntryProps> = props => {
  const h = createElement
  const [model, setModel] = useState<ModeEntryModel | null>(null)
  const [draft, setDraft] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    void resolveModeEntry(props.pin, props.source).then(answer => { if (live) setModel(answer) })
    return () => { live = false }
  }, [props.pin, props.source])

  if (model === null) return h('span', { 'data-mode-entry': 'pending' })
  if (!model.visible) {
    if (model.reason === 'refused' && model.notice !== null) {
      return h('span', { 'data-mode-entry': 'refused', role: 'note' }, model.notice)
    }
    // Honest absence: nothing to show, and nothing invented.
    return h('span', { 'data-mode-entry': 'hidden' })
  }
  const pinLabel = `${model.pin.harnessId}@${model.pin.nativeVersion}`
  return h('span', {
    'data-mode-entry': 'visible', role: 'group', 'aria-label': `该品牌模式（仅 ${pinLabel} 实测能力）`,
  },
    h('select', {
      'aria-label': `${pinLabel} 模式（以品牌原生名称显示，不做跨品牌等价）`,
      value: draft ?? '',
      onChange: (event: { target: { value: string } }) => setDraft(event.target.value),
    },
      h('option', { value: '' }, '（未选择）'),
      model.options.map(option => h('option', { key: option.name, value: option.name },
        `${pinLabel} ▸ ${option.name}（来源：${option.source}）`))),
    draft !== null && h('p', { role: 'status', 'aria-live': 'polite' },
      // There is no mode write channel in this wire vocabulary; the draft is
      // stated as a draft and nothing here may read back as success (FR-09).
      `已记录本地草稿：${model.pin.harnessId}:${draft}（待后端模式通道确认，未声称已生效）`))
}
