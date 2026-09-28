export const styles = `
.wb { --ui-surface:#fff; --ui-nav:#f6f6f6; --ui-sunken:#f0f0f1; --ui-hover:#eaeaea; --ui-selected:#e3e4e6; --ui-line:#e8e8e8; --ui-ink:#202123; --ui-ink-secondary:#6b6e73; --ui-ink-faint:#9a9da2; --ui-accent:#3b82f6; --ui-ok:#2e7d46; --ui-warn:#b26a00; --ui-error:#b3261e; color:var(--ui-ink); background:var(--ui-nav); font-size:13px; height:100vh; overflow:hidden; }
/* Shell-layer tokens only: the dark scheme re-declares the same .wb variables, no new token is introduced. */
@media(prefers-color-scheme: dark) { .wb { --ui-surface:#1b1c1e; --ui-nav:#151618; --ui-sunken:#212225; --ui-hover:#2a2b2f; --ui-selected:#33353a; --ui-line:#2c2d31; --ui-ink:#e6e7e8; --ui-ink-secondary:#a4a7ac; --ui-ink-faint:#7c7f85; --ui-accent:#60a5fa; --ui-ok:#4cc075; --ui-warn:#d9a441; --ui-error:#f0776c; } }
.wb [data-testid=workspace]:not([hidden]) { display:flex; flex-direction:column; height:100%; }
.wb button { border:0; border-radius:8px; background:transparent; color:inherit; padding:5px 10px; font-size:12px; }
.wb button:hover:not(:disabled) { background:var(--ui-hover); }
.wb button[aria-pressed=true] { color:var(--ui-ink); background:var(--ui-selected); }
.wb button:disabled { opacity:.35; }
.wb :focus-visible { outline:2px solid var(--ui-accent); outline-offset:2px; }
.wb h1 { margin:0; font-size:16px; font-weight:600; }
.wb p { line-height:1.6; }
.wb-bar { height:40px; flex-shrink:0; display:flex; align-items:center; gap:20px; padding:0 10px 0 14px; border-bottom:1px solid var(--ui-line); background:var(--ui-nav); }
.wb-bar strong { font-size:13px; font-weight:650; letter-spacing:.2px; }
.wb-bar small { font-family:ui-monospace,monospace; font-size:9px; color:var(--ui-ink-faint); font-weight:400; letter-spacing:1.3px; margin-left:10px; }
.wb-actions,.wb-layout-actions,.wb-status { display:flex; gap:4px; align-items:center; }
.wb-layout-actions { margin-left:auto; }
.wb-layout-actions button { display:flex; padding:6px; border-radius:8px; color:var(--ui-ink-secondary); }
.wb-layout-actions button[aria-pressed=true] { color:var(--ui-ink); }
.wb-body { flex:1; display:flex; min-height:0; }
/* Sidebar: fixed Header / Footer, shrinkable Navigation (own scroll when long),
 * Content fills the rest with min-height:0. Ported structure, not business code
 * (see PROVENANCE.md). */
.wb-sidebar { background:var(--ui-nav); }
.wb-sidebar>header { height:auto; min-height:34px; flex-wrap:wrap; align-items:center; padding:2px 4px 2px 2px; }
.wb-sidebar-identity { flex-shrink:0; font-size:12px; font-weight:650; letter-spacing:.2px; padding:0 6px; color:var(--ui-ink-secondary); }
.wb-sidebar-collapse { flex-shrink:0; color:var(--ui-ink-secondary); }
.wb-sidebar-restore { flex-shrink:0; color:var(--ui-ink-secondary); }
.wb-sidebar-nav { display:flex; flex:0 1 auto; flex-direction:column; min-height:0; overflow-y:auto; }
.wb-sidebar-nav>.wb-nav { flex-shrink:0; border-bottom:1px solid var(--ui-line); }
.wb-sidebar-content { flex:1 1 auto; min-height:0; overflow:auto; overflow-y:auto; }
.wb-sidebar-footer { flex-shrink:0; min-height:0; }
.wb-sidebar-footer .wb-status { flex-wrap:wrap; align-content:flex-start; max-height:132px; overflow-y:auto; }
.wb-region { height:100%; min-width:0; display:flex; flex-direction:column; background:var(--ui-nav); overflow:hidden; }
.wb-main { background:var(--ui-surface); }
.wb-region>header { height:34px; flex-shrink:0; display:flex; align-items:center; gap:4px; padding:0 6px; }
.wb-region>header>[role=group] { flex:1; min-width:0; overflow:auto; display:flex; align-items:center; height:100%; gap:2px; }
.wb-region-title { font-size:13px; font-weight:650; letter-spacing:.2px; padding:0 4px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.wb-region [draggable=true] { white-space:nowrap; flex-shrink:0; height:26px; border-radius:8px; cursor:grab; color:var(--ui-ink-secondary); }
.wb-region [draggable=true][aria-pressed=true] { color:var(--ui-ink); background:var(--ui-selected); }
.wb-region-actions { display:flex; align-items:center; flex-shrink:0; opacity:0; width:0; overflow:hidden; transition:opacity .12s; }
.wb-region>header:hover .wb-region-actions, .wb-region>header:focus-within .wb-region-actions { opacity:1; width:auto; }
.wb-region-actions select { font:inherit; font-size:10px; color:var(--ui-ink-faint); border:0; background:transparent; width:54px; }
.wb-region-label { font-size:11px; color:var(--ui-ink-faint); margin-left:7px; }
.wb-content { overflow:auto; min-height:0; }
.wb-content:has(.wb-surface) { flex:1; }
.wb-left .wb-content { flex:1; }
.wb-surface { box-sizing:border-box; height:100%; padding:14px; }
.wb-surface h1,.wb-surface h2 { font-size:16px; }
.wb-surface textarea { max-width:100%; }
.wb-nav { flex-shrink:0; display:flex; flex-direction:column; align-items:stretch; gap:2px; padding:6px; }
.wb-nav button { display:flex; align-items:center; justify-content:flex-start; gap:8px; min-height:30px; max-height:32px; padding:5px 8px; border-radius:8px; font-size:12px; color:var(--ui-ink-secondary); text-align:left; }
.wb-nav button[aria-pressed=true] { color:var(--ui-ink); background:var(--ui-selected); }
.wb-nav-icon { width:16px; display:inline-flex; align-items:center; justify-content:center; font-size:14px; line-height:1; flex-shrink:0; }
.wb-layout { flex:1; min-width:0; position:relative; }
.wb-group { height:100%; }
.wb-separator { background:transparent; flex-shrink:0; position:relative; }
.wb-separator::after { content:""; position:absolute; inset:0; margin:auto; background:var(--ui-line); }
.wb-separator[aria-orientation=vertical] { width:4px; }.wb-separator[aria-orientation=vertical]::after { width:1px; height:100%; }
.wb-separator[aria-orientation=horizontal] { height:4px; }.wb-separator[aria-orientation=horizontal]::after { height:1px; width:100%; }
.wb-separator:hover::after,.wb-separator:focus-visible::after,.wb-separator[data-separator=active]::after { background:var(--ui-accent); }
.wb-separator-empty { display:none; }
.wb-empty { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:24px; color:var(--ui-ink-faint); user-select:none; }
.wb-empty-mark { display:flex; align-items:center; justify-content:center; width:56px; height:56px; border-radius:50%; background:var(--ui-sunken); color:#c4c6ca; font-size:26px; font-weight:500; margin-bottom:18px; }
.wb-empty h1 { font-size:15px; font-weight:550; color:var(--ui-ink-secondary); }
.wb-empty p { margin:10px 0 24px; font-size:12px; }
.wb-empty small { font-size:10px; text-align:center; }
.wb-status { min-height:30px; flex-shrink:0; padding:0 10px; border-top:1px solid var(--ui-line); background:var(--ui-nav); color:var(--ui-ink-secondary); font-size:11px; gap:8px; }
/* The compact bottom band only carries the footer container while the sidebar
 * cannot host it; empty most of the time, it must not reserve space. */
.wb-status-band { flex-shrink:0; }
.wb-status-band:empty { display:none; }
.wb-full { height:100vh; display:flex; flex-direction:column; background:var(--ui-surface); }
.wb-full>.wb-bar { height:44px; justify-content:space-between; background:var(--ui-nav); }
.wb-full-content { width:100%; max-width:1100px; margin:0 auto; padding:28px; overflow:auto; }
/* Errors sit above the overlay stack (z-index:10): a failure during an overlay must stay visible. */
.wb-error { position:fixed; bottom:44px; right:16px; padding:12px 16px; max-width:80vw; border:1px solid #f0c4c1; border-radius:14px; background:var(--ui-surface); color:var(--ui-error); box-shadow:0 8px 24px rgba(32,33,35,.14); z-index:20; }
.wb-error button { margin-left:16px; color:var(--ui-ink-secondary); }
.wb-overlays { position:fixed; inset:0; z-index:10; pointer-events:none; }
.wb-overlay { position:absolute; pointer-events:auto; }
.wb-overlay-popover { }
.wb-overlay-dialog { inset:0; display:flex; align-items:center; justify-content:center; background:rgba(32,33,35,.28); }
.wb-overlay-page { inset:0; display:flex; background:var(--ui-nav); }
.wb-overlay-surface { display:flex; flex-direction:column; min-width:0; min-height:0; outline:none; background:var(--ui-surface); border:1px solid var(--ui-line); border-radius:14px; box-shadow:0 12px 32px rgba(32,33,35,.18); overflow:hidden; }
.wb-overlay-dialog .wb-overlay-surface { width:min(520px, calc(100vw - 48px)); max-height:calc(100vh - 96px); }
.wb-overlay-popover .wb-overlay-surface { max-width:min(420px, calc(100vw - 16px)); max-height:calc(100vh - 16px); }
.wb-overlay-page .wb-overlay-surface { width:100%; height:100%; max-width:1100px; margin:0 auto; border:0; border-radius:0; box-shadow:none; }
.wb-overlay-bar { height:40px; flex-shrink:0; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 8px 0 14px; border-bottom:1px solid var(--ui-line); }
.wb-overlay-content { flex:1; min-height:0; overflow:auto; padding:14px; }
.wb-settings-section { padding:12px 0; border-bottom:1px solid var(--ui-line); }
.wb-settings-section:last-child { border-bottom:0; }
.wb-settings-section[data-active-section] { scroll-margin-top:12px; }
.wb-settings-section[data-active-section]>h2 { color:var(--ui-accent); }
.wb-settings-section>h2 { margin:0 0 8px; font-size:14px; }
.wb-settings-empty { color:var(--ui-ink-faint); }
.wb-drop-targets { position:absolute; inset:0; display:grid; grid-template-columns:25% 1fr 25%; grid-template-rows:22% 1fr 25%; gap:5px; padding:8px; z-index:4; background:#fafafacc; }
.wb-drop-targets>div { display:flex; align-items:center; justify-content:center; background:#f0f0f1dd; border:1px dashed #c4c6ca; border-radius:14px; color:var(--ui-ink-secondary); }
.wb-drop-targets>div:hover { background:var(--ui-hover); }
.wb-drop-top { grid-area:1/1/2/4; }.wb-drop-left { grid-area:2/1; }.wb-drop-main { grid-area:2/2; }.wb-drop-right { grid-area:2/3; }.wb-drop-bottom { grid-area:3/1/4/4; }
@media(max-width:800px) { .wb-bar small { display:none; }.wb-region-actions select { width:40px; } }
`
