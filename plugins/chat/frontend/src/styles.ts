// Chat styles, scoped by the `chat-` prefix and injected per page instance
// (same pattern as the existing plugins). Light/dark theme via CSS variables
// on [data-chat-theme]; the Streamdown surface is isolated here — the platform
// base components never load Markdown styles (research-plan §2).
export const chatStyles = `
.chat-page, .chat-placeholder { display:flex; flex-direction:column; height:100%; min-height:0; min-width:0; position:relative;
  --chat-border: #e8e8e8; --chat-bg: #ffffff; --chat-bg-alt: #f6f6f6; --chat-fg: #202123; --chat-fg-subtle: #818388;
  --chat-accent: #3b82f6; --chat-danger: #b3261e; --chat-user-bubble: #edf4ff; --chat-code-bg: #f6f6f6; }
.chat-page *, .chat-placeholder * { box-sizing:border-box; }
.chat-page :focus-visible { outline:2px solid var(--chat-accent); outline-offset:3px; }
.chat-page[data-chat-theme="dark"], .chat-placeholder[data-chat-theme="dark"] {
  --chat-border: #33333d; --chat-bg: #1b1b22; --chat-bg-alt: #23232c; --chat-fg: #e9e9ef; --chat-fg-subtle: #9d9daa;
  --chat-accent: #8fa4ff; --chat-danger: #ff8b84; --chat-user-bubble: #2a2f45; --chat-code-bg: #24242e; }
.chat-placeholder { align-items:center; justify-content:center; gap:8px; background:var(--chat-bg); color:var(--chat-fg); }
.chat-placeholder h2 { margin:0; font-size:18px; }
.chat-connection-choices { display:flex; flex-wrap:wrap; justify-content:center; gap:12px; }
.wb .chat-connector-choice { border:1px solid var(--chat-border); background:var(--chat-bg-alt); padding:10px 18px; border-radius:10px; font-size:14px; }
.chat-page { background:var(--chat-bg); color:var(--chat-fg); font:14px/1.7 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
.chat-page-head { display:flex; flex:none; align-items:center; justify-content:space-between; gap:12px; min-height:48px; padding:8px 24px; }
.chat-page-head>div:first-child { min-width:0; }
.chat-page-head small { color:var(--chat-fg-subtle); letter-spacing:.08em; text-transform:uppercase; font-size:11px; }
.chat-page-head h2 { margin:0; font-size:13px; font-weight:550; max-width:70ch; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.chat-page-head-actions { display:flex; align-items:center; gap:10px; }
.chat-run-state { font-size:12px; color:var(--chat-fg-subtle); border:1px solid var(--chat-border); border-radius:999px; padding:2px 10px; }
.chat-run-state[data-status="idle"] { display:none; }
.chat-page-head .chat-primary-action { color:var(--chat-fg-subtle); background:transparent; font-size:12px; padding:5px 9px; }
.chat-page-head .chat-primary-action:hover { background:var(--chat-bg-alt); }
.chat-primary-action { background:var(--chat-accent); color:#fff; border:none; border-radius:8px; padding:7px 14px; font-size:13px; cursor:pointer; }
.chat-primary-action:disabled { opacity:.45; cursor:default; }
.chat-icon-action { background:transparent; color:var(--chat-fg); border:0; border-radius:50%; width:30px; height:30px; padding:0; cursor:pointer; font-size:21px; flex:none; }
.chat-icon-action:hover { background:var(--chat-bg-alt); }
.chat-ghost-action { background:transparent; border:none; color:var(--chat-accent); cursor:pointer; font-size:12px; padding:2px 6px; border-radius:6px; }
.chat-ghost-action:hover { background:var(--chat-bg-alt); }
.chat-note { margin:4px auto; width:min(760px,calc(100% - 48px)); color:var(--chat-fg-subtle); font-size:12px; }
.chat-error { margin:4px auto; width:min(760px,calc(100% - 48px)); color:var(--chat-danger); font-size:12px; overflow-wrap:anywhere; }
.chat-thread-stage { position:relative; display:flex; flex:1; min-height:0; }
.chat-draft-welcome { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:24px; gap:18px; pointer-events:none; }
.chat-draft-welcome button { pointer-events:auto; }
.chat-draft-welcome h1 { font-size:clamp(20px,2.1vw,28px); font-weight:500; line-height:1.45; margin:0; text-align:center; }
.chat-welcome-mark { font-size:34px; line-height:1; color:#bfc1c5; }
.chat-scroll-wrap { position:relative; flex:1; min-height:0; display:flex; }
.chat-scroll-viewport { flex:1; min-width:0; overflow-y:auto; padding:30px 24px 32px; scrollbar-width:thin; scrollbar-color:#d5d5d5 transparent; }
.chat-scroll-content { display:flex; flex-direction:column; gap:14px; max-width:760px; margin:0 auto; width:100%; }
.chat-thread-list { display:flex; flex-direction:column; gap:18px; min-width:0; }
.chat-scroll-resume { position:absolute; bottom:10px; left:50%; transform:translateX(-50%); background:var(--chat-bg-alt);
  border:1px solid var(--chat-border); border-radius:999px; padding:4px 10px; }
.chat-message { display:flex; flex-direction:column; }
.chat-message-user { align-items:flex-end; }
.chat-message-user .chat-message-body { max-width:85%; }
.chat-message-user .chat-user-text { background:var(--chat-user-bubble); border-radius:18px 18px 5px 18px; padding:10px 15px; white-space:pre-wrap; overflow-wrap:anywhere; }
.chat-message-assistant .chat-message-body { max-width:100%; }
.chat-message-actions { display:flex; gap:6px; margin-top:4px; opacity:0; }
.chat-message:hover .chat-message-actions, .chat-message:focus-within .chat-message-actions { opacity:1; }
.chat-status-note { color:var(--chat-fg-subtle); font-size:12px; margin-top:4px; }
.chat-md { font-size:14px; }
.chat-md > :first-child { margin-top:0; }
.chat-md pre { margin:0; }
.chat-md-fallback { white-space:pre-wrap; font-size:14px; }
.chat-md-link { color:var(--chat-accent); background:none; border:none; padding:0; font:inherit; cursor:pointer; text-decoration:underline; text-underline-offset:3px; word-break:break-all; }
.chat-md-link-inert { cursor:default; text-decoration-style:dotted; color:var(--chat-fg-subtle); }
.chat-md-inline-code { background:var(--chat-code-bg); border-radius:5px; padding:1px 5px; font-family:ui-monospace,monospace; font-size:13px; }
.chat-code { border:1px solid var(--chat-border); border-radius:10px; margin:10px 0; overflow:hidden; background:var(--chat-code-bg); }
.chat-code-head { display:flex; align-items:center; justify-content:space-between; padding:6px 10px; border-bottom:1px solid var(--chat-border); font-size:12px; color:var(--chat-fg-subtle); }
.chat-code-body { margin:0; padding:10px 12px; font-family:ui-monospace,monospace; font-size:13px; line-height:1.5; overflow:auto; }
.chat-code-scroll { white-space:pre; }
.chat-code-wrap { white-space:pre-wrap; word-break:break-word; }
.chat-code-line { display:inline-block; width:100%; }
.chat-reasoning { margin:0; width:fit-content; max-width:100%; }
.chat-reasoning-head { display:flex; align-items:center; gap:8px; }
.chat-reasoning-trigger { display:flex; align-items:center; gap:6px; background:transparent; border:none; color:var(--chat-fg-subtle);
  cursor:pointer; font-size:12px; padding:2px 0; width:100%; text-align:left; }
.chat-reasoning-chevron { transition:transform .15s; }
.chat-reasoning[data-state="open"] .chat-reasoning-chevron { transform:rotate(90deg); }
.chat-reasoning-label { color:var(--chat-fg-subtle); }
.chat-reasoning-content { padding:8px 12px; margin-top:6px; border-left:2px solid var(--chat-border); }
.chat-reasoning-text { margin:0; white-space:pre-wrap; color:var(--chat-fg-subtle); font-size:13px; font-family:inherit; }
.chat-reasoning[data-streaming="true"] .chat-reasoning-label { color:var(--chat-accent); }
.chat-tool { border:1px solid var(--chat-border); border-radius:12px; overflow:hidden; }
.chat-tool-summary { display:flex; align-items:center; gap:8px; width:100%; background:var(--chat-bg-alt); border:none;
  color:var(--chat-fg); cursor:pointer; font-size:12px; padding:10px 12px; text-align:left; min-width:0; }
.chat-tool-chevron { color:var(--chat-fg-subtle); flex:none; }
.chat-tool-kind { flex:none; color:var(--chat-fg-subtle); font-size:12px; }
.chat-tool-title { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
.chat-tool-state { margin-left:auto; flex:none; display:inline-flex; align-items:center; gap:5px; font-size:12px; color:var(--chat-fg-subtle); }
.chat-tool-state[data-state="failed"] { color:var(--chat-danger); }
.chat-tool-content { padding:8px 10px; border-top:1px solid var(--chat-border); }
.chat-tool-detail { display:flex; flex-direction:column; gap:8px; min-width:0; }
.chat-tool-params, .chat-tool-output { margin:0; background:var(--chat-code-bg); border-radius:8px; padding:8px 10px;
  font-family:ui-monospace,monospace; font-size:12px; overflow:auto; max-height:180px; white-space:pre-wrap; word-break:break-word; }
.chat-tool-error { display:flex; align-items:center; gap:8px; color:var(--chat-danger); font-size:12px; flex-wrap:wrap; }
.chat-tool-note { color:var(--chat-fg-subtle); font-size:12px; }
.chat-tool-spin { animation:chat-rotate 1.1s linear infinite; transform-origin:center; }
@keyframes chat-rotate { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .chat-tool-spin { animation:none; } }
.chat-command { display:flex; flex-direction:column; gap:6px; min-width:0; }
.chat-command-line { background:var(--chat-code-bg); border-radius:8px; padding:7px 10px; font-family:ui-monospace,monospace; font-size:12px; overflow-x:auto; white-space:pre; }
.chat-execute { position:relative; min-width:0; }
.chat-execute-viewport { margin:0; max-height:5.2em; overflow:auto; background:var(--chat-code-bg); border-radius:8px;
  padding:7px 10px; font-family:ui-monospace,monospace; font-size:12px; white-space:pre-wrap; word-break:break-word; }
.chat-execute-follow { position:absolute; right:8px; bottom:8px; display:flex; gap:6px; align-items:center; }
.chat-execute-new { font-size:11px; color:var(--chat-accent); }
.chat-execute-meta { display:flex; gap:12px; color:var(--chat-fg-subtle); font-size:11px; margin-top:2px; }
.chat-compose { position:relative; flex:none; width:min(808px,100%); align-self:center; background:var(--chat-bg); padding:8px 24px 12px; display:flex; flex-direction:column; gap:8px; }
.chat-composer-card { border:1px solid var(--chat-border); border-radius:22px; background:var(--chat-bg); padding:12px 12px 9px; box-shadow:0 2px 12px rgba(0,0,0,.04); }
.chat-composer-card:focus-within { border-color:#c3c8d0; }
.chat-composer-bottom { display:flex; align-items:center; gap:8px; min-height:32px; }
.chat-sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
.chat-send-action { flex:none; width:32px; height:32px; border-radius:50%; padding:0; font-size:21px; display:flex; align-items:center; justify-content:center; }
.chat-send-action[data-testid="chat-stop"] { width:auto; min-width:32px; padding:0 10px; border-radius:16px; font-size:11px; }
.chat-compose .chat-error,.chat-compose .chat-note { width:100%; margin:0; }
.chat-compose-block { margin:0; color:var(--chat-fg-subtle); font-size:12px; }
.chat-compose-meta { margin:0; color:var(--chat-fg-subtle); font-size:10px; text-align:center; }
.chat-compose-toolbar { flex:1; display:flex; flex-wrap:wrap; gap:4px 8px; align-items:center; justify-content:flex-end; min-height:0; min-width:0; }
.chat-toolbar-item { min-width:0; max-width:100%; }
.chat-toolbar-item:empty { display:none; }
.chat-toolbar-item p { margin:0; font-size:12px; color:var(--chat-fg-subtle); max-width:320px; }
.chat-toolbar-item [data-profile-picker] { flex-wrap:nowrap; }
.chat-toolbar-item button,.chat-toolbar-item select { white-space:nowrap; }
.chat-toolbar-item [data-profile-picker]>select { max-width:200px; }
.chat-input-row { display:flex; align-items:flex-end; gap:8px; }
.chat-input-text { flex:1; width:100%; min-width:0; resize:none; min-height:58px; max-height:180px; border:0; border-radius:10px;
  background:transparent; color:var(--chat-fg); padding:0 4px 10px; font:inherit; outline:none; }
.chat-input-text::placeholder { color:#a6a8ad; }
.chat-input-text:focus-visible { outline:none; }
.chat-approvals { display:flex; flex-direction:column; gap:8px; }
.chat-approval { border:1px solid var(--chat-accent); border-radius:10px; padding:8px 12px; }
.chat-approval-head { display:flex; gap:8px; align-items:baseline; }
.chat-approval-state { color:var(--chat-fg-subtle); font-size:12px; }
.chat-approval-detail { margin:4px 0; font-size:13px; }
.chat-approval-muted { color:var(--chat-fg-subtle); font-size:12px; margin:2px 0; }
.chat-approval-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:6px; }
.chat-approval-actions button { border:1px solid var(--chat-border); background:var(--chat-bg-alt); color:var(--chat-fg);
  border-radius:8px; padding:5px 12px; font-size:13px; cursor:pointer; }
.chat-approval-actions button:disabled { opacity:.45; cursor:default; }
.chat-approvals-more { color:var(--chat-fg-subtle); font-size:12px; }
.chat-attachments { display:flex; gap:8px; flex-wrap:wrap; }
.chat-attachment { display:flex; align-items:center; gap:8px; border:1px solid var(--chat-border); border-radius:10px; padding:6px 8px; max-width:320px; }
.chat-attachment-thumb { border:none; background:none; padding:0; cursor:zoom-in; }
.chat-attachment-thumb img { width:40px; height:40px; object-fit:cover; border-radius:6px; display:block; }
.chat-attachment-meta { display:flex; flex-direction:column; min-width:0; }
.chat-attachment-name { font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.chat-attachment-phase { font-size:11px; color:var(--chat-fg-subtle); }
.chat-attachment-phase[data-phase="failed"] { color:var(--chat-danger); }
.chat-attachment-reason { word-break:break-all; }
.chat-preview-backdrop, .chat-dialog-backdrop, .chat-panel-backdrop { position:absolute; inset:0; background:rgba(0,0,0,.35);
  display:flex; align-items:center; justify-content:center; z-index:30; }
.chat-preview { background:var(--chat-bg); color:var(--chat-fg); border-radius:12px; max-width:70ch; max-height:80%; overflow:auto; }
.chat-preview-head { display:flex; justify-content:space-between; align-items:center; padding:10px 14px; border-bottom:1px solid var(--chat-border); }
.chat-preview-body { padding:14px; }
.chat-preview-body img { max-width:100%; }
.chat-dialog { background:var(--chat-bg); color:var(--chat-fg); border-radius:12px; width:min(560px, 92vw); max-height:80%; display:flex; flex-direction:column; }
.chat-dialog-head { display:flex; justify-content:space-between; align-items:center; padding:12px 16px; }
.chat-dialog-head h2 { margin:0; font-size:16px; }
.chat-dialog-search { padding:0 16px 10px; }
.chat-dialog-search input { width:100%; box-sizing:border-box; border:1px solid var(--chat-border); border-radius:8px; padding:8px 10px; background:var(--chat-bg-alt); color:var(--chat-fg); }
.chat-dialog-list { overflow:auto; padding:0 8px 8px; display:flex; flex-direction:column; gap:4px; min-height:120px; }
.chat-dialog-row { display:grid; grid-template-columns:auto 1fr auto; gap:10px; align-items:center; text-align:left;
  border:1px solid var(--chat-border); background:var(--chat-bg-alt); border-radius:8px; padding:8px 10px; cursor:pointer; color:var(--chat-fg); }
.chat-dialog-row:disabled { opacity:.5; cursor:default; }
.chat-dialog-row-label { font-weight:600; font-size:13px; }
.chat-dialog-row-path { color:var(--chat-fg-subtle); font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.chat-dialog-row-source { font-size:11px; border:1px solid var(--chat-border); border-radius:999px; padding:1px 8px; color:var(--chat-fg-subtle); }
.chat-dialog-note { color:var(--chat-fg-subtle); font-size:12px; padding:4px 16px; }
.chat-dialog-error { display:flex; gap:8px; align-items:center; color:var(--chat-danger); font-size:12px; padding:4px 16px; }
.chat-dialog-foot { display:flex; gap:10px; align-items:center; border-top:1px solid var(--chat-border); padding:10px 16px; }
.chat-dialog-foot button { border:1px solid var(--chat-border); background:var(--chat-bg-alt); color:var(--chat-fg); border-radius:8px; padding:6px 12px; cursor:pointer; }
.chat-panel-backdrop { inset:auto 24px calc(100% + 4px); align-items:flex-end; justify-content:center; background:transparent; z-index:20; }
.chat-panel { background:var(--chat-bg); color:var(--chat-fg); border:1px solid var(--chat-border); border-radius:12px;
  width:100%; max-height:min(360px,50vh); display:flex; flex-direction:column; box-shadow:0 5px 24px rgba(0,0,0,.09); }
.chat-panel-search { padding:10px 12px; border-bottom:1px solid var(--chat-border); }
.chat-panel-search input { width:100%; box-sizing:border-box; border:1px solid var(--chat-border); border-radius:8px; padding:7px 10px; background:var(--chat-bg-alt); color:var(--chat-fg); }
.chat-panel-list { overflow:auto; padding:6px; }
.chat-panel-group { font-size:11px; color:var(--chat-fg-subtle); text-transform:uppercase; letter-spacing:.06em; padding:6px 8px 2px; }
.chat-panel-row { display:flex; width:100%; gap:10px; align-items:baseline; border:none; background:transparent; color:var(--chat-fg);
  padding:7px 8px; border-radius:8px; cursor:pointer; text-align:left; }
.chat-panel-row[data-selected="true"] { background:var(--chat-bg-alt); }
.chat-panel-row[aria-disabled="true"] { cursor:default; opacity:.6; }
.chat-panel-row-main { display:flex; flex-direction:column; min-width:0; flex:1; }
.chat-panel-row-title { font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.chat-panel-row-desc { font-size:12px; color:var(--chat-fg-subtle); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.chat-panel-row-source { flex:none; font-size:11px; color:var(--chat-fg-subtle); border:1px solid var(--chat-border); border-radius:999px; padding:1px 8px; }
.chat-panel-row-disabled { flex:none; font-size:11px; color:var(--chat-fg-subtle); white-space:nowrap; }
.chat-panel-note { color:var(--chat-fg-subtle); font-size:12px; padding:8px; }
.chat-panel-source-error { display:flex; gap:8px; align-items:center; color:var(--chat-danger); font-size:12px; padding:6px 8px; }
.chat-connection-badge { font-size:12px; color:var(--chat-fg-subtle); border:1px solid var(--chat-border); border-radius:999px; padding:2px 10px; }
.chat-connection-badge[data-status="connected"] { display:inline-flex; align-items:center; justify-content:center; width:16px; height:22px; padding:0; border:0; }
.chat-connection-badge[data-status="connected"]::before { content:""; width:6px; height:6px; border-radius:50%; background:var(--ordessa-color-ok,#2e7d46); }
.wb .chat-page { --chat-bg:var(--ordessa-color-surface); --chat-bg-alt:var(--ui-sunken); --chat-fg:var(--ordessa-color-text); --chat-fg-subtle:var(--ordessa-color-muted); --chat-border:var(--ordessa-color-border); --chat-accent:var(--ordessa-color-accent); --chat-danger:var(--ordessa-color-danger); --chat-code-bg:var(--ui-sunken); --chat-user-bubble:color-mix(in srgb,var(--ordessa-color-accent) 9%,var(--ordessa-color-surface)); }
@media (max-width:650px) {
  .chat-page-head { padding:8px 14px; }
  .chat-scroll-viewport { padding:16px 14px 24px; }
  .chat-compose { padding:6px 12px 8px; }
  .chat-panel-backdrop { left:12px; right:12px; }
  .chat-compose-toolbar { gap:4px; }
  .chat-toolbar-item [data-profile-picker]>select { max-width:130px; }
  .chat-note,.chat-error { width:calc(100% - 28px); }
}
@media (prefers-reduced-motion:reduce) { .chat-reasoning-chevron { transition:none; } }
`
