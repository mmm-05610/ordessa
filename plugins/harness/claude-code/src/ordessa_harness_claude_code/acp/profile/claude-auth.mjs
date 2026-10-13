/** Private instance auth: never expose this return value as route evidence. */
export function claudeProviderAuthToken(headers = {}) {
  const entries = Object.entries(headers).filter(([name]) => name.toLowerCase() === 'authorization')
  if (!entries.length) return 'acp-proxy'
  if (entries.length !== 1 || typeof entries[0][1] !== 'string'
      || !/^Bearer [^\s\u007f]{1,8000}$/u.test(entries[0][1]))
    throw new Error('Invalid bounded Claude provider authentication')
  return entries[0][1].slice(7)
}
