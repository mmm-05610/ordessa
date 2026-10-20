/**
 * T008-03 registration seam: the host's settings sections and overlay
 * panels are PRESENTED through the Workbench containers via the public
 * API — the presentation registration moves to Workbench, while every
 * business VALUE stays with its owner (settings values live with the host
 * services; nothing here reads or writes them).
 *
 * When no Workbench is composed (the empty-host case), registration is
 * honestly unavailable and the host keeps its own fallback chrome — a
 * missing container is never papered over with a second presentation
 * system pretending to be present.
 */
import type { ResourceScope } from '@ordessa/extension-api'
import type { Workbench, WorkbenchSettingsSection, WorkbenchOverlay } from '@extensions/ordessa.contracts/contract.js'

export interface HostSurfaceDeclarations {
  /** Host-owned settings sections (presentation only; values stay put). */
  settings: ReadonlyArray<Omit<WorkbenchSettingsSection, 'component'> & { component: unknown }>
  /** Host panels presented as Workbench overlays. */
  overlays: ReadonlyArray<WorkbenchOverlay>
}

export interface HostSurfaceRegistration {
  readonly presented: boolean
  readonly disposers: ReadonlyArray<() => void>
  release(): void
}

export function registerHostSurfaces(
  workbench: Workbench | undefined,
  declarations: HostSurfaceDeclarations,
  scope?: ResourceScope,
): HostSurfaceRegistration {
  // Registrations are scope-owned through the composition face
  // (WorkbenchComposition.forScope) — never a bare registry grab.
  const composition = workbench?.composition
  const registrationFace = composition && scope !== undefined ? composition.forScope(scope) : undefined
  if (workbench === undefined || registrationFace === undefined) {
    // Honest absence: no Workbench container (or no scope), so nothing is
    // presented through it. The host fallback chrome keeps rendering.
    return {
      presented: false,
      disposers: [],
      release: () => undefined,
    }
  }
  const disposers: Array<() => void> = []
  for (const section of declarations.settings) {
    const handle = registrationFace.addSettingsSection(section as WorkbenchSettingsSection)
    disposers.push(() => handle.dispose())
  }
  for (const overlay of declarations.overlays) {
    const handle = registrationFace.addOverlay(overlay)
    disposers.push(() => handle.dispose())
  }
  return {
    presented: true,
    disposers,
    release: () => {
      for (const dispose of disposers.splice(0)) dispose()
    },
  }
}
