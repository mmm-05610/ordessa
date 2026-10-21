import { jsonDigest } from "../../../../../../../infrastructure/src/ordessa_infrastructure/encoding/canonical_json.mjs"
export { stableJSON, jsonDigest } from "../../../../../../../infrastructure/src/ordessa_infrastructure/encoding/canonical_json.mjs"
// Preserve all fields; reject numbers without a common exact Python/JS form.
// This is a configuration identity domain, not a change to the generic codec.
export function assertConfigurationIdentity(options) {
  if (!Array.isArray(options)) throw new TypeError('Native configuration identity requires configOptions array')
  const active = new Set()
  const visit = value => {
    if (typeof value === 'number' && !Number.isSafeInteger(value))
      throw new TypeError('Unsupported native configuration identity number: expected safe integer')
    if (typeof value === 'string') {
      for (let i = 0; i < value.length; i++) {
        const code = value.charCodeAt(i)
        if (code >= 0xd800 && code <= 0xdbff) {
          const next = value.charCodeAt(++i)
          if (!(next >= 0xdc00 && next <= 0xdfff)) throw new TypeError('Unpaired native configuration surrogate')
        } else if (code >= 0xdc00 && code <= 0xdfff) throw new TypeError('Unpaired native configuration surrogate')
      }
    }
    if (value !== null && typeof value === 'object') {
      if (active.has(value)) throw new TypeError('Cyclic native configuration identity')
      active.add(value)
      for (const [key, item] of Object.entries(value)) { visit(key); visit(item) }
      active.delete(value)
    }
  }
  visit(options)
  jsonDigest(options) // Frozen codec validates plain JSON and dense arrays.
  return options
}
export function configurationDigest(observation) {
  return jsonDigest(assertConfigurationIdentity(observation.configOptions))
}
