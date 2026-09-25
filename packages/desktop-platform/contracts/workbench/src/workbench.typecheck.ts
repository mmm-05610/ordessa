import type {
  Workbench,
  WorkbenchComposition,
  WorkbenchModule,
  WorkbenchOverlay,
  WorkbenchSettingsSection,
} from './workbench'

// This file is type-checked with the desktop sources but is not bundled into
// the runtime contract. It pins both the new shapes and v1 compatibility.
declare const legacy: Workbench
const optionalComposition: WorkbenchComposition | undefined = legacy.composition
void optionalComposition

const moduleContribution = {
  id: 'example.chat', title: 'Chat', homeViewId: 'example.chat.main', sidebarViewId: 'example.chat.sidebar',
} satisfies WorkbenchModule
void moduleContribution

const overlayContribution = {
  id: 'example.chat.picker', title: 'Select a project', presentation: 'popover', component: () => null,
} satisfies WorkbenchOverlay
void overlayContribution

const settingsContribution = {
  id: 'example.chat.settings', title: 'Chat', component: () => null,
} satisfies WorkbenchSettingsSection
void settingsContribution

// @ts-expect-error A module without a home view cannot be activated.
const missingHomeView: WorkbenchModule = { id: 'broken', title: 'Broken' }
void missingHomeView

// @ts-expect-error An overlay must choose one of the supported presentations.
const unsupportedOverlay: WorkbenchOverlay = { id: 'broken', title: 'Broken', presentation: 'window', component: () => null }
void unsupportedOverlay
