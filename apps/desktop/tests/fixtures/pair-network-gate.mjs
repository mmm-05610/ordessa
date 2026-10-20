// C-0074: classify complete private trace/NetLog; return only categories and counts.
import assert from 'node:assert/strict'

const hashAnnotation = value => [...value].reduce((n, c) => (n * 31 + c.charCodeAt(0)) % 138003713, 0)
const dictionaryAnnotation = hashAnnotation('spellcheck_hunspell_dictionary')
// Fixed Electron 40.10.2 / Chromium 144.0.7559.236 dictionary source.
// Only this source's one observed HTTPS resource redirect is background traffic.
const dictionaryOrigin = 'https://redirector.gvt1.com'
const dictionaryPath = /^\/edgedl\/chrome\/dict\/[^/]+\.bdic$/
const sensitiveQueryName = /(?:token|auth|bearer|secret|password|credential|prompt|message|session|workspace|payload|body)/i
const sensitiveRequestField = /^(?:authorization|proxy_authorization|cookie|request_cookie|bearer|token|secret|credential|password|request_?body|upload(?:_?data)?|post_?data|prompt|message)$/i
const hasSensitiveRequestField = value => {
  if (typeof value === 'string') return /(?:authorization|cookie)\s*:|\bbearer\s+/i.test(value)
  if (Array.isArray(value)) return value.some(hasSensitiveRequestField)
  if (!value || typeof value !== 'object') return false
  return Object.entries(value).some(([name, item]) => sensitiveRequestField.test(name) || hasSensitiveRequestField(item))
}
const probeAddress = '2001:4860:4860::8888' // Chromium 144 host_resolver_manager.cc kIPv6ProbeAddress.
const key = source => Number.isInteger(source?.type) && Number.isInteger(source?.id) ? `${source.type}:${source.id}` : null
const loopback = value => value.startsWith('127.') || value === '::1' || value.startsWith('::ffff:127.')
const addrIn = (value, address, port) => {
  if (typeof value === 'string') return value === `${address}:${port}` || value === `[${address}]:${port}`
  if (Array.isArray(value)) return value.some(v => addrIn(v, address, port))
  if (value && typeof value === 'object') return Object.values(value).some(v => addrIn(v, address, port))
  return false
}
const deps = (params, out = []) => {
  if (!params || typeof params !== 'object') return out
  if (Array.isArray(params)) { for (const item of params) deps(item, out); return out }
  for (const [name, value] of Object.entries(params)) {
    if (name === 'source_dependency') { const source = key(value); if (source) out.push(source) }
    else deps(value, out)
  }
  return out
}
const reachable = (edges, start, target) => {
  const queue = [start], seen = new Set(queue)
  while (queue.length) for (const next of edges.get(queue.shift()) ?? []) {
    if (next === target) return true
    if (!seen.has(next)) { seen.add(next); queue.push(next) }
  }
  return false
}

