import type { WirePort } from '@extensions/ordessa.contracts/contract.js'
import { DelegatingProfileServiceClient } from '@extensions/ordessa.profile-api/contract.js'

/** Preserve uncertainty: a lost reply is not a safe-to-retry refusal. */
export async function profileCall(wire: WirePort, operation: string, payload: unknown): Promise<unknown> {
  const params = Object.fromEntries(Object.entries(payload as Record<string, unknown>)
    .filter(([, value]) => value !== undefined))
  const result = await wire.call(`profiles.v2.${operation}`, params)
  if (result.kind === 'Accepted') {
    if (!Object.hasOwn(result.result, 'data')) throw new Error('Profile Unknown: malformed response')
    return result.result['data']
  }
  throw new Error(`Profile ${result.kind}: ${result.reason}`)
}

export function createWireClient(wire: WirePort) {
  return new DelegatingProfileServiceClient((operation, payload) => profileCall(wire, operation, payload))
}
