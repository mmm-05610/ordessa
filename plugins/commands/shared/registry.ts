// Thin forward (T008-10): the registry helper moved to the extension runtime.
// Importing from here keeps resolving to the SAME objects.
export { registry, ordered } from '@ordessa/extension-host/services/command-registry'
