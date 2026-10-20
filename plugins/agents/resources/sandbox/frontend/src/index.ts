// Package barrel: the public surface of the Sandbox Settings contribution.
// Everything the product assembly needs to wire the region, and nothing of the
// Workbench or Permissions internals behind it.
export {
  SANDBOX_DESCRIBE_API_VERSION,
  SANDBOX_DESCRIBE_METHOD,
  SANDBOX_DESCRIBE_OPTIONAL_PARAMS,
  SANDBOX_DESCRIBE_REQUIRED_PARAMS,
  SANDBOX_STABLE_ERROR_CODES,
  isSandboxErrorCode,
  sandboxMenuOptions,
  type SandboxDescribeRequest,
  type SandboxDescribeResponse,
  type SandboxDescribeResult,
  type SandboxDescribeStatus,
  type SandboxDescribeTransport,
  type SandboxErrorCode,
  type SandboxOption,
  type SandboxOptionStatus,
  type SandboxPlatformResult,
  type SandboxSettingsHost,
} from './contract'
export {
  SANDBOX_SETTINGS_SECTION_ID,
  SANDBOX_SETTINGS_SECTION_TITLE,
  sandboxRegionUnavailableReason,
  createInMemoryDraftStore,
  createSandboxSettingsRegion,
  evaluateSandboxSelection,
  isSandboxRegionVisible,
  resolveSandboxRegionState,
  sandboxCopy,
  sandboxCoverageText,
  sandboxRowDisablement,
  type SandboxDraftStore,
  type SandboxPin,
  type SandboxRegionState,
  type SandboxSelectionOutcome,
  type SandboxSettingsRegion,
  type SandboxSettingsRegionDeps,
  type SandboxSettingsSnapshot,
} from './settings-region'
export { SandboxSettingsSectionView, type SandboxSettingsSectionViewProps } from './views/settings-section-view'
export { createSandboxSettingsPlugin, type SandboxSettingsPluginDeps } from './entry'
