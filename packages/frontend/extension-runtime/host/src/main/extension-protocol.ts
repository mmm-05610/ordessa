import { readFile } from 'node:fs/promises'
import { randomBytes } from 'node:crypto'
import path from 'node:path'
import { confinedFile, type Discovery } from './extensions'
const mime: Record<string, string> = { '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml', '.woff2': 'font/woff2' }
export function protocolHandler(rendererRoot: string, discovery: Discovery) {
  const imports: Record<string, string> = {
    react: '/shared/react.js', 'react/jsx-runtime': '/shared/jsx-runtime.js',
    'react-dom': '/shared/react-dom.js', 'react-dom/client': '/shared/react-dom-client.js',
    '@ordessa/extension-api': '/shared/api.js',
    '@ordessa/ui-components/api': '/shared/ui-components-api.js',
  }
  for (const id of discovery.installed.keys()) imports['@extensions/' + id + '/'] = '/extensions/' + id + '/'
  return async (request: { url: string; method: string }): Promise<Response> => {
    try {
      const url = new URL(request.url)
      if (request.method !== 'GET' || url.protocol !== 'ordessa:' || url.host !== 'desktop' || url.username || url.password || url.search) return new Response('Denied', { status: 403 })
      if (url.pathname === '/' || url.pathname === '/index.html') {
        const nonce = randomBytes(18).toString('base64')
        const map = JSON.stringify({ imports }).replaceAll('<', '\\u003c')
        const html = '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/main.css"><title>Ordessa Desktop</title><script nonce="' + nonce + '" type="importmap">' + map + '</script></head><body><div id="root"></div><script type="module" src="/main.js"></script></body></html>'
        return new Response(html, { headers: {
          'content-type': 'text/html; charset=utf-8',
          'content-security-policy': "default-src 'none'; script-src 'self' 'nonce-" + nonce + "'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; frame-src 'none'; object-src 'none'",
        } })
      }
      const relative = decodeURIComponent(url.pathname.slice(1))
      let root = rendererRoot, file = relative
      if (relative.startsWith('extensions/')) {
        const [, id, ...parts] = relative.split('/')
        const extension = discovery.installed.get(id)
        if (!extension) return new Response('Not enabled', { status: 403 })
        root = extension.root; file = parts.join('/')
      }
      const contentType = mime[path.extname(file)]
      if (!contentType) return new Response('Unsupported file', { status: 415 })
      const bytes = await readFile(await confinedFile(root, file))
      return new Response(new Uint8Array(bytes), { headers: { 'content-type': contentType, 'x-content-type-options': 'nosniff', 'cache-control': 'no-store' } })
    } catch { return new Response('Not found or outside allowed root', { status: 404 }) }
  }
}
