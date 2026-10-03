/**
 * F5 display tools (R7/M14 `oe-f5/1`, T008-19) — translation and icon
 * fallback (F5 §7: namespace + params + missing-key fallback; stable icon
 * ids with unknown fallback; theme carries high-contrast semantics).
 *
 * Pure display utilities: no service access, no authorization, no secrets.
 */

export interface Translator {
  /** Namespaced lookup with {param} interpolation; missing keys fall back
   *  to the key itself (visible, never silent) and record the miss. */
  translate(namespace: string, key: string, params?: Record<string, string | number>): string
  missingKeys(): ReadonlyArray<string>
}

export function createTranslator(
  catalog: Readonly<Record<string, Record<string, string>>>,
  fallback?: Translator,
): Translator {
  const missing = new Set<string>()
  return {
    translate(namespace, key, params) {
      const entry = catalog[namespace]?.[key]
      let resolved: string | undefined = entry
      if (resolved === undefined) {
        resolved = fallback?.translate(namespace, key, params)
      }
      if (resolved === undefined) {
        missing.add(`${namespace}:${key}`)
        resolved = key // visible fallback: the key itself, never an empty string
      }
      let text = resolved
      if (params) {
        for (const [name, value] of Object.entries(params)) {
          text = text.split(`{${name}}`).join(String(value))
        }
      }
      return text
    },
    missingKeys: () => [...missing],
  }
}

export interface IconResolver {
  /** Stable icon id; unknown ids fall back to a declared default. */
  resolve(id: string): string
}

export function createIconResolver(known: Readonly<Record<string, string>>, fallbackId = 'icon.unknown'): IconResolver {
  return {
    resolve(id: string): string {
      return known[id] ?? fallbackId
    },
  }
}

export interface ThemeTokens {
  highContrast: boolean
  tokens: Readonly<Record<string, string>>
}

/** Theme carries high-contrast semantics; consumers never hardcode colors. */
export function createTheme(tokens: Record<string, string>, highContrast = false): ThemeTokens {
  return {
    highContrast,
    tokens: Object.freeze({ ...tokens, ...(highContrast ? { contrast: 'high' } : {}) }),
  }
}