export function parsePairTraces(files) {
  const parents = new Map(), execs = new Set(), sockets = [], connections = [], sends = [], closes = []
  let stamped = true
  for (const [filename, content] of Object.entries(files)) {
    const tid = Number(filename.match(/^electron-connect\.trace\.(\d+)$/)?.[1])
    if (!Number.isInteger(tid)) continue
    for (const line of content.split('\n')) {
      if (!line.trim()) continue
      const prefix = line.match(/^(\d+\.\d+)\s/)
      if (!prefix) { stamped = false; continue }
      const time = Number(prefix[1]) * 1000
      if (line.includes('execve(') && /= 0(?:\s|$)/.test(line)) execs.add(tid)
      const child = line.match(/\b(?:clone|clone3|fork|vfork)\(.*\)\s+=\s+(\d+)(?:\s|$)/)
      if (child) parents.set(Number(child[1]), tid)
      const socket = line.match(/\bsocket\(AF_INET6?,\s*(SOCK_DGRAM|SOCK_STREAM)[^)]*\)\s+=\s+(\d+)(?:\s|$)/)
      if (socket) sockets.push({ tid, time, fd: Number(socket[2]), transport: socket[1] === 'SOCK_DGRAM' ? 'udp' : 'tcp' })
      const send = line.match(/\b(?:sendto|sendmsg|sendmmsg)\((0x[0-9a-f]+|\d+),/i)
      if (send) sends.push({ tid, time, fd: Number(send[1]) })
      const close = line.match(/\bclose\((\d+)\)/)
      if (close) closes.push({ tid, time, fd: Number(close[1]) })
      if (!line.includes('connect(') || !/AF_INET6?/.test(line)) continue
      const fd = Number(line.match(/\bconnect\((\d+),/)?.[1])
      const address = line.match(/sin_addr=inet_addr\("([^"]+)"\)/)?.[1]
        ?? line.match(/inet_pton\(AF_INET6, "([^"]+)"/)?.[1]
      const port = Number(line.match(/sin6?_port=htons\((\d+)\)/)?.[1])
      if (!address || !Number.isInteger(fd) || !Number.isInteger(port)) continue
      connections.push({ tid, time, fd, address, port, returnedZero: /= 0(?:\s|$)/.test(line) })
    }
  }
  const processRoot = tid => {
    const seen = new Set()
    while (Number.isInteger(tid) && !seen.has(tid)) {
      seen.add(tid)
      if (execs.has(tid)) return tid
      tid = parents.get(tid)
    }
    return null
  }
  return { stamped, connections: connections.map(connection => {
    const root = processRoot(connection.tid)
    const candidates = sockets.filter(item => root !== null && processRoot(item.tid) === root &&
      item.fd === connection.fd && item.time <= connection.time &&
      !closes.some(c => processRoot(c.tid) === root && c.fd === item.fd && c.time > item.time && c.time < connection.time))
    const socket = candidates.sort((a, b) => b.time - a.time)[0]
    const after = socket ? sends.filter(item => processRoot(item.tid) === root && item.fd === connection.fd &&
      item.time >= socket.time && !closes.some(c => processRoot(c.tid) === root && c.fd === item.fd && c.time > socket.time && c.time < item.time)) : []
    return { ...connection, transport: socket?.transport ?? 'unknown', sendCalls: after.length, local: loopback(connection.address) }
  }), rawSendCalls: sends.length }
}

export function classifyPairNetwork(files, netlog, serverOrigin) {
  const trace = parsePairTraces(files)
  if (!trace.stamped || !Array.isArray(netlog?.events) || !Number.isFinite(Number(netlog.constants?.timeTickOffset)))
    return { pass: false, reason: 'INCOMPLETE_EVIDENCE' }
  const server = new URL(serverOrigin)
  assert.equal(server.protocol, 'http:')
  assert.ok(loopback(server.hostname), 'Server origin must be loopback')
  const types = netlog.constants.logEventTypes ?? {}, sourceTypes = netlog.constants.logSourceType ?? {}
  if (![types.TCP_CONNECT, types.UDP_CONNECT, types.UDP_BYTES_SENT, types.SOCKET_BYTES_SENT,
    types.HOST_RESOLVER_MANAGER_IPV6_REACHABILITY_CHECK, types.URL_REQUEST_REDIRECTED,
    sourceTypes.URL_REQUEST].every(Number.isInteger))
    return { pass: false, reason: 'NETLOG_CONSTANTS_MISSING' }
  const eventsBySource = new Map(), edges = new Map()
  for (const event of netlog.events) {
    const source = key(event.source)
    if (!source) continue
    const items = eventsBySource.get(source) ?? []
    items.push(event); eventsBySource.set(source, items)
    for (const dep of deps(event.params)) {
      if (!edges.has(source)) edges.set(source, new Set())
      if (!edges.has(dep)) edges.set(dep, new Set())
      edges.get(source).add(dep); edges.get(dep).add(source)
    }
  }
  const dictionaryRequests = [], unknownRequests = []
  for (const [source, events] of eventsBySource) {
    if (!source.startsWith(`${sourceTypes.URL_REQUEST}:`)) continue
    const urls = events.flatMap(event => typeof event.params?.url === 'string' ? [event.params.url] : [])
    if (!urls.length) { unknownRequests.push(source); continue }
    const methods = events.flatMap(event => typeof event.params?.method === 'string' ? [event.params.method] : [])
    const annotation = events.map(event => event.params?.traffic_annotation).find(Number.isInteger)
    const redirects = events.filter(event => event.type === types.URL_REQUEST_REDIRECTED)
    const distinctUrls = new Set(urls)
    const allServer = annotation !== dictionaryAnnotation && redirects.length === 0 && distinctUrls.size === 1 &&
      methods.includes('POST') && methods.every(method => method === 'POST') &&
      urls.every(raw => { try { const url = new URL(raw); return url.origin === server.origin &&
        url.pathname.startsWith('/wire/v1/') && !url.search && !url.hash && !url.username && !url.password } catch { return false } })
    const initial = (() => { try { return new URL(urls[0]) } catch { return null } })()
    const redirect = redirects[0]
    const redirectLocation = typeof redirect?.params?.location === 'string' ? redirect.params.location : null
    const redirectFollowed = redirects.length === 0 ? distinctUrls.size === 1 :
      redirects.length === 1 && distinctUrls.size === 2 && redirectLocation !== urls[0] &&
      events.slice(events.indexOf(redirect) + 1).some(event => event.params?.url === redirectLocation)
    const resourceUrls = redirects.length === 0 ? urls : [...urls, redirectLocation]
    const dictionary = annotation === dictionaryAnnotation && methods.includes('GET') && methods.every(m => m === 'GET') &&
      redirects.length <= 1 && redirectFollowed && !events.some(event => hasSensitiveRequestField(event.params)) &&
      initial?.origin === dictionaryOrigin && dictionaryPath.test(initial.pathname) &&
      !initial.search && !initial.hash && !initial.username && !initial.password &&
      resourceUrls.every(raw => { try { const url = new URL(raw); return url.protocol === 'https:' &&
        url.pathname.endsWith('.bdic') && !url.username && !url.password &&
        [...url.searchParams.keys()].every(name => !sensitiveQueryName.test(name)) } catch { return false } })
    if (allServer) continue
    if (dictionary) dictionaryRequests.push(source)
    else unknownRequests.push(source)
  }
  const categories = { server: 0, udpProbe: 0, dictionaryProxy: 0, localUdp: 0, remoteTcp: 0, remoteSend: 0, unknown: 0 }
  for (const connection of trace.connections) {
    const candidates = netlog.events.filter(event => (event.type === types.TCP_CONNECT || event.type === types.UDP_CONNECT) &&
      Math.abs(Number(event.time) + Number(netlog.constants.timeTickOffset) - connection.time) <= 1000 &&
      (addrIn(event.params?.address_list, connection.address, connection.port) || addrIn(event.params?.address, connection.address, connection.port)))
    const unique = [...new Map(candidates.map(event => [`${event.type}:${key(event.source)}`, event])).values()]
    const matched = unique.length === 1 ? unique[0] : null
    const loggedTransport = matched?.type === types.TCP_CONNECT ? 'tcp' : matched?.type === types.UDP_CONNECT ? 'udp' : 'unknown'
    if (connection.transport === 'unknown' || loggedTransport === 'unknown' || connection.transport !== loggedTransport) { categories.unknown++; continue }
    if (!connection.local && connection.transport === 'tcp') { categories.remoteTcp++; continue }
    if (!connection.local && connection.sendCalls > 0) { categories.remoteSend++; continue }
    if (!connection.local && connection.transport === 'udp' && connection.address === probeAddress &&
        !netlog.events.some(event => event.type === types.UDP_BYTES_SENT && key(event.source) === key(matched.source)) &&
        netlog.events.some(event => event.type === types.HOST_RESOLVER_MANAGER_IPV6_REACHABILITY_CHECK &&
          Math.abs(Number(event.time) + Number(netlog.constants.timeTickOffset) - connection.time) <= 2000)) {
      categories.udpProbe++; continue
    }
    if (!connection.local) { categories.unknown++; continue }
    if (connection.transport === 'udp') {
      if (connection.sendCalls === 0 && !netlog.events.some(event => event.type === types.UDP_BYTES_SENT &&
          key(event.source) === key(matched.source)) && netlog.events.some(event =>
            event.type === types.HOST_RESOLVER_MANAGER_IPV6_REACHABILITY_CHECK &&
            Math.abs(Number(event.time) + Number(netlog.constants.timeTickOffset) - connection.time) <= 2000)) categories.localUdp++
      else categories.unknown++
      continue
    }
    if (connection.address === server.hostname && connection.port === Number(server.port)) { categories.server++; continue }
    const matchedSource = key(matched.source)
    const isDictionaryProxy = dictionaryRequests.some(request => reachable(edges, request, matchedSource)) &&
      netlog.events.some(event => event.type === types.SOCKET_BYTES_SENT && reachable(edges, matchedSource, key(event.source)))
    if (isDictionaryProxy) categories.dictionaryProxy++
    else categories.unknown++
  }
  const pass = categories.server > 0 && categories.remoteTcp === 0 && categories.remoteSend === 0 &&
    categories.unknown === 0 && unknownRequests.length === 0
  return { pass, categories, dictionaryRequests: dictionaryRequests.length, unknownRequests: unknownRequests.length,
    connectCount: trace.connections.length, rawSendCalls: trace.rawSendCalls }
}

export function credentialDestinationAllowed(url, serverOrigin, bearerPresent) {
  if (!bearerPresent) return true
  try {
    const server = new URL(serverOrigin), destination = new URL(url)
    return server.protocol === 'http:' && loopback(server.hostname) && !!server.port &&
      destination.origin === server.origin && !destination.username && !destination.password
  } catch { return false }
}
