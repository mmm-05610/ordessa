// One authorized comparison POST, independent of every previous Unit attempt.
// Never log headers, secret values, error messages, response bodies or stacks.
import { OpenAI } from '/home/maoqh/.pi/agent/install/releases/0.86.1/node_modules/openai/client.mjs';
import { configureHttpDispatcher } from '/home/maoqh/.pi/agent/install/releases/0.86.1/node_modules/@earendil-works/pi-coding-agent/dist/core/http-dispatcher.js';
import { randomUUID, createHash } from 'node:crypto';
const report = {
  model: 'glm-5.3-flash', endpoint: 'https://opencode.ai/zen/go/v1',
  comparison: 'installed OpenAI SDK with installed Pi HTTP dispatcher; isolated launch environment',
  maxRetries: 0, max_tokens: 32, stream: true, post_intents: 0,
  differences_from_native_prompt: ['minimal single user message; no system/tools/history',
    'no Pi User-Agent or x-opencode-session wrapper; SDK default headers',
    '25 second SDK timeout; native idle timeout defaults 300 seconds'],
  proxy_environment_present: ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY',
    'http_proxy','https_proxy','all_proxy','no_proxy'].filter(k => Boolean(process.env[k])),
  node_version: process.version,
};
const selectedMaxTokens = Number(process.argv[2] || 32);
if (!Number.isInteger(selectedMaxTokens) || selectedMaxTokens < 1 || selectedMaxTokens > 4096)
  throw new Error('diagnostic_token_bound_invalid');
report.max_tokens = selectedMaxTokens;
const sessionHeaderEnabled = process.argv[3] === 'session-header';
const session = sessionHeaderEnabled ? `ordessa-go-diagnostic-${randomUUID()}` : undefined;
report.opencode_session_header_present = sessionHeaderEnabled;
if (session) {
  report.session_identifier_sha256 = createHash('sha256').update(session).digest('hex');
  report.differences_from_native_prompt[1] = 'own ordessa-go-diagnostic/1 User-Agent; independent diagnostic x-opencode-session';
}
function safeProviderError(value) {
  if (!value || typeof value !== 'object') return undefined;
  const error = value.error && typeof value.error === 'object' ? value.error : value;
  const result = {};
  for (const field of ['type','code','param','message']) {
    if (typeof error[field] !== 'string' && typeof error[field] !== 'number') continue;
    let text = String(error[field]);
    const secret = process.env.OPENCODE_API_KEY;
    if (secret) text = text.split(secret).join('[REDACTED]');
    text = text.replace(/Bearer\s+[^\s"']+/gi, 'Bearer [REDACTED]');
    result[field] = text.slice(0, 1000);
    if (text.length > 1000) result.message_truncated = true;
  }
  return result;
}
function safeChain(error) {
  const chain = [], seen = new Set();
  for (let e = error; e && !seen.has(e) && chain.length < 8; e = e.cause) {
    seen.add(e);
    const item = {};
    for (const field of ['name','code','errno','syscall']) {
      const v = e[field];
      if (typeof v === 'number' || (typeof v === 'string' && /^[A-Za-z0-9_.-]{1,100}$/.test(v))) item[field] = v;
    }
    if (Number.isInteger(e.status)) item.status = e.status;
    if (Array.isArray(e.errors)) item.errors = e.errors.map(safeChain);
    chain.push(item);
  }
  return chain;
}
configureHttpDispatcher();
const actualFetch = globalThis.fetch;
const client = new OpenAI({
  apiKey: process.env.OPENCODE_API_KEY, baseURL: report.endpoint,
  maxRetries: 0, timeout: 25000,
  defaultHeaders: session ? { 'x-opencode-session': session,
    'User-Agent': 'ordessa-go-diagnostic/1' } : undefined,
  fetch: async (url, init) => {
    report.post_intents += 1;
    report.phase = 'fetch';
    try {
      const response = await actualFetch(url, init);
      report.http_status = response.status;
      report.phase = 'http_response';
      if (!response.ok) {
        try { report.provider_error = safeProviderError(await response.clone().json()); }
        catch { report.provider_error_format = 'not_json_or_unreadable'; }
      }
      return response;
    } catch (error) {
      report.fetch_error_chain = safeChain(error);
      throw error;
    }
  },
});
try {
  const stream = await client.chat.completions.create({
    model: report.model, stream: true, max_tokens: selectedMaxTokens,
    messages: [{ role: 'user', content: 'Reply with only OK. Do not use tools.' }],
  });
  let chunks = 0, text = '', reasoningCharacters = 0;
  const finishReasons = [];
  for await (const chunk of stream) {
    chunks++;
    for (const choice of chunk.choices || []) {
      text += choice.delta?.content || '';
      reasoningCharacters += (choice.delta?.reasoning_content || '').length;
      if (choice.finish_reason) finishReasons.push(choice.finish_reason);
    }
    if (chunk.usage) report.usage_tokens = {
      prompt: chunk.usage.prompt_tokens, completion: chunk.usage.completion_tokens,
      total: chunk.usage.total_tokens,
    };
  }
  report.phase = 'stream_completed';
  report.stream_chunks = chunks;
  report.assistant_text_characters = text.length;
  report.reply_matches_requested_OK = text.trim() === 'OK';
  report.reasoning_characters = reasoningCharacters;
  report.finish_reasons = finishReasons;
  report.outcome = 'completed';
} catch (error) {
  report.outcome = 'failed';
  report.sdk_error_chain = safeChain(error);
}
report.billing_amount = 'unknown; no billing statement read';
console.log(JSON.stringify(report, null, 2));
process.exitCode = report.outcome === 'completed' ? 0 : 1;
