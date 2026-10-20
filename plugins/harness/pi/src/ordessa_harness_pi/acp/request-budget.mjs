import { createHash, randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const CONTRACT = 'ordessa.pi.request-budget'
const PROVIDER = 'deepseek'
const MODEL = 'deepseek-flash'
const API = 'openai-completions'
const API_ORIGIN = 'https://api.deepseek.com'
const API_PATHS = new Set(['/chat/completions', '/v1/chat/completions'])
// Reserve for the provider's full 1M-token input context. Treat every UTF-8
// request byte as one token (256,000), then add a deliberately large 3,072
// token framing allowance for each of at most 128 messages and 64 tools:
// 256,000 + (128 + 64) * 3,072 = 845,824 tokens, below 1,000,000.
const MAX_BODY_BYTES = 256_000
const MAX_MESSAGES = 128
const MAX_TOOLS = 64
const MAX_INPUT_TOKENS = 1_000_000
const MAX_OUTPUT_TOKENS = 16_384
const RESERVED_USD = '0.3196608'
const DIGEST = /^(?:sha256:)?[a-f0-9]{64}$/u
const SHA256_HEX = /^[a-f0-9]{64}$/u

const refused = () => new Error('Pi request budget refused')
const exactObject = (value, keys) => value !== null && typeof value === 'object'
  && !Array.isArray(value) && Object.keys(value).length === keys.length
  && keys.every(key => Object.hasOwn(value, key))
const text = (value, max = 256) => typeof value === 'string' && value.length > 0
  && value.length <= max && value === value.trim()
  && !/[\u0000-\u001f\u007f]/u.test(value)

function configFromEnvironment(value) {
  let config
  try { config = JSON.parse(value) } catch { throw refused() }
  const keys = ['endpoint', 'token', 'plan_digest', 'role', 'phase_id', 'pi_ai_module', 'module_sha256']
  if (!exactObject(config, keys) || !text(config.token, 512)
      || !DIGEST.test(config.plan_digest)
      || !['report', 'review'].includes(config.role)
      || !text(config.phase_id, 128)
      || !text(config.pi_ai_module, 4096)
      || !SHA256_HEX.test(config.module_sha256)) throw refused()
  let endpoint
  let moduleUrl
  try {
    endpoint = new URL(config.endpoint)
    moduleUrl = new URL(config.pi_ai_module)
  } catch { throw refused() }
  if (endpoint.protocol !== 'http:' || endpoint.hostname !== '127.0.0.1'
      || !endpoint.port || !['', '/'].includes(endpoint.pathname)
      || endpoint.username || endpoint.password || endpoint.search || endpoint.hash
      || moduleUrl.protocol !== 'file:' || !moduleUrl.pathname.endsWith('/api/openai-completions.js'))
    throw refused()
  return Object.freeze({ ...config, endpoint: endpoint.origin, piAiModuleUrl: moduleUrl.href })
}

function requestParts(input, init) {
  let url
  let method
  let body
  try {
    url = new URL(input instanceof Request ? input.url : input instanceof URL ? input.href : input)
    method = init?.method ?? (input instanceof Request ? input.method : 'GET')
    body = init?.body ?? (input instanceof Request ? undefined : undefined)
  } catch { throw refused() }
  if (method !== 'POST' || url.protocol !== 'https:' || url.origin !== API_ORIGIN
      || !API_PATHS.has(url.pathname) || url.search || url.hash
      || typeof body !== 'string' || Buffer.byteLength(body, 'utf8') > MAX_BODY_BYTES)
    throw refused()
  let payload
  try { payload = JSON.parse(body) } catch { throw refused() }
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)
      || payload.model !== MODEL || payload.stream !== true
      || (payload.n !== undefined && payload.n !== 1)
      || !Number.isSafeInteger(payload.max_tokens) || payload.max_tokens < 1
      || payload.max_tokens > MAX_OUTPUT_TOKENS
      || Object.hasOwn(payload, 'max_completion_tokens')
      || Object.hasOwn(payload, 'extra_body')
      || (Object.hasOwn(payload, 'thinking')
        && (!exactObject(payload.thinking, ['type']) || payload.thinking.type !== 'disabled'))
      || Object.hasOwn(payload, 'reasoning')
      || Object.hasOwn(payload, 'reasoning_effort')
      || !Array.isArray(payload.messages) || payload.messages.length === 0
      || payload.messages.length > MAX_MESSAGES
      || (Object.hasOwn(payload, 'tools')
        && (!Array.isArray(payload.tools) || payload.tools.length > MAX_TOOLS)))
    throw refused()
  for (const message of payload.messages) {
    if (message === null || typeof message !== 'object' || Array.isArray(message)) throw refused()
    if (!['system', 'user', 'assistant', 'tool'].includes(message.role)
        || Object.keys(message).some(key => !['role', 'content', 'name', 'tool_call_id',
          'tool_calls', 'function_call', 'refusal'].includes(key))) throw refused()
    const content = message.content
    if (content === null || typeof content === 'string') continue
    if (!Array.isArray(content) || content.some(part => part === null
        || typeof part !== 'object' || Array.isArray(part)
        || part.type !== 'text' || typeof part.text !== 'string')) throw refused()
  }
  return { url, payload, requestBytes: Buffer.byteLength(body, 'utf8') }
}

