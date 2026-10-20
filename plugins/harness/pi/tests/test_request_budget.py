"""Isolated contract tests for the Pi request-budget extension; no model/runtime calls."""
from pathlib import Path
import json
import subprocess


EXTENSION = Path(__file__).parents[1] / "src/ordessa_harness_pi/acp/request-budget.mjs"
IMPORT = json.dumps(EXTENSION.as_uri())


def run_node(body: str) -> None:
    source = f"""
import assert from 'node:assert/strict'
import {{ createBudgetedFetch, createBudgetedStreamSimple, announceReady }} from {IMPORT}
const config = {{ endpoint: 'http://127.0.0.1:43127', token: 'local-capability',
  plan_digest: 'sha256:' + 'a'.repeat(64), role: 'report', phase_id: 'phase-once' }}
const payload = {{ model: 'deepseek-flash', messages: [{{ role: 'user', content: 'bounded text' }}],
  max_tokens: 16384, stream: true, n: 1 }}
const apiUrl = 'https://api.deepseek.com/chat/completions'
const upstreamResponse = (url = apiUrl, status = 200, redirected = false) => ({{
  url, status, redirected, text: async () => ''
}})
const jsonResponse = value => ({{ status: 200, redirected: false,
  text: async () => JSON.stringify(value) }})
{body}
"""
    subprocess.run(["node", "--input-type=module", "--eval", source], check=True,
                   cwd=EXTENSION.parents[6], capture_output=True, text=True)


def test_denied_reservation_never_reaches_deepseek():
    run_node("""
let outbound = 0
const fetchImpl = async (url, init) => {
  if (String(url).endsWith('/reserve')) return jsonResponse({ allowed: false })
  outbound += 1
  return upstreamResponse()
}
const guarded = createBudgetedFetch({ config, fetchImpl, pid: 101 })
await assert.rejects(guarded(apiUrl, { method: 'POST', body: JSON.stringify(payload) }))
assert.equal(outbound, 0)
""")


def test_actual_pi_api_payload_and_streamed_cache_usage_stay_behind_budget():
    run_node("""
const { streamSimple: original } = await import('file:///home/maoqh/.pi/agent/install/releases/0.86.1/node_modules/@earendil-works/pi-ai/dist/api/openai-completions.js')
let outbound = 0
let reservations = 0
const recorded = []
const fetchImpl = async (url, init) => {
  if (String(url).endsWith('/reserve')) {
    reservations += 1
    return jsonResponse({allowed:true,reservation_id:'actual-pi-shape'})
  }
  if (String(url).endsWith('/usage')) {
    recorded.push(JSON.parse(init.body))
    return jsonResponse({recorded:true})
  }
  outbound += 1
  const request = JSON.parse(init.body)
  assert.equal(request.thinking.type, 'disabled')
  assert.equal(request.max_tokens, 16384)
  assert.equal(init.redirect, 'error')
  const chunks = [
    {id:'fixture',object:'chat.completion.chunk',choices:[{index:0,delta:{role:'assistant',content:'{}'},finish_reason:null}]},
    {id:'fixture',object:'chat.completion.chunk',choices:[{index:0,delta:{},finish_reason:'stop'}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12,prompt_cache_hit_tokens:4,prompt_cache_miss_tokens:6}}
  ]
  const response = new Response(chunks.map(x=>'data: '+JSON.stringify(x)+'\\n\\n').join('')+'data: [DONE]\\n\\n',
    {status:200,headers:{'content-type':'text/event-stream'}})
  Object.defineProperty(response,'url',{value:String(url)})
  return response
}
const guarded = createBudgetedStreamSimple({config,streamSimple:original,fetchImpl,pid:101})
const result = await guarded({provider:'deepseek',id:'deepseek-flash',name:'isolated actual Pi',
  api:'openai-completions',baseUrl:'https://api.deepseek.com',reasoning:false,input:['text'],
  contextWindow:1000000,maxTokens:16384,cost:{input:.3,output:1.2,cacheRead:.006,cacheWrite:0},
  samplingParams:{thinking:{type:'disabled'},response_format:{type:'json_object'}},
  compat:{supportsStore:false,supportsDeveloperRole:false,maxTokensField:'max_tokens'}},
  {messages:[{role:'user',content:[{type:'text',text:'isolated fixture'}],timestamp:1}]},
  {apiKey:'non-secret-isolated-fixture',reasoning:'off'}).result()
assert.notEqual(result.stopReason,'error',result.errorMessage)
await new Promise(resolve=>setImmediate(resolve))
assert.equal(outbound,1)
assert.equal(reservations,1)
assert.equal(recorded.length,1)
assert.equal(recorded[0].input_tokens,6)
assert.equal(recorded[0].cache_read_tokens,4)
assert.equal(recorded[0].output_tokens,2)
assert.equal(recorded[0].total_tokens,12)
""")


