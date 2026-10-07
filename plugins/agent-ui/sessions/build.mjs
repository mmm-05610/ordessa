import { buildExtension } from '../../../tooling/build-extension.mjs'
await buildExtension(import.meta.dirname, {"entries":{"entry":"src/entry.tsx"},"licenses":[["radix-ui/LICENSE","radix-ui-LICENSE"]]})
