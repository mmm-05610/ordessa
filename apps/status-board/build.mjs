import { build } from 'esbuild'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('.', import.meta.url))
export async function buildStatusBoard(outdir = root + 'dist') {
  await mkdir(outdir, { recursive: true })
  await build({ entryPoints: [root + 'src/main.tsx'], outdir, entryNames: 'main', bundle: true, platform: 'browser', format: 'esm', target: 'chrome132', jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"' } })
  const html = (await readFile(root + 'index.html', 'utf8')).replace('./src/main.tsx', './main.js').replace('</head>', '<link rel="stylesheet" href="./main.css"></head>')
  await writeFile(outdir + '/index.html', html)
}
if (process.argv[1] === fileURLToPath(import.meta.url)) await buildStatusBoard()
