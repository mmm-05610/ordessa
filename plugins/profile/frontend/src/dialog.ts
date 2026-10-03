/**
 * F4 dialog face for the Profile UI (T009-08): `window.confirm` is retired.
 * The injected face reports the user's choice; when no dialog face is
 * composed the result is a typed `unavailable` — the caller declines safely
 * (keeps the draft / skips the impact action). A missing dialog never
 * fabricates consent and never falls back to a browser modal.
 */
export interface DialogFace {
  confirm(request: { operationId: string; title: string; text: string }): Promise<
    { kind: 'confirmed' } | { kind: 'cancelled' } | { kind: 'revoked' } | { kind: 'unavailable' } | { kind: 'failed'; reason: string }>
}

let face: DialogFace | null = null
let seq = 0

/** Composition wires the Workbench dialog face here (008 seam). */
export function setDialogFace(next: DialogFace | null): void {
  face = next
}

/** True ONLY on explicit confirmation; every other outcome declines safely. */
export async function confirmAction(title: string, text: string): Promise<boolean> {
  if (face === null) return false // typed unavailable: decline, never consent
  const result = await face.confirm({ operationId: `profile-${++seq}`, title, text })
  return result.kind === 'confirmed'
}