function controlUrl(config, action) {
  return new URL(`/${action}`, config.endpoint).href
}

async function controlRequest({ config, fetchImpl, action, body, expected }) {
  let response
  try {
    response = await fetchImpl(controlUrl(config, action), {
      method: 'POST', redirect: 'error',
      headers: {
        'content-type': 'application/json',
        'x-ordessa-budget-token': config.token,
      },
      body: JSON.stringify(body),
    })
  } catch { throw refused() }
  if (!response || response.redirected === true || response.status !== 200) throw refused()
  let responseText
  try { responseText = await response.text() } catch { throw refused() }
  if (typeof responseText !== 'string' || responseText.length > 4096) throw refused()
  let result
  try { result = JSON.parse(responseText) } catch { throw refused() }
  if (!expected(result)) throw refused()
  return result
}

function validUsage(usage) {
  if (!usage || typeof usage !== 'object') return false
  return ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens'].every(key =>
    Number.isSafeInteger(usage[key]) && usage[key] >= 0)
}

function uploadUsage({ config, fetchImpl, reservation, requestId, pid, usage }) {
  if (!reservation || !validUsage(usage)) return
  const body = {
    contract: `${CONTRACT}.usage/1`, plan_digest: config.plan_digest,
    role: config.role, phase_id: config.phase_id, pid, request_id: requestId,
    reservation_id: reservation, provider: PROVIDER, model: MODEL,
    input_tokens: usage.input, output_tokens: usage.output,
    cache_read_tokens: usage.cacheRead, cache_write_tokens: usage.cacheWrite,
    total_tokens: usage.totalTokens,
  }
  // A usage-report failure never releases the pre-reserved maximum.
  void controlRequest({ config, fetchImpl, action: 'usage', body,
    expected: result => exactObject(result, ['recorded']) && result.recorded === true }).catch(() => {})
}

/** Build the only HTTP fetch Pi's selected DeepSeek provider may use. */
export function createBudgetedFetch({ config, fetchImpl = globalThis.fetch, pid = process.pid }) {
  if (!config || typeof fetchImpl !== 'function' || !Number.isSafeInteger(pid) || pid <= 0)
    throw refused()
  let used = false
  let reservationId
  let requestId
  let requestBytes
  const fetchBudgeted = async (input, init = {}) => {
    if (used) throw refused()
    const request = requestParts(input, init)
    used = true
    requestId = randomUUID()
    requestBytes = request.requestBytes
    const reservation = await controlRequest({
      config, fetchImpl, action: 'reserve',
      body: {
        contract: `${CONTRACT}.reserve/1`, plan_digest: config.plan_digest,
        role: config.role, phase_id: config.phase_id, pid, request_id: requestId,
        provider: PROVIDER, model: MODEL, request_bytes: requestBytes,
        max_input_tokens: MAX_INPUT_TOKENS, max_output_tokens: MAX_OUTPUT_TOKENS,
        reserved_usd: RESERVED_USD,
      },
      expected: result => exactObject(result, ['allowed', 'reservation_id'])
        && result.allowed === true && text(result.reservation_id, 256),
    })
    reservationId = reservation.reservation_id
    let response
    try {
      response = await fetchImpl(input, { ...init, redirect: 'error' })
    } catch { throw refused() }
    if (!response || response.redirected === true
        || (Number.isInteger(response.status) && response.status >= 300 && response.status < 400)
        || typeof response.url !== 'string' || response.url !== request.url.href)
      throw refused()
    return response
  }
  fetchBudgeted.budgetReceipt = () => ({
    requestId, reservationId, requestBytes,
    pid, provider: PROVIDER, model: MODEL,
  })
  return fetchBudgeted
}

