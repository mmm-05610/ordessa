/** Read-only Provider/Model resource picker for the Chat composer. */
import type { ComponentType } from 'react'
import {
  chatContribution,
  defineChatComponentKey,
  type ChatContributionsService,
  type ChatLocation,
} from '@extensions/ordessa.chat-api/contract.js'
import type { ResourceScope, IDisposable } from '@ordessa/extension-api'
import type { ModelProviderService, Eligibility } from '@extensions/ordessa.model-provider/contract.js'
import { ModelSelector, type ComposerLocation, type SessionEligibilitySource } from './selector'

export const CANONICAL_MODEL_SELECTOR_ID = 'model-provider.composer.model-selector'
export const CanonicalModelSelectorKey = defineChatComponentKey<{ location: ChatLocation }>(
  'ordessa.chat.model-selector', 1,
)

export interface CanonicalModelSelectorWiring {
  service: ModelProviderService
}

function displayLocation(location: ChatLocation): ComposerLocation {
  return { kind: location.kind, harnessId: location.harnessId ?? '' }
}

const configurationUnavailable = 'Agent Core 尚未提供基于真实 NodeRef 的模型配置应用能力。这里只读 Provider 资源，当前不能应用模型。'
const unsupportedEligibility: SessionEligibilitySource = {
  eligibility: (): Eligibility => 'unsupported',
  reason: () => configurationUnavailable,
}

export function CanonicalModelSelector({ wiring, location }: {
  wiring: CanonicalModelSelectorWiring
  location: ChatLocation
}) {
  return <ModelSelector
    service={wiring.service}
    location={displayLocation(location)}
    eligibilitySource={unsupportedEligibility}
    statusReason={configurationUnavailable}
  />
}

export function canonicalModelSelectorComponent(wiring: CanonicalModelSelectorWiring): ComponentType<{ location: ChatLocation }> {
  return function CanonicalModelSelectorForLocation(props) {
    return <CanonicalModelSelector wiring={wiring} location={props.location} />
  }
}

export function registerCanonicalModelSelector(
  chat: ChatContributionsService,
  scope: ResourceScope,
): IDisposable {
  let disposed = false
  const registration = chat.forScope(scope).addContribution(chatContribution<{ location: ChatLocation }>({
    id: CANONICAL_MODEL_SELECTOR_ID,
    slot: 'composer.toolbar',
    order: 100,
    key: CanonicalModelSelectorKey,
    project: context => context.slot !== 'composer.toolbar'
      ? { hidden: true as const }
      : { hidden: false as const, props: { location: context.location } },
  }))
  return {
    get isDisposed() { return disposed },
    dispose() {
      if (disposed) return
      disposed = true
      registration.dispose()
    },
  }
}
