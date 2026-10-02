/** Development maintenance only. Never imported by product startup. */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const args = process.argv.slice(2)
if (args.length !== 2 || args[0] !== '--confirm-existing-ordessa-root'
    || !path.isAbsolute(args[1]) || path.resolve(args[1]) !== args[1]) {
  console.error('Usage: node products/desktop/initialize-existing-data-root.mjs --confirm-existing-ordessa-root /absolute/known/ordessa-root')
  process.exitCode = 1
} else {
  try {
    const result = await build({ entryPoints: [path.join(root, 'apps/desktop/electron/data-root.ts')],
      bundle: true, platform: 'node', format: 'esm', write: false })
    const module = await import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64'))
    await module.initializeExistingDataRoot(args[1], { confirmed: true })
    console.log('Existing Ordessa root initialized; existing contents preserved.')
  } catch (error) {
    console.error(error.message)
    process.exitCode = 1
  }
}
