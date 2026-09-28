// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (contracts/service.ts, verbatim)
/**
 * The wire-facing service surface. Method names, params and projections are
 * frozen by specs/002-model-provider/contracts/backend-wire.md; this file
 * only types them for the desktop side.
 */
import type { Eligibility, ProviderConfigState } from './states'

export interface ModelOfferingView {
  modelId: string
  displayName?: string
  availability?: 'unknown' | 'available' | 'unavailable'
  unavailableReason?: string | null
  eligibility?: Eligibility
  eligibilityReason?: string
}

export interface ProviderConfigView {
  id: string
  version: number
  displayName: string
  harness: string | null
  provider: string
  credentialId: string | null
  models: ModelOfferingView[]
  archivedAt: string | null
  /** 'harness' = read from the harness's own configuration; 'ordessa' = a named preset saved here. */
  managedBy: 'harness' | 'ordessa'
  state: ProviderConfigState
  lastProbeAt?: string
  provenance?: { baseUrl?: string; authStyle?: string; wireApi?: string; fieldsSource?: string } | null
  createdAt: string
  updatedAt: string
}

export interface ProbeAnswer {
  status: 'ok' | 'failed' | 'reachable' | 'unreachable'
  models?: string[]
  code?: string
  detail?: string
}

export type WireInvoke = (method: string, params: object) => Promise<unknown>

export interface ModelProviderWire {
  list(includeArchived: boolean): Promise<{ items: ProviderConfigView[]; nextCursor: null }>
  create(body: Record<string, unknown>): Promise<{ providerModel: ProviderConfigView }>
  update(body: Record<string, unknown>): Promise<{ providerModel: ProviderConfigView }>
  archive(providerModelId: string, expectedVersion: number): Promise<{ providerModel: ProviderConfigView }>
  probeModels(baseUrl: string, credentialId: string | null): Promise<ProbeAnswer>
  probeConnection(baseUrl: string, credentialId: string | null): Promise<ProbeAnswer>
}

/** The one transport seam; production wires the extension host, tests fake it. */
export function wireThrough(invoke: WireInvoke): ModelProviderWire {
  return {
    list: (includeArchived) => invoke('providerModels.list', { includeArchived }) as never,
    create: (body) => invoke('providerModels.create', body) as never,
    update: (body) => invoke('providerModels.update', body) as never,
    archive: (providerModelId, expectedVersion) =>
      invoke('providerModels.archive', { requestId: `arch-${Date.now()}-${providerModelId}`, providerModelId, expectedVersion }) as never,
    probeModels: (baseUrl, credentialId) =>
      invoke('providerModels.probeModels', { requestId: `probe-${Date.now()}`, baseUrl, credentialId }) as never,
    probeConnection: (baseUrl, credentialId) =>
      invoke('providerModels.probeConnection', { requestId: `conn-${Date.now()}`, baseUrl, credentialId }) as never,
  }
}

export interface ModelProviderService {
  readonly wire: ModelProviderWire
  /** Outbound *probe* requests only - the counterexample behind
   * FR-STATE-3 (settings render must not auto-probe). */
  readonly probeCalls: number
  list(includeArchived?: boolean): Promise<ProviderConfigView[]>
  testConnection(baseUrl: string, credentialId: string | null): Promise<ProbeAnswer>
  fetchModels(baseUrl: string, credentialId: string | null): Promise<ProbeAnswer>
  save(body: Record<string, unknown>, edit?: { id: string; version: number }): Promise<ProviderConfigView>
}
