/**
 * F5 context keys (R7/M14 `oe-f5/1`, T008-19) — the frozen ContextKeyRegistry.
 *
 * Keys are namespaced and scope-bound; they derive from focus, selected UI
 * targets and authorized projections. `when` expressions evaluate
 * AVAILABILITY ONLY — they never grant execution rights (the original
 * public operation stays the authorization face) and a key never carries a
 * secret or a second copy of business state (F5 §7).
 */
export class ContextKeyRegistry {
  private readonly values = new Map<string, string | number | boolean | null>()

  constructor(private readonly scope: string) {}

  private full(name: string): string {
    return `${this.scope}:${name}`
  }

  set(name: string, value: string | number | boolean | null): void {
    if (/secret|token|password|apikey|credential/i.test(name)) {
      throw new Error('context keys never carry secrets')
    }
    this.values.set(this.full(name), value)
  }

  get(name: string): string | number | boolean | null {
    return this.values.get(this.full(name)) ?? null
  }

  /**
   * Minimal `when` evaluator: `name`, `!name`, `name == value`, `a && b`,
   * `a || b` over context values. Availability display only.
   */
  evaluate(when: string): boolean {
    const orParts = when.split('||')
    return orParts.some(part => part.split('&&').every(term => this.evaluateTerm(term.trim())))
  }

  private evaluateTerm(term: string): boolean {
    if (term.startsWith('!')) {
      return !this.evaluateTerm(term.slice(1).trim())
    }
    const eq = term.match(/^([A-Za-z0-9_.:-]+)\s*==\s*"?([^"]*)"?$/)
    if (eq) {
      return String(this.get(eq[1]) ?? '') === eq[2]
    }
    return Boolean(this.get(term))
  }

  /** Scope exit: keys die with their scope (no cross-scope leakage). */
  releaseScope(): void {
    for (const key of [...this.values.keys()]) {
      if (key.startsWith(`${this.scope}:`)) this.values.delete(key)
    }
  }
}
