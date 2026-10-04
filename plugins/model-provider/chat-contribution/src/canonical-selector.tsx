/** Model selector backed by the backend Agent configuration projection. */
import { useCallback, useEffect, useState, type ComponentType } from 'react'
import {
  chatContribution,
  defineChatComponentKey,
  type ChatContributionsService,
  type ChatLocation,
} from '@extensions/ordessa.chat-api/contract.js'
import type { ResourceScope, IDisposable } from '@ordessa/extension-api'
import type { ModelProviderService } from '@extensions/ordessa.model-provider/contract.js'
import type { WirePort } from '@extensions/ordessa.contracts/contract.js'
import type { ConfigurationProjection, ConfigurationProjectionSnapshot } from '@extensions/ordessa.agent-contracts/contract.js'
import type { createWireConfigurationClient } from '@extensions/ordessa.agent-contracts/contract.js'
import type { Eligibility } from '@extensions/ordessa.model-provider/contract.js'
import { ModelSelector, type ComposerLocation, type QueuedChoice } from './selector'

export const CANONICAL_MODEL_SELECTOR_ID = 'model-provider.composer.model-selector'
export const CanonicalModelSelectorKey = defineChatComponentKey<{ location: ChatLocation }>(
  'ordessa.chat.model-selector', 1,
)

export type WireConfigurationClient = ReturnType<typeof createWireConfigurationClient>

export interface CanonicalModelSelectorWiring {
  service: ModelProviderService
  wire: WirePort
  configuration: WireConfigurationClient
}

function locationKey(location: ChatLocation): string {
  return JSON.stringify(location.kind === 'session'
    ? ['session', location.connectionId, location.serverInstanceId, location.sessionId, location.runtimeGeneration]
    : ['draft', location.connectionId, location.serverInstanceId, location.draftId,
      location.projectId, location.harnessId, location.runtimeGeneration])
}

function composerLocation(location: ChatLocation): ComposerLocation {
  if (location.kind === 'session') {
    return { kind: 'session', session: {
      serverInstanceId: location.serverInstanceId ?? '',
      harnessId: location.harnessId ?? '',
      acpSessionId: location.sessionId,
    } }
  }
  return { kind: 'draft', target: {
    serverInstanceId: location.serverInstanceId ?? '',
    harnessId: location.harnessId ?? '',
    projectId: location.projectId ?? '',
  } }
}

function queuedChoice(snapshot: ConfigurationProjectionSnapshot): QueuedChoice | null {
  const model = snapshot.config?.resolved.model
  if (!model || typeof model !== 'object') return null
  const value = model as Record<string, unknown>
  if (typeof value.harnessId !== 'string' || typeof value.providerConfigId !== 'string'
    || typeof value.modelId !== 'string') return null
  return {
    harnessId: value.harnessId,
    providerConfigId: value.providerConfigId,
    modelId: value.modelId,
    ...(Number.isSafeInteger(value.configVersion) ? { configVersion: value.configVersion as number } : {}),
  }
}

