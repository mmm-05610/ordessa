/** Codex 0.147.0 ModelsResponse dialect, not a provider/model identity heuristic. */
import { createHash } from 'node:crypto'
import { constants, closeSync, fchmodSync, fsyncSync, lstatSync, mkdirSync,
  openSync, readFileSync, realpathSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const text = value => typeof value === 'string' && value.length > 0 && value.length <= 4096
  && value === value.trim() && !/[\u0000-\u001f\u007f]/u.test(value)
const object = value => value && typeof value === 'object' && !Array.isArray(value)
const boundedInteger = value => Number.isSafeInteger(value) && value > 0 && value <= 100000000
const refuse = () => {throw new Error('Declared Codex model capabilities required')}

export function compileCodexModelCatalog(model, facts) {
  if (!text(model) || !object(facts) || facts.toolCall !== true || typeof facts.reasoning !== 'boolean'
      || Object.keys(facts).some(key => !['toolCall', 'reasoning', 'reasoningOptions', 'modalities', 'limits', 'cost'].includes(key))) refuse()
  let efforts = []
  if (facts.reasoning) {
    if (!Array.isArray(facts.reasoningOptions) || facts.reasoningOptions.length !== 1) refuse()
    const option = facts.reasoningOptions[0]
    if (!object(option) || Object.keys(option).length !== 2 || option.type !== 'effort'
        || !Array.isArray(option.values) || option.values.length < 1 || option.values.length > 16
        || option.values.some(value => !text(value) || value.length > 64)
        || new Set(option.values).size !== option.values.length) refuse()
    efforts = [...option.values]
  } else if (facts.reasoningOptions !== undefined
      && (!Array.isArray(facts.reasoningOptions) || facts.reasoningOptions.length !== 0)) refuse()
  if (facts.limits !== undefined && (!object(facts.limits)
      || Object.keys(facts.limits).some(key => !['context', 'output'].includes(key))
      || Object.values(facts.limits).some(value => !boundedInteger(value)))) refuse()
  if (facts.modalities !== undefined && (!object(facts.modalities)
      || Object.keys(facts.modalities).some(key => !['input', 'output'].includes(key))
      || Object.values(facts.modalities).some(values => !Array.isArray(values) || !values.length
        || values.some(value => !['text', 'image'].includes(value)) || new Set(values).size !== values.length))) refuse()
  // Execution choices are conservative adapter policy, not advertised backend
  // capability claims: no parallel calls, verbosity, summaries or native search.
  // The generic upstream fallback instructions are reused independently of
  // any official model metadata. Never clone a bundled model under a new slug.
  return {models: [{slug: model, display_name: model, description: null,
    default_reasoning_level: efforts.includes('medium') ? 'medium' : efforts[0] ?? null,
    supported_reasoning_levels: efforts.map(effort => ({effort, description: effort})),
    shell_type: 'shell_command', visibility: 'list', supported_in_api: true, priority: 0,
    availability_nux: null, upgrade: null,
    base_instructions: readFileSync(new URL('./codex-generic-prompt.md', import.meta.url), 'utf8'),
    include_skills_usage_instructions: false, include_plugin_usage_instructions: false,
    include_apps_usage_instructions: false, supports_reasoning_summary_parameter: false,
    default_reasoning_summary: 'none', support_verbosity: false, default_verbosity: null,
    apply_patch_tool_type: null, truncation_policy: {mode: 'bytes', limit: 10000},
    supports_parallel_tool_calls: false, experimental_supported_tools: [],
    use_responses_lite: false,
    ...(facts.modalities?.input ? {input_modalities: [...facts.modalities.input]} : {}),
    ...(facts.limits?.context ? {context_window: facts.limits.context, max_context_window: facts.limits.context} : {}),
  }]}
}

export function writeCodexModelCatalog(home, model, facts) {
  const content = JSON.stringify(compileCodexModelCatalog(model, facts)) + '\n'
  const root = path.resolve(home)
  if (root !== home || realpathSync(root) !== root || !lstatSync(root).isDirectory())
    throw new Error('Canonical private Codex instance directory required')
  const directory = path.join(root, 'model-catalogs')
  try {mkdirSync(directory, {mode: 0o700})} catch (error) {if (error.code !== 'EEXIST') throw error}
  const dir = lstatSync(directory)
  if (!dir.isDirectory() || dir.isSymbolicLink() || (dir.mode & 0o077)
      || typeof process.getuid === 'function' && dir.uid !== process.getuid())
    throw new Error('Private model catalogue directory required')
  const digest = createHash('sha256').update(content).digest('hex')
  const file = path.join(directory, digest + '.json')
  let fd
  try {fd = openSync(file, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600)}
  catch (error) {
    if (error.code !== 'EEXIST') throw error
    fd = openSync(file, constants.O_RDONLY | constants.O_NOFOLLOW)
    try {if (readFileSync(fd, 'utf8') !== content || (lstatSync(file).mode & 0o777) !== 0o400)
      throw new Error('Immutable catalogue content changed')} finally {closeSync(fd)}
    return file
  }
  try {writeFileSync(fd, content); fsyncSync(fd); fchmodSync(fd, 0o400)} finally {closeSync(fd)}
  return file
}
