// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/styles.ts, verbatim)
/**
 * The Workbench visual tokens (design.md §6). Colors ride CSS variables so
 * the section matches the shell; state is always text + glyph, never color
 * alone.
 */
export const tokens = {
  surface: '#fff',
  nav: '#f6f6f6',
  ink: '#202123',
  accent: '#3b82f6',
  warning: '#b26a00',
  error: '#b3261e',
  muted: '#6b7280',
  mono: 'ui-monospace, SFMono-Regular, Menlo, monospace',
}

export const styles = {
  root: (narrow: boolean) => ({
    display: 'grid',
    gridTemplateColumns: narrow ? '1fr' : '280px 1fr',
    gap: 12,
    padding: 12,
    background: tokens.surface,
    color: tokens.ink,
    minHeight: 320,
  }),
  listPane: { background: tokens.nav, borderRadius: 8, padding: 8 },
  listItem: (selected: boolean) => ({
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '6px 8px', borderRadius: 6, cursor: 'pointer',
    background: selected ? tokens.surface : 'transparent',
    outline: selected ? `2px solid ${tokens.accent}` : 'none',
  }),
  detail: { padding: 4 },
  modelRow: { display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' },
  modelId: { fontFamily: tokens.mono, fontSize: 12 },
  button: { marginRight: 8, padding: '4px 10px', cursor: 'pointer' },
  errorText: { color: tokens.error },
  warningText: { color: tokens.warning },
  mutedText: { color: tokens.muted, fontSize: 12 },
}
