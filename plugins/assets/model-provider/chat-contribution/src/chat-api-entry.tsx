// authored in this line (Z3 T05, chat-api consumption): wires the model
// selector into the REAL published Chat contributions API.
// Consumed checkpoint: chat-api READY @ 54ad26c15d8480823374d85590919ba6bcca60d2
// (implementationSha a3ec20c046, token 'ordessa.chat.contributions.v1').
//
// SLOT MAPPING (recorded, not silently substituted): the model-provider design
// wording says "composer.footer", but the frozen chat-api contract has no such
// slot — its six slots are frozen and the composer-attached one is
// `composer.toolbar` (Chat renders the composer's contribution area from it).
// This module therefore registers on the owner's published slot; if Z2 later
// freezes a footer slot the switch is mechanical (one slot string + order).
import { useMemo } from 'react'
import {
  chatContribution,
  defineChatComponentKey,
  type ChatComponentKey,
  type ChatContributionsService,
  type ChatLocation,
} from '@extensions/ordessa.chat-api/contract.js'
import type { IDisposable, ResourceScope } from '@ordessa/extension-api'
import type { ModelProviderService } from '../../contracts/index'
import { ModelSelector } from './selector'
import { createNextTurnClient, type WireInvoke } from './next-turn-client'

export const MODEL_SELECTOR_ID = 'model-provider.composer.model-selector'

/** The key this domain owns for its composer control (ordessa.chat.*
 * namespace via the contract's single factory). */
export const ModelSelectorKey: ChatComponentKey<{ location: ChatLocation }> =
  defineChatComponentKey<{ location: ChatLocation }>('ordessa.chat.model-selector', 1)

export interface SelectorWiring {
  service: ModelProviderService
  /** The Server wire invoke; undefined = typed refusal at queue time
   * (REQ-Z3-5 still OPEN), never a silent no-op. */
  invoke?: WireInvoke
}

/** Renders the migrated selector against the published ChatLocation shape,
 * owning a per-location next-turn client (queue → pending-next-turn;
 * late/foreign resolutions are rejected inside the client). */
export function ChatModelSelector({ wiring, location }: {
  wiring: SelectorWiring
  location: ChatLocation
}) {
  const client = useMemo(
    () => createNextTurnClient(wiring.invoke, adaptLocation(location)),
    [wiring.invoke, location])
  return <ModelSelector service={wiring.service} location={adaptLocation(location)}
                        queued={client.pending}
                        onQueue={(choice) => { void client.queue(choice) }} />
}

function adaptLocation(location: ChatLocation) {
  // ChatLocation → the selector's session reference; a draft has no native
  // session id, so the selector shows its honest "pick a harness/session
  // first" degradation and the client refuses to queue (TARGET_UNAVAILABLE).
  if (location.kind === 'session') {
    return { kind: 'session' as const, session: {
      serverInstanceId: location.serverInstanceId ?? '',
      harnessId: location.harnessId ?? '',
      acpSessionId: location.sessionId,
    } }
  }
  return { kind: 'draft' as const, target: {
    serverInstanceId: location.serverInstanceId ?? '',
    harnessId: location.harnessId ?? '',
    projectId: location.projectId ?? '',
  } }
}

/** Registers the selector under `scope`; disposing the returned handle (or
 * closing the scope) revokes exactly this registration — Chat keeps working
 * without it (US-4 absence comparison). Nothing here touches Chat's internal
 * store: the wiring travels as projection props keyed by ModelSelectorKey. */
export function registerModelSelector(
  chat: ChatContributionsService, scope: ResourceScope, wiring: SelectorWiring,
): IDisposable {
  const registration = chatContribution({
    id: MODEL_SELECTOR_ID,
    slot: 'composer.toolbar',
    order: 100,
    key: ModelSelectorKey,
    project: (context) => {
      if (context.slot !== 'composer.toolbar') return { hidden: true as const }
      return {
        hidden: false as const,
        props: { location: context.location },
      }
    },
  })
  void wiring
  return chat.forScope(scope).addContribution(registration)
}

export { ModelSelector }
