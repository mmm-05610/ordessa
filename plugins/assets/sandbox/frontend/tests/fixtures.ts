// Fixtures use only the option vocabulary the backend actually publishes
// (plugins/assets/sandbox/api/src/ordessa_sandbox_api/matrix.py BRAND_OPTIONS)
// so no test can pass by inventing an option name.
import {
  SANDBOX_DESCRIBE_API_VERSION,
  type SandboxDescribeRequest,
  type SandboxDescribeResponse,
  type SandboxDescribeResult,
  type SandboxDescribeTransport,
  type SandboxOption,
} from '../src/contract'

export function option(over: Partial<SandboxOption> = {}): SandboxOption {
  return {
    optionId: 'sandbox_mode=read-only', status: 'supported', source: 'pinned vocabulary',
    platforms: ['linux', 'macos', 'windows'], coverage: ['bash', 'read', 'edit'],
    lockedByAdministrator: false, note: '', ...over,
  }
}

export function describeResult(over: Partial<SandboxDescribeResult> = {}): SandboxDescribeResult {
  return {
    apiVersion: SANDBOX_DESCRIBE_API_VERSION, harnessId: 'codex', nativeVersion: '0.147.0',
    visible: true, status: 'available', reason: 'harnesses.toml pin', lockedByAdministrator: false,
    options: codexOptions(), ...over,
  }
}

/** matrix.py BRAND_OPTIONS["codex"] */
export function codexOptions(): SandboxOption[] {
  return [
    option({ note: 'effect proof still requires bound evidence' }),
    option({ optionId: 'sandbox_mode=workspace-write' }),
    option({
      optionId: 'sandbox_mode=danger-full-access', status: 'unsupported',
      source: 'in the native vocabulary but outside the writable set: never offered',
      coverage: [],
    }),
  ]
}

/** matrix.py BRAND_OPTIONS["claude-code"] — every cell UNKNOWN, coverage Bash only. */
export function claudeOptions(): SandboxOption[] {
  return [
    option({
      optionId: 'bash_sandbox=enabled', status: 'unknown',
      source: 'documented mechanism (bubblewrap/Seatbelt); no L2 probe on the current pin',
      platforms: ['linux', 'wsl2', 'macos'], coverage: ['bash'],
    }),
    option({
      optionId: 'powershell_sandbox=enabled', status: 'unknown', platforms: ['windows'], coverage: [],
    }),
    option({ optionId: 'monitor_sandbox=enabled', status: 'unknown', platforms: [], coverage: [] }),
  ]
}

export function codexDescribe(over: Partial<SandboxDescribeResult> = {}): SandboxDescribeResult {
  return describeResult({ harnessId: 'codex', options: codexOptions(), ...over })
}

export function claudeDescribe(over: Partial<SandboxDescribeResult> = {}): SandboxDescribeResult {
  return describeResult({ harnessId: 'claude-code', nativeVersion: '2.1.270', options: claudeOptions(), ...over })
}

/** The OK-but-nothing-proven answer: visible, status unknown, and NO options. */
export function unknownPinDescribe(harnessId = 'opencode'): SandboxDescribeResult {
  return describeResult({
    harnessId, nativeVersion: '', status: 'unknown', options: [],
    reason: `('${harnessId}', '') is not a pinned native-sandbox family/version in this repository; no menu is invented`,
  })
}

/** A transport that answers from a scripted queue; the last entry repeats. */
export function fakeTransport(...responses: SandboxDescribeResponse[]) {
  const calls: SandboxDescribeRequest[] = []
  const transport: SandboxDescribeTransport = {
    describe: async request => {
      calls.push(request)
      return responses[Math.min(calls.length - 1, responses.length - 1)]
    },
  }
  return { transport, calls }
}

export const REQUEST: SandboxDescribeRequest = {
  harnessId: 'codex', nativeVersion: '0.147.0', osName: 'linux', osVersion: '6.9',
}

export const ok = (result: SandboxDescribeResult): SandboxDescribeResponse => ({ status: 'ok', result })
export const noProvider = (): SandboxDescribeResponse => ({ status: 'no-provider' })
export const providerError = (message = 'describe failed'): SandboxDescribeResponse => ({
  status: 'error', code: 'PROVIDER_BUSY', message,
})
