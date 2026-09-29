/**
 * Optional glue entry.  Activation resolves the two tokens from the host
 * scope; absent tokens mean the glue stays absent — never a fake picker
 * (contracts.md §4).  Composition wiring lands with the C0 integration.
 */
export { createProfileChatGlue, ProfilePickerKey } from './glue'
export { ProfileSelectionStore } from './selection'
