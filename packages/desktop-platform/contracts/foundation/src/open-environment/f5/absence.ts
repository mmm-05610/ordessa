/**
 * F5 absence matrix (R7/M14 `oe-f5/1`) — guarantee honesty.
 *
 * Every F5 capability declares what it does when its real backing is
 * missing. `unavailable`/`session-only` are honest states: the platform
 * never fakes persistence, never fakes cancellation, and never fakes a
 * query. Consumers must handle the declared absence — silence is not an
 * option, and a typed absence is not a success.
 */

export type Absence = 'available' | 'session-only' | 'unavailable'

export interface F5AbsenceMatrix {
  /** Owner state stores are pure in-process mechanisms: always available. */
  stateStores: Extract<Absence, 'available'>
  /** Selection bindings derive from stores: available with the store. */
  selectors: Extract<Absence, 'available'>
  /** Projections need the E3 observation seam; without it they are unavailable. */
  projections: Absence
  /** Query cache is in-process; the declared policies stay off unless configured. */
  queryCache: Extract<Absence, 'available'>
  /** Task scopes are local waiting state: available; backend cancel is separate. */
  tasks: Extract<Absence, 'available'>
  /** Edit sessions are local tools; saving needs the domain's conditional write. */
  editing: Extract<Absence, 'available'>
  /** UI storage needs a host adapter; absent adapter = session-only (F5 §6). */
  uiStorage: Absence
  /** Interactions need the Workbench presentation layer. */
  interactions: Absence
  /** Context keys derive from authorized projections: availability follows. */
  contextKeys: Absence
}

export const UI_STORAGE_ABSENCE: Absence = 'session-only'
export const UI_STORAGE_ABSENCE_REASON =
  'no host adapter is composed; safe-UI preferences live for this session only ' +
  'and restart recovery is not promised'
