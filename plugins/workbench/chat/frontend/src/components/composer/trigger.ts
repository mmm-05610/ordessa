// Slash trigger token extraction for a plain controlled <textarea>, ported
// from ZCode lib/promptInputTriggers.ts + mentions/activePromptInputToken.ts @
// 29628c9a (Apache-2.0). Chat needs only the `/` trigger (input-spec P02):
// the token must start at line start or after whitespace, run to the caret,
// and the caret must stay inside the token — the upstream reconcile rules
// (token text changed → recompute; caret left → close; pure caret move →
// keep) are ported so arrow keys do not reset the panel.
export interface SlashTokenSnapshot {
  readonly query: string
  readonly tokenStart: number
  readonly tokenEnd: number
  readonly tokenText: string
}

const ACTIVE_SLASH_RE = /(^|\s)(\/)([^\s/]*)$/

export function extractSlashTrigger(textBeforeCaret: string): { query: string } | null {
  const match = ACTIVE_SLASH_RE.exec(textBeforeCaret)
  if (!match) return null
  return { query: match[3] ?? '' }
}

export function createSlashSnapshot(text: string, caret: number): SlashTokenSnapshot | null {
  const active = extractSlashTrigger(text.slice(0, caret))
  if (!active) return null
  const tokenStart = caret - active.query.length - 1
  const tokenEnd = caret
  return { query: active.query, tokenStart, tokenEnd, tokenText: text.slice(tokenStart, tokenEnd) }
}

const caretInsideToken = (snapshot: SlashTokenSnapshot, caret: number): boolean =>
  caret >= snapshot.tokenStart + 1 && caret <= snapshot.tokenEnd

/** Reconcile the previous snapshot against a new (text, caret): a pure caret
 * move inside the unchanged token keeps the snapshot (no re-filter); any text
 * change re-derives it; leaving the token closes the panel (null). */
export function reconcileSlashSnapshot(previous: SlashTokenSnapshot | null, text: string, caret: number): SlashTokenSnapshot | null {
  if (!previous) return createSlashSnapshot(text, caret)
  if (text.slice(previous.tokenStart, previous.tokenEnd) !== previous.tokenText) return createSlashSnapshot(text, caret)
  if (!caretInsideToken(previous, caret)) return null
  return previous
}

/** Replacement range for insert-command: only valid while the caret is still
 * inside the ORIGINAL token text; a moved caret refuses the stale insert. */
export function slashReplacementRange(snapshot: SlashTokenSnapshot | null, text: string, caret: number): { start: number; end: number } | null {
  if (!snapshot) return null
  if (text.slice(snapshot.tokenStart, snapshot.tokenEnd) !== snapshot.tokenText) return null
  if (!caretInsideToken(snapshot, caret)) return null
  return { start: snapshot.tokenStart, end: snapshot.tokenEnd }
}
