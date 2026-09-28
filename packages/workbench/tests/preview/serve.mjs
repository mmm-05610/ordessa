// Static file server for the Workbench preview fixture. Listens on 127.0.0.1
// only and serves this directory. Usage: PORT=4173 node serve.mjs
import { createServer } from 'node:http'
import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import path from 'node:path'

const root = import.meta.dirname
const port = Number(process.env.PORT) || 4173
const types = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.map': 'application/json',
  '.svg': 'image/svg+xml',
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://127.0.0.1')
  let pathname = decodeURIComponent(url.pathname)
  if (pathname === '/') pathname = '/preview.html'
  const file = path.resolve(root, '.' + pathname)
  if (file !== root && !file.startsWith(root + path.sep)) { res.writeHead(403).end('forbidden'); return }
  try {
    const info = await stat(file)
    if (!info.isFile()) { res.writeHead(404).end('not found'); return }
    res.writeHead(200, {
      'content-type': types[path.extname(file)] ?? 'application/octet-stream',
      'content-length': String(info.size),
      'cache-control': 'no-store',
    })
    createReadStream(file).pipe(res)
  } catch {
    res.writeHead(404).end('not found')
  }
})

server.listen(port, '127.0.0.1', () => {
  console.log(`workbench preview fixture: http://127.0.0.1:${port}/preview.html`)
})
