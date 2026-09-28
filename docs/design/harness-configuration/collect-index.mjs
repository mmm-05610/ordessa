// Read-only official-document index collector. Does not run any harness.
// Prints metadata and machine identifiers, never writes files or executes docs.
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createHash } from 'node:crypto';
const run = promisify(execFile);
const sources = [
  ['codex', 'https://learn.chatgpt.com/docs/config-file/config-reference.md', 'markdown'],
  ['claude', 'https://code.claude.com/docs/en/settings-reference.md', 'markdown'],
  ['claude-env', 'https://code.claude.com/docs/en/env-vars.md', 'markdown'],
  ['opencode', 'https://opencode.ai/config.json', 'schema'],
  ['opencode-tui', 'https://opencode.ai/tui.json', 'schema'],
  ['kilo', 'https://app.kilo.ai/config.json', 'schema'],
  ['pi', 'https://raw.githubusercontent.com/earendil-works/pi/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/docs/settings.md', 'table'],
  ['hermes', 'https://raw.githubusercontent.com/NousResearch/hermes-agent/6f7a7991bb069db07ae74a479823ce8310f8c7e0/website/docs/user-guide/configuration.md', 'table'],
  ['qwen', 'https://raw.githubusercontent.com/QwenLM/qwen-code/302e7d88ef366991295e41dd9b158a13ab29cd74/docs/users/configuration/settings.md', 'table'],
  ['dsh', 'https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/477b4f420553e8a52c2fbccc464d7561b239c443/docs/config-catalog.md', 'catalog'],
];
function schemaKeys(root) {
  const paths = new Set();
  function visit(n, path, refs, depth = 0) {
    if (!n || typeof n !== 'object') return;
    if (depth > 1) return;
    if (n.$ref?.startsWith('#/') && !refs.has(n.$ref)) {
      const target = n.$ref.slice(2).split('/').reduce((v, k) => v?.[k.replace(/~1/g, '/').replace(/~0/g, '~')], root);
      visit(target, path, new Set([...refs, n.$ref]), depth);
    }
    for (const [k, v] of Object.entries(n.properties ?? {})) {
      const p = path ? `${path}.${k}` : k; paths.add(p); visit(v, p, refs, depth + 1);
    }
    for (const v of n.anyOf ?? []) visit(v, path, refs, depth);
    for (const v of n.oneOf ?? []) visit(v, path, refs, depth);
    for (const v of n.allOf ?? []) visit(v, path, refs, depth);
    if (n.items) visit(n.items, `${path}[]`, refs, depth);
    if (typeof n.additionalProperties === 'object') visit(n.additionalProperties, `${path}.*`, refs, depth + 1);
    for (const v of Object.values(n.patternProperties ?? {})) visit(v, `${path}.*`, refs, depth + 1);
  }
  visit(root, '', new Set()); return [...paths].sort();
}
const requested = new Set(process.argv.slice(2));
for (const id of requested) if (!sources.some(s => s[0] === id)) throw new Error(`Unknown source: ${id}`);
const result = await Promise.all(sources.filter(s => !requested.size || requested.has(s[0])).map(async ([id, url, format]) => {
  try {
    const { stdout } = await run('curl', ['-L', '--max-time', '25', '-sS', '-w', '\n__FETCH_META__%{http_code} %{url_effective}', url], { maxBuffer: 16 * 1024 * 1024 });
    const split = stdout.lastIndexOf('\n__FETCH_META__');
    const body = stdout.slice(0, split), meta = stdout.slice(split + 15).trim();
    if (!meta.startsWith('200 ')) return { id, url, error: meta };
    let keys;
    if (format === 'schema') keys = schemaKeys(JSON.parse(body));
    else if (format === 'table') keys = [...new Set([...body.matchAll(/^\|\s*`([A-Za-z_][A-Za-z_0-9.<>\[\]*-]*)`\s*\|/gm)].map(m => m[1]))].sort();
    else if (format === 'catalog') {
      const found = new Set(); let owner = '';
      for (const line of body.split('\n')) {
        const section = line.match(/^## `([^`]+)`/);
        if (section) { owner = section[1]; found.add(owner); }
        const field = line.match(/^  ([A-Za-z_][A-Za-z_0-9]*)\??:/);
        if (owner && field) found.add(`${owner}::${field[1]}`);
      }
      keys = [...found].sort();
    }
    else if (id === 'codex') keys = [...new Set([...body.matchAll(/\bkey:\s*"([^"]+)"/g)].map(m => m[1]))].sort();
    else if (id === 'claude') keys = [...new Set([...body.matchAll(/^###\s+`([^`]+)`/gm)].map(m => m[1]))].sort();
    else keys = [...new Set([...body.matchAll(/^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|/gm)].map(m => m[1]))].sort();
    const extraction = format === 'schema' ? 'schema properties capped at two named levels; dynamic keys use *; deeper extension schemas are NOT enumerated' : format === 'catalog' ? 'package headings and two-space TypeScript field declarations; includes referenced types/runtime-only fields; NOT an accepted-config schema' : format === 'table' ? 'first-column code identifiers only; examples/prose/YAML-only fields and some nested fields are NOT covered' : 'document identifiers extracted mechanically; NOT a complete semantic inventory or support assertion';
    if (!keys.length) throw new Error('Extraction returned no identifiers; source format needs review');
    return { id, url, fetchedAt: new Date().toISOString(), response: meta, bytes: Buffer.byteLength(body), sha256: createHash('sha256').update(body).digest('hex'), extraction, keys };
  } catch (e) { return { id, url, error: String(e.message).slice(0,300) }; }
}));
console.log(JSON.stringify(result));
