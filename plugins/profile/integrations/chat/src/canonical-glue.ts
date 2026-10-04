/** Profile contribution backed only by the Agent's canonical configuration owner. */
import type { ResourceScope } from '@ordessa/extension-api'
import {
  chatContribution,
  type ChatContributionContext,
  type ChatContributionsService,
  type ChatLocation,
} from '@extensions/ordessa.chat-api/contract.js'
import { ProfilePickerKey } from './glue'
import type { ProfileCatalogGroup, ProfileSelection, ProfileServiceClient } from '@extensions/ordessa.profile-api/contract.js'
import type { ConfigurationProjection } from '@extensions/ordessa.agent-contracts/contract.js'
import { ProfilePicker } from './picker'
import type { ProfilePickerProps } from './picker-model'
import type { ProfileCatalog } from './catalog'

export const CanonicalProfilePickerKey = ProfilePickerKey

export interface WireConfigurationClient {
  forLocation(location: ChatLocation): Promise<ConfigurationProjection>
  dispose(): void
  prepare(snapshot: { target: ChatLocation; submissionId: string; draftRevision: number }): Promise<
    | { status: 'ready' }
    | { status: 'refused'; reason: string }
    | { status: 'unknown' }
  >
}

export interface CanonicalProfileGlueInput {
  profiles: Pick<ProfileServiceClient, 'resolvePreview'>
  catalog: () => readonly ProfileCatalogGroup[]
  catalogState?: Pick<ProfileCatalog, 'message' | 'subscribe' | 'getSnapshot' | 'refresh'>
  configuration: WireConfigurationClient
  onOpenManager?: () => void
}

interface ProjectionEntry {
  promise?: Promise<ConfigurationProjection>
  projection?: ConfigurationProjection
  release?: () => void
  pendingLabel?: string
  message?: string
}

/** This key is only a local projection cache key; it never becomes an Agent target. */
function locationCacheKey(location: ChatLocation): string {
  return JSON.stringify(location.kind === 'session'
    ? ['session', location.connectionId, location.serverInstanceId, location.sessionId, location.runtimeGeneration]
    : ['draft', location.connectionId, location.serverInstanceId, location.draftId,
      location.projectId, location.harnessId, location.runtimeGeneration])
}

function profilePatch(preview: Awaited<ReturnType<ProfileServiceClient['resolvePreview']>>) {
  if (preview.conflicts.length > 0) throw new Error('所选 Profile 存在字段冲突，未提交配置。')
  const patch: Record<string, unknown> = {}
  const unset: string[] = []
  for (const item of preview.items) {
    const key = item.facetId === 'assets.model-provider' && item.itemId === 'choice'
      ? 'model' : `${item.facetId}.${item.itemId}`
    if (item.state === 'explicit') patch[key] = item.value
    else if (item.state === 'unset') unset.push(key)
    // disabled/provider-absent values are not present fields and do not clear
    // another control's or Profile's current configuration.
  }
  return { patch, unset }
}

function labelOf(entry: ProjectionEntry | undefined): string | null {
  if (!entry) return null
  if (entry.pendingLabel) return entry.pendingLabel
  return null
}

/**
 * Creates the production Profile picker projection. It has no local Agent
 * owner; Profile selection is a field-masked operation on the resolved target.
 */
export function createCanonicalProfileGlue(
  scope: ResourceScope,
  contributions: ChatContributionsService,
  input: CanonicalProfileGlueInput,
) {
  const entries = new Map<string, ProjectionEntry>()
  const listeners = new Set<() => void>()
  let revision = 0
  let disposed = false
  const publish = () => {
    revision += 1
    for (const listener of [...listeners]) listener()
  }
  const ensureProjection = (location: ChatLocation): Promise<ConfigurationProjection> => {
    const key = locationCacheKey(location)
    let entry = entries.get(key)
    if (!entry) { entry = {}; entries.set(key, entry) }
    if (entry.projection) return Promise.resolve(entry.projection)
    if (!entry.promise) {
      entry.promise = input.configuration.forLocation(location).then(projection => {
        if (disposed) throw new Error('Profile picker scope is retired')
        entry!.projection = projection
        entry!.release = projection.subscribe(publish)
        publish()
        return projection
      }).catch(error => {
        entry!.message = error instanceof Error ? error.message : String(error)
        publish()
        throw error
      })
    }
    return entry.promise
  }
  const subscribe = (listener: () => void) => {
    listeners.add(listener)
    const stopCatalog = input.catalogState?.subscribe(listener)
    return () => { listeners.delete(listener); stopCatalog?.() }
  }
  const getSnapshot = () => revision + (input.catalogState?.getSnapshot() ?? 0)
  const groupsFor = (groups: readonly ProfileCatalogGroup[], location: ChatLocation) =>
    location.kind === 'session' && location.harnessId
      ? groups.filter(group => group.harnessId === location.harnessId)
      : groups

  const registration = contributions.forScope(scope).addContribution(chatContribution<ProfilePickerProps>({
    id: 'ordessa.profile-chat.picker',
    slot: 'composer.toolbar',
    order: 10,
    key: CanonicalProfilePickerKey,
    project: (context: ChatContributionContext) => {
      if (context.slot !== 'composer.toolbar') return { hidden: true }
      const location = context.location
      const entry = entries.get(locationCacheKey(location))
      void ensureProjection(location).catch(() => undefined)
      const liveProps = (): ProfilePickerProps => {
        const active = entries.get(locationCacheKey(location))
        const groups = groupsFor(input.catalog(), location)
        return {
          label: labelOf(active),
          groups,
          statusMessage: active?.message ?? (active?.pendingLabel
            ? '已记录 Profile 配置意图；原生确认会在发送前由 Agent 核验。'
            : input.catalogState?.message)
            ?? (groups.length ? undefined : '当前 Harness 没有可用预设。'),
          onRefresh: input.catalogState ? () => { void input.catalogState!.refresh() } : undefined,
          onOpenSelector: input.catalogState ? () => { void input.catalogState!.refresh() } : undefined,
          onOpenManager: input.onOpenManager,
          onSelect: selection => {
            const selected = entries.get(locationCacheKey(location))!
            selected.pendingLabel = selection.displayName
            selected.message = undefined
            publish()
            void ensureProjection(location).then(async projection => {
              const preview = await input.profiles.resolvePreview(selection.profileId,
                location.kind === 'session' ? location.sessionId : undefined)
              const { patch, unset } = profilePatch(preview)
              const answer = await projection.dispatch(patch, {
                unset,
                sourceRef: `profile:${selection.harnessId}:${selection.profileId}@${preview.revision}:${preview.digest}`,
              })
              if (answer.kind === 'unavailable') selected.message = answer.reason
              else if (answer.kind === 'unknown'
                || (answer.kind === 'ok' && answer.value.state === 'unknown')) {
                selected.message = 'Profile 配置结果未知；已保留原操作关联，请刷新核实。'
              }
              publish()
            }).catch(error => {
              selected.message = error instanceof Error ? error.message : String(error)
              publish()
            })
          },
          subscribe,
          getSnapshot,
          getLiveProps: liveProps,
        }
      }
      return { hidden: false, props: { ...liveProps(), subscribe, getSnapshot, getLiveProps: liveProps } }
    },
  }))

  return {
    dispose() {
      if (disposed) return
      disposed = true
      registration.dispose()
      for (const entry of entries.values()) entry.release?.()
      entries.clear()
      listeners.clear()
    },
  }
}
