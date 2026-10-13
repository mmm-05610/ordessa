/**
 * Offline gate for qwen runs that must not reach any non-loopback address.
 *
 * This is a reviewed test asset, deliberately NOT part of the production
 * deployment: production qwen talks to the official DeepSeek root, which is what
 * the deployment template records. A gate that points Pi at a local fake
 * endpoint preloads this module into the adapter process (NODE_OPTIONS) so the
 * claim "this run only reached loopback" is enforced at the socket layer rather
 * than inferred from the configuration.
 *
 * Enforcement is fail closed: the connection throws before any DNS lookup or
 * TCP connect happens to a non-loopback destination, so nothing leaves the
 * guest and the adapter fails immediately instead of silently succeeding.
 *
 * When AGENTBOX_EGRESS_AUDIT names a path (the gate points it at the project
 * workspace so the host can read it back), every load and every refusal is
 * appended there. The audit record holds host and port only - never a
 * credential, header, or request body.
 */
const dns = require("node:dns")
const fs = require("node:fs")
const net = require("node:net")
const tls = require("node:tls")

const AUDIT = process.env.AGENTBOX_EGRESS_AUDIT
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "::1", "localhost", "ip6-localhost"])

function record(line) {
  if (!AUDIT) return
  try {
    fs.appendFileSync(AUDIT, `${line}\n`)
  } catch {
    // Auditing must never be the reason a refusal is missed.
  }
}

function isLoopbackHost(host) {
  if (host === undefined || host === null || host === "") return true
  return LOOPBACK_HOSTS.has(String(host).toLowerCase())
}

function refuse(kind, host, port) {
  const where = `${host ?? "?"}:${port ?? "?"}`
  record(`denied ${kind} ${where}`)
  const error = new Error(`AGENTBOX_EGRESS_BLOCKED: ${kind} to ${where} is not loopback`)
  error.code = "AGENTBOX_EGRESS_BLOCKED"
  throw error
}

/** One destination may be given as a port plus host, an options object, or a path. */
function destination(args) {
  if (typeof args[0] === "object" && args[0] !== null) return { host: args[0].host, port: args[0].port, path: args[0].path }
  return { host: args[1], port: args[0], path: undefined }
}

const connect = net.Socket.prototype.connect
net.Socket.prototype.connect = function guardedConnect(...args) {
  const { host, port, path } = destination(args)
  // A unix domain socket is local IPC, not egress.
  if (path === undefined && !isLoopbackHost(host)) refuse("connect", host, port)
  return connect.apply(this, args)
}

const tlsConnect = tls.connect
tls.connect = function guardedTlsConnect(...args) {
  const { host, port, path } = destination(args)
  if (path === undefined && !isLoopbackHost(host)) refuse("tls", host, port)
  return tlsConnect.apply(this, args)
}

const lookup = dns.lookup
dns.lookup = function guardedLookup(hostname, ...rest) {
  if (!isLoopbackHost(hostname)) refuse("dns", hostname, undefined)
  return lookup.call(dns, hostname, ...rest)
}
dns.promises.lookup = function guardedPromiseLookup(hostname, ...rest) {
  if (!isLoopbackHost(hostname)) refuse("dns", hostname, undefined)
  return lookup.call(dns.promises, hostname, ...rest)
}

record(`guard-loaded pid=${process.pid}`)
