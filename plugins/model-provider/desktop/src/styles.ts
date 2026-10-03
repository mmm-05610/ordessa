// Adapted from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/styles.ts).
/**
 * The Workbench visual tokens (design.md §6). Colors ride CSS variables so
 * the section matches the shell; state is always text + glyph, never color
 * alone.
 */
export const tokens = {
  surface: 'var(--ordessa-color-surface, #fff)',
  nav: 'var(--ordessa-color-bg, #f6f6f6)',
  ink: 'var(--ordessa-color-text, #202123)',
  accent: 'var(--ordessa-color-accent, #3b82f6)',
  warning: 'var(--ordessa-color-warning, #b26a00)',
  error: 'var(--ordessa-color-danger, #b3261e)',
  muted: 'var(--ordessa-color-muted, #6b7280)',
  mono: 'ui-monospace, SFMono-Regular, Menlo, monospace',
}

export const styles = {
  root: (narrow: boolean) => ({
    display: 'grid',
    gridTemplateColumns: narrow ? 'minmax(0, 1fr)' : '200px minmax(0, 1fr)',
    gap: 24,
    padding: 0,
    background: tokens.surface,
    color: tokens.ink,
    minHeight: 320,
  }),
  listPane: { background: tokens.nav, borderRadius: 12, padding: 8, alignSelf: 'start' },
  listItem: (selected: boolean) => ({
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '10px 8px', borderRadius: 8, cursor: 'pointer', flexWrap: 'wrap' as const,
    background: selected ? tokens.surface : 'transparent',
    boxShadow: selected ? '0 1px 4px #0000000a' : 'none',
  }),
  detail: { padding: 16, minWidth: 0, border: '1px solid var(--ordessa-color-border, #e7e7e9)', borderRadius: 14 },
  modelRow: { display: 'flex', alignItems: 'center', gap: 8, padding: '10px 0', flexWrap: 'wrap' as const, borderBottom: '1px solid var(--ordessa-color-border, #eeeeef)' },
  modelId: { fontFamily: tokens.mono, fontSize: 12 },
  button: { marginRight: 8, padding: '6px 10px', cursor: 'pointer', borderRadius: 8, border: '1px solid var(--ordessa-color-border, #dedee1)', background: 'var(--ordessa-color-bg, #fafafa)', color: 'inherit', fontSize: 12 },
  errorText: { color: tokens.error },
  warningText: { color: tokens.warning },
  mutedText: { color: tokens.muted, fontSize: 12 },
}

export const settingsCss = `
.mp-settings{font:13px/1.5 system-ui,sans-serif;max-width:900px}.mp-settings h2{font-size:20px;font-weight:500}.mp-settings p{overflow-wrap:anywhere}.mp-settings button:focus-visible,.mp-settings [role=option]:focus-visible{outline:2px solid #548fe5;outline-offset:2px}
.mp-settings-form{display:grid;grid-template-columns:1fr 1fr;gap:14px 16px;padding-top:16px}.mp-settings-form label{display:flex;flex-direction:column;gap:6px;font-size:12px;color:#696970}.mp-settings-form input,.mp-settings-form select{box-sizing:border-box;width:100%;min-width:0;padding:8px 10px;border:1px solid #dedee1;border-radius:8px;background:#fafafa;color:#202123;font:13px system-ui,sans-serif}.mp-settings-form p{grid-column:1/-1;margin:0}.mp-settings-form>button{align-self:end;justify-self:start}.mp-settings [role=listbox]>button{margin-top:10px;width:100%;padding:8px;border:1px solid #dedee1;background:#fff;border-radius:8px;font:inherit;cursor:pointer}
@media(max-width:650px){.mp-settings{grid-template-columns:minmax(0,1fr)!important;gap:12px!important}.mp-settings-form{grid-template-columns:minmax(0,1fr)}}
.mp-settings-form label{color:var(--ordessa-color-muted,#696970)}.mp-settings-form input,.mp-settings-form select,.mp-settings [role=listbox]>button{background:var(--ordessa-color-bg,#fafafa);color:var(--ordessa-color-text,#202123);border-color:var(--ordessa-color-border,#dedee1)}
@media(prefers-color-scheme:dark){.mp-settings-form input,.mp-settings-form select,.mp-settings [role=listbox]>button{background:var(--ordessa-color-bg,#252526);color:var(--ordessa-color-text,#eee)}}
@container(max-width:650px){.mp-settings{grid-template-columns:minmax(0,1fr)!important;gap:12px!important}.mp-settings-form{grid-template-columns:minmax(0,1fr)}}
.wb-settings-section .mp-settings-form label{margin:0}
`