function CanonicalModelSelector({ wiring, location }: { wiring: CanonicalModelSelectorWiring; location: ChatLocation }) {
  const key = locationKey(location)
  const [projection, setProjection] = useState<ConfigurationProjection>()
  const [projectionSnapshot, setProjectionSnapshot] = useState<ConfigurationProjectionSnapshot>({
    status: 'loading', target: key,
  })
  const [message, setMessage] = useState<string>()

  useEffect(() => {
    let active = true
    setProjection(undefined)
    setProjectionSnapshot({ status: 'loading', target: key })
    setMessage(undefined)
    const opening: Promise<ConfigurationProjection> = wiring.configuration.forLocation(location)
    void opening.then((value: ConfigurationProjection) => {
      if (!active) return
      setProjection(value)
      setProjectionSnapshot(value.getSnapshot())
    }).catch((error: unknown) => {
      if (active) setMessage(error instanceof Error ? error.message : String(error))
    })
    return () => { active = false }
  }, [wiring.configuration, location.kind, key])

  useEffect(() => {
    if (!projection) return
    const update = () => setProjectionSnapshot(projection.getSnapshot())
    const release = projection.subscribe(update)
    update()
    return release
  }, [projection])

  const refresh = useCallback(() => {
    if (!projection) return
    void projection.refresh().then(setProjectionSnapshot).catch(error => {
      setMessage(error instanceof Error ? error.message : String(error))
    })
  }, [projection])

  const queue = useCallback((choice: QueuedChoice) => {
    if (!projection || projectionSnapshot.status !== 'ready') return
    setMessage(undefined)
    void projection.dispatch({ model: {
      harnessId: choice.harnessId,
      providerConfigId: choice.providerConfigId,
      modelId: choice.modelId,
      ...(choice.configVersion === undefined ? {} : { configVersion: choice.configVersion }),
    } }).then(answer => {
      if (answer.kind === 'unavailable') setMessage(answer.reason)
      else if (answer.kind === 'unknown' || (answer.kind === 'ok' && answer.value.state === 'unknown')) {
        setMessage('模型配置结果未知；保留原操作关联，请刷新核实。')
      }
    }).catch(error => setMessage(error instanceof Error ? error.message : String(error)))
  }, [projection, projectionSnapshot.status])

  const statusReason = message ?? (projectionSnapshot.status === 'loading'
    ? '正在读取 Agent 配置权威。'
    : projectionSnapshot.status === 'unknown'
      ? `Agent 配置状态未知：${projectionSnapshot.queryHint ?? '请刷新核实。'}`
      : projectionSnapshot.status === 'unavailable'
        ? projectionSnapshot.reason ?? 'Agent 配置权威不可用。'
        : projectionSnapshot.config?.observedEvidence === 'unknown'
          ? '配置意图已读取，但原生确认仍未知；发送前会重新核验。' : undefined)

  // Read-only Provider inspection supplies selector eligibility. This does
  // not prepare a native session or write configuration; the selected value
  // remains an Agent intent and the Agent guard checks it again at send time.
  const inspectChoice = useCallback(async (choice: QueuedChoice, version: number) => {
    try {
      const answer = await wiring.wire.call('modelProvider.inspectChoice', {
        harnessId: choice.harnessId,
        providerConfigId: choice.providerConfigId,
        modelId: choice.modelId,
        configVersion: version,
      })
      if (answer.kind === 'Accepted') {
        const verdict = answer.result.verdict
        const eligibility: Eligibility = verdict === 'supported' ? 'ready'
          : verdict === 'unsupported' ? 'unsupported' : 'unknown'
        const reason = typeof answer.result.reason === 'string' ? answer.result.reason : undefined
        return reason === undefined ? { eligibility } : { eligibility, reason }
      }
      return { eligibility: answer.kind === 'Refused' ? 'error' as const : 'unknown' as const,
        reason: answer.reason }
    } catch (error) {
      return { eligibility: 'unknown' as const, reason: error instanceof Error ? error.message : String(error) }
    }
  }, [wiring.wire])
  const current = undefined // confirmed model is not inferred from resolved intent
  return <ModelSelector
    service={wiring.service}
    location={composerLocation(location)}
    inspectChoice={inspectChoice}
    queued={queuedChoice(projectionSnapshot)}
    onQueue={queue}
    disabled={projectionSnapshot.status !== 'ready'}
    lastConfirmed={null}
    current={current}
    onOpen={refresh}
    statusReason={statusReason}
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
  configuration: WireConfigurationClient,
  wiring: Omit<CanonicalModelSelectorWiring, 'configuration'>,
): IDisposable {
  let disposed = false
  const scoped = chat.forScope(scope)
  const registration = scoped.addContribution(chatContribution<{ location: ChatLocation }>({
    id: CANONICAL_MODEL_SELECTOR_ID,
    slot: 'composer.toolbar',
    order: 100,
    key: CanonicalModelSelectorKey,
    project: context => context.slot !== 'composer.toolbar'
      ? { hidden: true as const }
      : { hidden: false as const, props: { location: context.location } },
  }))
  const guard = scoped.addSubmissionGuard({
    id: 'ordessa.agent.configuration.prepare',
    order: 20,
    prepare: snapshot => configuration.prepare(snapshot),
  })
  return {
    get isDisposed() { return disposed },
    dispose() {
      if (disposed) return
      disposed = true
      registration.dispose()
      guard.dispose()
    },
  }
}
