import { createHash } from 'node:crypto'

/** JSON-only canonical encoding: object keys sort, array order remains native. */
export function stableJSON(value) {
  const visit = (item, seen) => {
    if (item === null || typeof item === 'string' || typeof item === 'boolean') return JSON.stringify(item)
    if (typeof item === 'number' && Number.isFinite(item)) return JSON.stringify(item)
    if (typeof item !== 'object' || seen.has(item)) throw new TypeError('Expected finite acyclic JSON')
    seen.add(item)
    let encoded
    if (Array.isArray(item)) {
      if (Object.keys(item).length !== item.length) throw new TypeError('Expected dense JSON array')
      // A named property can otherwise hide a hole from the key-count check;
      // Array.map skips that hole and silently changes the encoded payload.
      for (let index = 0; index < item.length; index++) {
        if (!Object.prototype.hasOwnProperty.call(item, index)) throw new TypeError('Expected dense JSON array')
      }
      encoded = '[' + item.map(entry => visit(entry, seen)).join(',') + ']'
    } else {
      if (Object.getPrototypeOf(item) !== Object.prototype && Object.getPrototypeOf(item) !== null)
        throw new TypeError('Expected plain JSON object')
      encoded = '{' + Object.keys(item).sort().map(key => JSON.stringify(key) + ':' + visit(item[key], seen)).join(',') + '}'
    }
    seen.delete(item)
    return encoded
  }
  return visit(value, new Set())
}

export function jsonDigest(value) {
  return createHash('sha256').update(stableJSON(value)).digest('hex')
}

