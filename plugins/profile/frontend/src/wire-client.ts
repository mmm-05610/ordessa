import type { WirePort } from '@extensions/ordessa.contracts/contract.js'
import { DelegatingProfileServiceClient, valueState } from '@extensions/ordessa.profile-api/contract.js'

/** Preserve uncertainty: a lost reply is not a safe-to-retry refusal. */
export async function profileCall(wire: WirePort, operation: string, payload: unknown): Promise<unknown> {
  const params = Object.fromEntries(Object.entries(payload as Record<string, unknown>)
    .filter(([, value]) => value !== undefined))
  const result = await wire.call(`profiles.v2.${operation}`, params)
  if (result.kind === 'Accepted') {
    if (!Object.hasOwn(result.result, 'data')) throw new Error('Profile Unknown: malformed response')
    const data = result.result['data']
    if (operation === 'describeFacets') {
      if (!Array.isArray(data)) throw new Error('Profile Unknown: malformed facet catalog')
      return data.map(row => {
        if (!row || typeof row !== 'object' || !Array.isArray(row.items))
          throw new Error('Profile Unknown: malformed facet descriptor')
        const { items, ...descriptor } = row
        return { ...descriptor, itemDescriptors: items }
      })
    }
    if (operation === 'resolvePreview' && !params.sessionUid) {
      if (!data || typeof data !== 'object' || !Array.isArray((data as Record<string, unknown>).items))
        throw new Error('Profile Unknown: malformed preview')
      const preview = data as Record<string, unknown>
      return { ...preview, items: (preview.items as Record<string, unknown>[]).map(item => {
        if (item.source !== 'profile' || typeof item.revision !== 'number')
          throw new Error('Profile Unknown: malformed item source')
        return { ...item, state: valueState(item.value), source: { kind: 'profile', revision: item.revision } }
      }) }
    }
    return data
  }
  throw new Error(`Profile ${result.kind}: ${result.reason}`)
}

export function createWireClient(wire: WirePort) {
  return new DelegatingProfileServiceClient((operation, payload) => profileCall(wire, operation, payload))
}
