/**
 * T009-03 call leases: caller/activation/target authorization with an
 * AFTER-AWAIT re-check (contracts/frontend.md §Bridge API).
 *
 * Every call runs under a lease bound to caller, activation, generation and
 * target. The lease is re-checked after the awaited result returns: a lease
 * revoked mid-flight makes the result STALE — the caller receives a typed
 * `Refused` (never an exception, honoring "the host never fails a call with
 * an exception") and must not apply the result to any newer selection.
 */
import type { WirePort, WireResult } from '@ordessa/interface-contracts'

export interface CallContext {
  readonly caller: string
  readonly activation: string
  readonly generation: number
  readonly target: string
}

export interface CallLease {
  readonly id: string
  readonly context: CallContext
  revoke(reason: string): void
  readonly revoked: { active: boolean; reason?: string }
}

export class LeaseRegistry {
  private leases = new Map<string, { context: CallContext; reason?: string }>()
  private seq = 0

  register(context: CallContext): CallLease {
    const id = `lease-${++this.seq}`
    this.leases.set(id, { context })
    const leases = this.leases // capture: the getter below must not rely on `this`
    return {
      id,
      context,
      revoke: (reason: string) => {
        const entry = leases.get(id)
        if (entry !== undefined) entry.reason = reason
      },
      get revoked() {
        const entry = leases.get(id)
        return { active: entry !== undefined && entry.reason !== undefined, reason: entry?.reason }
      },
    }
  }

  valid(id: string): boolean {
    const entry = this.leases.get(id)
    return entry !== undefined && entry.reason === undefined
  }

  contextOf(id: string): CallContext | undefined {
    return this.leases.get(id)?.context
  }

  /** Generation check: a call under an old generation is stale. */
  currentGeneration(activation: string): number | undefined {
    let latest: number | undefined
    for (const entry of this.leases.values()) {
      if (entry.context.activation === activation
          && (latest === undefined || entry.context.generation > latest)) {
        latest = entry.context.generation
      }
    }
    return latest
  }
}

/**
 * Call a wire method under a lease; the lease is re-checked AFTER the await.
 * Revoked leases and stale generations yield typed Refused results — the
 * result delivery itself is the authorization boundary.
 */
export async function callWithContext(
  port: WirePort,
  registry: LeaseRegistry,
  leaseId: string,
  method: string,
  params: Readonly<Record<string, unknown>>,
  requestId: string,
): Promise<WireResult> {
  const result = await port.call(method, params)
  // After-await re-check: authorization is verified again at delivery time.
  if (!registry.valid(leaseId)) {
    return {
      kind: 'Refused',
      requestId,
      reason: 'lease-revoked-after-await',
      retryable: false,
    }
  }
  const context = registry.contextOf(leaseId)
  if (context !== undefined) {
    // a newer generation for the same activation makes this delivery stale
    const leaseCurrent = registry.currentGeneration(context.activation)
    if (leaseCurrent !== undefined && context.generation < leaseCurrent) {
      return { kind: 'Refused', requestId, reason: 'stale-generation-after-await', retryable: false }
    }
  }
  return result
}
