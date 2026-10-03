/** Opaque product argv handoff; the platform does not interpret domain flags. */
export function productServerArgs(env: Readonly<Record<string, string | undefined>> = process.env): readonly string[] {
  const source = env.ORDESSA_SERVER_ARGS_JSON
  if (source === undefined) return Object.freeze([])
  if (source.length > 65536) throw new Error('SERVER_PRODUCT_ARGS_INVALID')
  let value: unknown
  try { value = JSON.parse(source) } catch { throw new Error('SERVER_PRODUCT_ARGS_INVALID') }
  if (!Array.isArray(value) || value.length > 256
      || !value.every(arg => typeof arg === 'string' && !arg.includes('\0'))) {
    throw new Error('SERVER_PRODUCT_ARGS_INVALID')
  }
  return Object.freeze([...value])
}
