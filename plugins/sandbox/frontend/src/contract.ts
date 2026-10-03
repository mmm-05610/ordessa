// TypeScript mirror of the published `sandbox.describe@1` contract.
//
// Authority for every name below:
//   plugins/assets/sandbox/api/src/ordessa_sandbox_api/describe.py   (SandboxOption,
//       SandboxDescription.options_for_ui/select, _OPTION_STRICTNESS)
//   plugins/assets/sandbox/api/src/ordessa_sandbox_api/matrix.py     (CellStatus,
//       DescribeOption, BRAND_OPTIONS — the only option vocabulary that exists)
//   plugins/assets/sandbox/api/src/ordessa_sandbox_api/platform.py   (PlatformResult)
//   plugins/assets/sandbox/api/src/ordessa_sandbox_api/errors.py     (SandboxErrorCode)
//   plugins/assets/sandbox/backend/src/ordessa_sandbox_backend/composition.py
//       (FacetDescription.to_wire — the exact JSON the wire method answers with)
//   plugins/assets/sandbox/backend/src/ordessa_sandbox_backend/plugin.py
//       (method id `sandbox.describe`, required/optional parameter sets)
//
// Nothing here names an option, a platform or a coverage category: those values
// arrive from the backend only. `tests/cross-language-codes.test.ts` fails the
// build if this mirror and the Python source drift apart.
import type { WorkbenchComposition } from '@extensions/ordessa.contracts/contract.js'

/** Wire api version string the backend answers with (`to_wire`). */
export const SANDBOX_DESCRIBE_API_VERSION = 'sandbox.describe@1'

/** The one read-only method this region consumes. */
export const SANDBOX_DESCRIBE_METHOD = 'sandbox.describe'

/** `plugin.py:_DESCRIBE_REQUIRED` — exact parameter names, copied not guessed. */
export const SANDBOX_DESCRIBE_REQUIRED_PARAMS = ['harnessId'] as const
/** `plugin.py:_DESCRIBE_OPTIONAL`. */
export const SANDBOX_DESCRIBE_OPTIONAL_PARAMS =
  ['nativeVersion', 'osName', 'osVersion', 'platformVersion'] as const

/**
 * The six stable sandbox refusal codes (contracts.md §C4). `errors.py` keeps a
 * seventh, `SANDBOX_INTENT_INVALID`, deliberately outside this set because a
 * schema typo must not read as a platform or coverage verdict; the region
 * mirrors the stable six and the cross-language test asserts that boundary.
 */
export const SANDBOX_STABLE_ERROR_CODES = Object.freeze([
  'SANDBOX_NATIVE_UNSUPPORTED',
  'SANDBOX_COVERAGE_UNPROVEN',
  'SANDBOX_PLATFORM_UNSUPPORTED',
  'SANDBOX_CONFIG_CONFLICT',
  'SANDBOX_EFFECT_UNKNOWN',
  'PROVIDER_BUSY',
] as const)

export type SandboxErrorCode = (typeof SANDBOX_STABLE_ERROR_CODES)[number]

export function isSandboxErrorCode(value: unknown): value is SandboxErrorCode {
  return (SANDBOX_STABLE_ERROR_CODES as readonly string[]).includes(String(value))
}

/** `matrix.py:CellStatus` — a describe cell. Unsupported and unknown stay distinct. */
export type SandboxOptionStatus = 'supported' | 'unsupported' | 'unknown'

/** `platform.py:PlatformResult`, kept separate from the cell status. */
export type SandboxPlatformResult = 'supported' | 'unsupported' | 'unknown'

/** `composition.py:FacetDescription.status`. */
export type SandboxDescribeStatus = 'available' | 'unknown' | 'uninstalled'

/** `describe.py:SandboxOption` / `to_wire().options[i]`, camelCased as on the wire. */
export interface SandboxOption {
  readonly optionId: string
  readonly status: SandboxOptionStatus
  /** Where this option's claim comes from; shown verbatim, never summarised away. */
  readonly source: string
  readonly platforms: readonly string[]
  /** Measured tool categories this option covers — an incomplete list by design. */
  readonly coverage: readonly string[]
  readonly lockedByAdministrator: boolean
  readonly note: string
}

/** `composition.py:FacetDescription.to_wire(harnessId, nativeVersion)`. */
export interface SandboxDescribeResult {
  readonly apiVersion: string
  readonly harnessId: string
  readonly nativeVersion: string
  /** False means the facet is uninstalled: the UI region disappears, values stay. */
  readonly visible: boolean
  readonly status: SandboxDescribeStatus
  readonly reason: string
  readonly lockedByAdministrator: boolean
  readonly options: readonly SandboxOption[]
}

/** Exactly the `sandbox.describe` parameter object. */
export interface SandboxDescribeRequest {
  harnessId: string
  nativeVersion?: string
  osName?: string
  osVersion?: string
  platformVersion?: string
}

/**
 * One answer from the backend. `no-provider` is the host's "this method is not
 * registered" outcome (the Sandbox backend plugin is absent); `error` is a
 * registered provider that refused — the two must never collapse into one
 * another, or a broken service would be reported as an uninstalled one.
 */
export type SandboxDescribeResponse =
  | { readonly status: 'no-provider' }
  | { readonly status: 'error'; readonly code: SandboxErrorCode; readonly message: string }
  | { readonly status: 'ok'; readonly result: SandboxDescribeResult }

/**
 * The injected transport. Its method maps 1:1 onto the real `sandbox.describe`
 * parameters; this package performs no network or IPC work of its own, and the
 * product assembly decides which channel carries the call.
 */
export interface SandboxDescribeTransport {
  describe(request: SandboxDescribeRequest): Promise<SandboxDescribeResponse>
}

/**
 * `SandboxDescription.options_for_ui()` in Python: only supported options may
 * reach a menu. Unknown and unsupported cells stay out entirely rather than
 * appearing as greyed guesses, so an unproven cell cannot be clicked.
 */
export function sandboxMenuOptions(result: Pick<SandboxDescribeResult, 'options'>): SandboxOption[] {
  return result.options.filter(option => option.status === 'supported')
}

/**
 * The real Settings contribution surface: the `addSettingsSection` member of
 * `WorkbenchComposition.forScope(scope)`, as published by the platform contract
 * (packages/workbench/api/workbench.ts). Taken by type so this region cannot
 * register through anything but the platform's own API.
 */
export type SandboxSettingsHost = Pick<
  ReturnType<WorkbenchComposition['forScope']>,
  'addSettingsSection'
>
