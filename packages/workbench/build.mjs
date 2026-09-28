import { buildExtension } from '../../tooling/build-extension.mjs'
await buildExtension(import.meta.dirname, {"entries":{"entry":"src/entry.tsx"},"licenses":[["react-resizable-panels/LICENSE.md","react-resizable-panels-LICENSE.md"]]})
