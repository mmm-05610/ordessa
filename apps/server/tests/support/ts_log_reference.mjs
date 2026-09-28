const canary = process.argv[2]
const SECRET_KEYS = ['token','secret','password','credential','authorization','bearer','apikey','api_key']
const isSecretKey = (key) => SECRET_KEYS.some((f) => key.toLowerCase().includes(f))
const redactText = (v) => (v.includes(canary) ? v.split(canary).join('[redacted]') : v)
const looksLikePath = (v) => v.startsWith('/') && !v.includes(' ')
const redactField = (key, value) => {
  if (isSecretKey(key)) return '[redacted]'
  if (typeof value === 'string' && looksLikePath(value)) return redactText(value.split('/').filter(Boolean).pop() ?? value)
  if (typeof value === 'string') return redactText(value)
  if (Array.isArray(value)) return value.map((i) => redactField(key, i))
  return value
}
const record = { ts: '2026-01-01T00:00:00.000Z', level: 'info', scope: 'host.desktop', msg: redactText('session started') }
const fields = JSON.parse(process.argv[3])
for (const [k, v] of Object.entries(fields)) record[k] = redactField(k, v)
process.stdout.write(JSON.stringify(record))