def test_fourth_request_is_denied_across_separate_pi_process_handlers():
    run_node("""
let reservations = 0
let outbound = 0
const fetchImpl = async (url, init) => {
  if (String(url).endsWith('/reserve')) {
    reservations += 1
    return jsonResponse(reservations <= 3
      ? { allowed: true, reservation_id: `r-${reservations}` } : { allowed: false })
  }
  outbound += 1
  return upstreamResponse()
}
for (let pid = 201; pid <= 204; pid += 1) {
  const guarded = createBudgetedFetch({ config, fetchImpl, pid })
  if (pid === 204)
    await assert.rejects(guarded(apiUrl, { method: 'POST', body: JSON.stringify(payload) }))
  else await guarded(apiUrl, { method: 'POST', body: JSON.stringify(payload) })
}
assert.equal(reservations, 4)
assert.equal(outbound, 3)
""")


def test_wrong_url_model_output_limit_or_nontext_input_is_rejected_before_reserve():
    run_node("""
let calls = 0
const fetchImpl = async () => { calls += 1; return jsonResponse({ allowed: true, reservation_id: 'r' }) }
const invalid = [
  [apiUrl.replace('api.deepseek.com', 'example.com'), payload],
  [apiUrl + '?redirect=1', payload],
  [apiUrl, { ...payload, model: 'other-model' }],
  [apiUrl, { ...payload, max_tokens: 16385 }],
  [apiUrl, { ...payload, stream: false }],
  [apiUrl, { ...payload, n: 2 }],
  [apiUrl, { ...payload, thinking: { type: 'enabled' } }],
  [apiUrl, { ...payload, thinking: { type: 'disabled', extra: true } }],
  [apiUrl, { ...payload, messages: Array.from({ length: 129 }, () => ({ role: 'user', content: 'x' })) }],
  [apiUrl, { ...payload, tools: Array.from({ length: 65 }, () => ({})) }],
  [apiUrl, { ...payload, messages: [{ role: 'user', content: [{ type: 'image_url', image_url: 'x' }] }] }],
  [apiUrl, { ...payload, messages: [{ role: 'user', content: 'x'.repeat(256001) }] }],
]
for (const [url, request] of invalid) {
  const guarded = createBudgetedFetch({ config, fetchImpl, pid: 301 })
  await assert.rejects(guarded(url, { method: 'POST', body: JSON.stringify(request) }))
}
assert.equal(calls, 0)
""")


def test_disabled_thinking_is_accepted_and_reserved_before_outbound_request():
    run_node("""
let outbound = 0
const fetchImpl = async (url, init) => {
  if (String(url).endsWith('/reserve')) return jsonResponse({ allowed: true, reservation_id: 'r-disabled' })
  outbound += 1
  return upstreamResponse()
}
const guarded = createBudgetedFetch({ config, fetchImpl, pid: 351 })
await guarded(apiUrl, { method: 'POST', body: JSON.stringify({ ...payload, thinking: { type: 'disabled' } }) })
assert.equal(outbound, 1)
""")


def test_missing_local_authority_fails_closed_before_model_http():
    run_node("""
let outbound = 0
const fetchImpl = async url => {
  if (String(url).endsWith('/reserve')) throw new Error('unavailable')
  outbound += 1
  return upstreamResponse()
}
const guarded = createBudgetedFetch({ config, fetchImpl, pid: 401 })
await assert.rejects(guarded(apiUrl, { method: 'POST', body: JSON.stringify(payload) }))
assert.equal(outbound, 0)
""")


