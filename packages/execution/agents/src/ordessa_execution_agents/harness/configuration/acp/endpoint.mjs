export function safeEndpoint(baseUrl) {
  if (typeof baseUrl !== "string" || !baseUrl || baseUrl.length > 4096 || baseUrl.trim() !== baseUrl || /[\u0000-\u001f\u007f]/u.test(baseUrl)) return false
  let url
  try { url = new URL(baseUrl) } catch { return false }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) return false
  return true
}
