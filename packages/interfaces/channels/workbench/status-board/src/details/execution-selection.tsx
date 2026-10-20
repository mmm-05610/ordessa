type ExecutionSelection = {
  readonly agentId: string
  readonly profileRevision: {
    readonly environmentNamespace: string
    readonly profileId: string
    readonly manifestRevision: number
    readonly contentDigest: string
  }
  readonly environmentId: string
  readonly environmentProvider: string
  readonly isolation: string
  readonly sharing: boolean
  readonly harnessId: string
  readonly provider: string
  readonly model: string
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
  try {
    const prototype = Object.getPrototypeOf(value)
    return prototype === Object.prototype || prototype === null
  } catch {
    return false
  }
}

function nonemptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

function isProfileRevisionRef(value: unknown): value is ExecutionSelection['profileRevision'] {
  if (!isPlainRecord(value)
    || Object.keys(value).sort().join(',') !== 'contentDigest,environmentNamespace,manifestRevision,profileId') return false
  return nonemptyString(value.environmentNamespace)
    && nonemptyString(value.profileId)
    && typeof value.manifestRevision === 'number'
    && Number.isSafeInteger(value.manifestRevision)
    && value.manifestRevision > 0
    && typeof value.contentDigest === 'string'
    && /^sha256:[0-9a-fA-F]{64}$/.test(value.contentDigest)
}

function parseSelection(value: unknown): ExecutionSelection | undefined {
  if (!isPlainRecord(value)) return undefined
  try {
    if (!nonemptyString(value.agentId)
      || !isProfileRevisionRef(value.profileRevision)
      || !nonemptyString(value.environmentId)
      || !nonemptyString(value.environmentProvider)
      || !nonemptyString(value.isolation)
      || typeof value.sharing !== 'boolean'
      || !nonemptyString(value.harnessId)
      || !nonemptyString(value.provider)
      || !nonemptyString(value.model)) return undefined
    return value as unknown as ExecutionSelection
  } catch {
    // A malformed accessor or proxy is unavailable selection data, never a
    // value that should be coerced into an apparent selection.
    return undefined
  }
}

export function ExecutionSelectionDetails({ selection }: { selection: unknown }) {
  const selected = parseSelection(selection)
  return <div className="execution-selection" aria-label="执行选择">
    <h3>执行选择</h3>
    {selected ? <>
      <p>已选择环境 {selected.environmentId}</p>
      <p>环境提供方 {selected.environmentProvider}</p>
      <p>运行提供方 {selected.provider}</p>
      <p>模型 {selected.model}</p>
      <p>隔离 {selected.isolation === 'none' ? '非沙箱（none）' : selected.isolation}</p>
    </> : <p className="empty">未选择执行环境</p>}
  </div>
}
