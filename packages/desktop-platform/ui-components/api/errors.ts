// Leaf module: the generic rejection type of this platform (contract §5).
//
// It lives apart from api/ui-components.ts on purpose: the Token construction
// site is in that module, and a bundle that only needs to THROW a platform error
// (the service implementation, compiled into the `ordessa.ui-components`
// extension) must not drag a second `new Token(...)` copy along — that is the
// CN-08 single-instance rule this package is subject to. Public consumers keep
// seeing everything through `api/ui-components`, which re-exports this file.
export type UiErrorCode =
  | 'UI_SCOPE_CLOSED' | 'UI_KEY_IDENTITY_CONFLICT' | 'UI_PROVIDER_DUPLICATE'
  | 'UI_SELECTION_DUPLICATE' | 'UI_RENDER_FAILED' | 'UI_ACTION_FAILED'

/** Every rejection this platform raises carries one of the generic codes above. */
export class UiComponentsError extends Error {
  constructor(readonly code: UiErrorCode, message: string) {
    super(`${code}: ${message}`)
    this.name = 'UiComponentsError'
  }
}