def test_redirects_are_rejected_and_never_followed():
    run_node("""
let outbound = 0
let redirectMode
const fetchImpl = async (url, init) => {
  if (String(url).endsWith('/reserve')) return jsonResponse({ allowed: true, reservation_id: 'r' })
  outbound += 1
  redirectMode = init.redirect
  return upstreamResponse('https://attacker.invalid/collect', 302, true)
}
const guarded = createBudgetedFetch({ config, fetchImpl, pid: 501 })
await assert.rejects(guarded(apiUrl, { method: 'POST', body: JSON.stringify(payload), redirect: 'follow' }))
assert.equal(redirectMode, 'error')
assert.equal(outbound, 1)
""")


def test_usage_reports_only_confirmed_counts_and_never_refunds_reservation():
    run_node("""
const controls = []
const upstream = []
const fetchImpl = async (url, init) => {
  const target = String(url)
  if (target.startsWith(config.endpoint)) {
    const body = JSON.parse(init.body)
    controls.push({ target, body, headers: init.headers })
    if (target.endsWith('/reserve')) return jsonResponse({ allowed: true, reservation_id: 'fixed-r' })
    return jsonResponse({ recorded: true })
  }
  upstream.push({ target, init })
  return upstreamResponse()
}
const streamSimple = (_model, _context, options) => {
  assert.equal(options.maxRetries, 0)
  assert.equal(options.maxRetryDelayMs, 0)
  const result = options.fetch(apiUrl, { method: 'POST', body: JSON.stringify(payload),
    headers: { authorization: 'provider-secret' } }).then(() => ({ stopReason: 'stop', usage: {
      input: 8, output: 3, cacheRead: 5, cacheWrite: 2, totalTokens: 18,
      cost: { total: 0.0001 }, prompt: 'must not be sent'
    } }))
  return { result: () => result }
}
const guarded = createBudgetedStreamSimple({ config, streamSimple, fetchImpl, pid: 601 })
const result = guarded({ provider: 'deepseek', id: 'deepseek-flash', api: 'openai-completions',
  reasoning: false }, { messages: [] }, { reasoning: 'off' })
await result.result()
await new Promise(resolve => setImmediate(resolve))
const reserve = controls.find(item => item.target.endsWith('/reserve'))
const usage = controls.find(item => item.target.endsWith('/usage'))
assert.equal(reserve.body.reserved_usd, '0.3196608')
assert.equal(reserve.body.max_input_tokens, 1000000)
assert.equal(reserve.body.max_output_tokens, 16384)
assert.equal(usage.body.input_tokens, 8)
assert.equal(usage.body.cache_read_tokens, 5)
assert.equal(usage.body.cache_write_tokens, 2)
assert.equal(Object.hasOwn(usage.body, 'prompt'), false)
assert.equal(JSON.stringify(usage.body).includes('provider-secret'), false)
assert.equal(JSON.stringify(controls).includes('bounded text'), false)
assert.equal(upstream.length, 1)
assert.equal(upstream[0].target, apiUrl)
assert.equal(upstream[0].init.redirect, 'error')
""")


def test_ready_requires_registered_wrapper_identity_and_posts_profile_binding():
    run_node("""
const sent = []
const fetchImpl = async (url, init) => {
  sent.push({ url: String(url), body: JSON.parse(init.body) })
  return jsonResponse({ ready: true })
}
const streamSimple = () => {}
await announceReady({ config, streamSimple,
  registered: { api: 'openai-completions', streamSimple },
  profile: '/unit/private/profile', pid: 701, fetchImpl })
assert.equal(sent.length, 1)
assert.equal(sent[0].url, config.endpoint + '/ready')
assert.equal(sent[0].body.pid, 701)
assert.equal(sent[0].body.profile, '/unit/private/profile')
assert.equal(sent[0].body.role, 'report')
await assert.rejects(announceReady({ config, streamSimple,
  registered: { api: 'openai-completions', streamSimple: () => {} },
  profile: '/unit/private/profile', pid: 702, fetchImpl }))
assert.equal(sent.length, 1)
""")
