/** A read-only view of native ACP commands. Names are data, never an instruction to submit. */
export interface NativeCommand {
  readonly name: string
  readonly description: string
  readonly inputHint?: string
}

export type NativeCommandCatalog =
  | Readonly<{ kind: 'absent' }>
  | Readonly<{ kind: 'unknown'; reason: 'malformed' | 'stale-session' | 'channel-down' | 'unobservable' }>
  | Readonly<{
      kind: 'available'
      connectionId: string
      nativeSessionId: string
      commands: readonly NativeCommand[]
    }>

export interface NativeCommandReader {
  getNativeCommands(sessionKey: string): NativeCommandCatalog
}

export function hasNativeCommandReader(value: unknown): value is NativeCommandReader {
  return value !== null && typeof value === 'object'
    && typeof (value as { getNativeCommands?: unknown }).getNativeCommands === 'function'
}

const object = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null

/** Validate before the ACP SDK can skip invalid list members during deserialization. */
export function parseNativeCommands(value: unknown): readonly NativeCommand[] | null {
  const update = object(value)
  if (!update || update.sessionUpdate !== 'available_commands_update'
      || !Array.isArray(update.availableCommands)) return null
  const seen = new Set<string>()
  const commands: NativeCommand[] = []
  for (const item of update.availableCommands) {
    const raw = object(item)
    if (!raw || typeof raw.name !== 'string' || !raw.name.trim()
        || (raw.description !== undefined && typeof raw.description !== 'string')
        || seen.has(raw.name)) return null
    seen.add(raw.name)
    const input = raw.input == null ? null : object(raw.input)
    if (raw.input != null && (!input || (input.hint !== undefined && typeof input.hint !== 'string'))) return null
    commands.push(Object.freeze({ name: raw.name, description: (raw.description as string | undefined) ?? '',
      ...(typeof input?.hint === 'string' ? { inputHint: input.hint } : {}) }))
  }
  return Object.freeze(commands)
}
