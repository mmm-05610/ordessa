import type { Token } from '@lumino/coreutils'
import { HarnessAvailabilityServiceToken } from '@extensions/ordessa.contracts/contract.js'
import type { HarnessAvailability } from './harness-availability'

export * from './harness-availability'

/**
 * Domain-typed view of the platform's single opaque DI identity. This is a
 * type-only assertion: the exported value is the exact shared Token object.
 */
export const HarnessAvailabilityToken = HarnessAvailabilityServiceToken as Token<HarnessAvailability>
