import type { QueryClient } from '@ordessa/system-access-client'
/** Finite read-only UI contribution; the host supplies actual wire bindings. */
export interface ExactQueryDefinition {
  method: string
  label: string
  note?: string
  fields?: readonly { key: string; label: string }[]
  parameter?: { key: string; label: string; json?: boolean }
}
export interface ExactQueryAccess {
  queries: readonly ExactQueryDefinition[]
  createQuery(method: string, scope: { realm_id: string; project_id: string }, parameters: Readonly<Record<string, unknown>>): QueryClient
}