/** Return a Pi provider handler that reserves before the only outbound HTTP. */
export function createBudgetedStreamSimple({ config, streamSimple, fetchImpl = globalThis.fetch,
  pid = process.pid }) {
  if (!config || typeof streamSimple !== 'function' || typeof fetchImpl !== 'function') throw refused()
  return (model, context, options = {}) => {
    if (!model || model.provider !== PROVIDER || model.id !== MODEL || model.api !== API
        || model.reasoning !== false || (options.reasoning !== undefined && options.reasoning !== 'off'))
      throw refused()
    const budgetFetch = createBudgetedFetch({ config, fetchImpl, pid })
    const resultStream = streamSimple(model, context, {
      ...options, maxRetries: 0, maxRetryDelayMs: 0, fetch: budgetFetch,
    })
    if (!resultStream || typeof resultStream.result !== 'function') throw refused()
    void resultStream.result().then(result => {
      const receipt = budgetFetch.budgetReceipt()
      if (receipt.reservationId && result?.stopReason !== 'error')
        uploadUsage({ config, fetchImpl, reservation: receipt.reservationId,
          requestId: receipt.requestId, pid, usage: result.usage })
    }).catch(() => {})
    return resultStream
  }
}

async function loadPiApi(config) {
  let source
  try { source = await readFile(fileURLToPath(config.piAiModuleUrl)) } catch { throw refused() }
  const digest = createHash('sha256').update(source).digest('hex')
  if (digest !== config.module_sha256) throw refused()
  let module
  try { module = await import(config.piAiModuleUrl) } catch { throw refused() }
  if (typeof module.streamSimple !== 'function') throw refused()
  return module.streamSimple
}

export async function announceReady({ config, streamSimple, registered, profile,
  fetchImpl = globalThis.fetch, pid = process.pid }) {
  if (!registered || registered.api !== API || registered.streamSimple !== streamSimple
      || !text(profile, 4096) || !profile.startsWith('/')
      || !Number.isSafeInteger(pid) || pid <= 0) throw refused()
  return controlRequest({ config, fetchImpl, action: 'ready', body: {
    contract: `${CONTRACT}.ready/1`, plan_digest: config.plan_digest,
    role: config.role, phase_id: config.phase_id, pid, profile,
    provider: PROVIDER, model: MODEL, api: API, registered: true,
  }, expected: result => exactObject(result, ['ready']) && result.ready === true })
}

/** Pi extension entry point. Main must require its authenticated ready record before prompt. */
export default async function installRequestBudget(pi) {
  let config
  try { config = configFromEnvironment(process.env.ORDESSA_PI_REQUEST_BUDGET) }
  catch { throw refused() }
  const underlyingStreamSimple = await loadPiApi(config)
  const streamSimple = createBudgetedStreamSimple({ config, streamSimple: underlyingStreamSimple })
  pi.registerProvider(PROVIDER, { api: API, streamSimple })
  pi.on('session_start', async (_event, context) => {
    const registered = context?.modelRegistry?.getRegisteredProviderConfig?.(PROVIDER)
    const profile = process.env.PI_CODING_AGENT_DIR
    await announceReady({ config, streamSimple, registered, profile })
  })
}

export const requestBudgetConstants = Object.freeze({
  provider: PROVIDER, model: MODEL, api: API, apiOrigin: API_ORIGIN,
  apiPaths: Object.freeze([...API_PATHS]), maxBodyBytes: MAX_BODY_BYTES,
  maxMessages: MAX_MESSAGES, maxTools: MAX_TOOLS,
  maxInputTokens: MAX_INPUT_TOKENS, maxOutputTokens: MAX_OUTPUT_TOKENS,
  reservedUsd: RESERVED_USD,
})
