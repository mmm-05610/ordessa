export const styles = `
.agent-panel { --ui-surface:#fff; --ui-nav:#f6f6f6; --ui-sunken:#f0f0f1; --ui-hover:#eaeaea; --ui-selected:#e3e4e6; --ui-line:#e8e8e8; --ui-ink:#202123; --ui-ink-secondary:#6b6e73; --ui-ink-faint:#9a9da2; --ui-accent:#3b82f6; --ui-bubble:#eff4fb; --ui-ok:#2e7d46; --ui-warn:#b26a00; --ui-error:#b3261e; --agent-ink:var(--ui-ink); --agent-muted:var(--ui-ink-secondary); --agent-line:var(--ui-line); --agent-blue:var(--ui-accent); --agent-wait:var(--ui-warn); box-sizing:border-box; height:100%; min-height:0; color:var(--agent-ink); font:13px system-ui,sans-serif; }
.agent-panel * { box-sizing:border-box; }
.agent-panel button,.agent-panel select { font:inherit; }
.agent-panel button { cursor:pointer; }
.agent-panel button:disabled { cursor:default; opacity:.5; }
.agent-panel :focus-visible { outline:2px solid var(--ui-accent); outline-offset:2px; }
.agent-sessions { display:flex; flex-direction:column; padding:6px 0; overflow:auto; background:var(--ui-nav); }
.agent-section-head { display:flex; align-items:center; justify-content:space-between; padding:6px 12px; color:var(--ui-ink-secondary); }
.agent-section-head h2 { margin:0; font:600 11px system-ui,sans-serif; letter-spacing:.02em; text-transform:none; color:var(--ui-ink); }
.agent-section-head button,.agent-actions button { color:var(--ui-ink-secondary); border:0; background:transparent; padding:4px 8px; border-radius:8px; font-size:12px; }
.agent-section-head button:hover:not(:disabled),.agent-actions button:hover:not(:disabled) { background:var(--ui-hover); color:var(--ui-ink); }
.agent-session-list { display:flex; flex-direction:column; padding:2px 8px; gap:1px; }
.agent-session-list button { width:100%; height:32px; border:0; border-radius:8px; text-align:left; background:transparent; padding:0 8px; display:flex; align-items:center; gap:8px; overflow:hidden; }
.agent-session-list button:hover { background:var(--ui-hover); }
.agent-session-list button[aria-current=true] { background:var(--ui-selected); }
.agent-actions { display:flex; padding:0 10px 6px; gap:5px; }
.agent-session-heading { border-top:1px solid var(--ui-line); margin-top:6px; padding-top:10px; }
.agent-session-list strong { flex:1; min-width:0; font-weight:500; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.agent-session-list small { flex:none; font:11px system-ui,sans-serif; color:var(--ui-ink-faint); }
.agent-session-group { margin:12px 16px 3px; color:var(--ui-ink-faint); font-size:11px; font-weight:550; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.agent-session-state { display:inline-flex; align-items:center; gap:4px; color:var(--ui-warn); font-size:11px; }
.agent-session-state::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor; }
.agent-session-state[data-status=running] { color:var(--ui-ok); }
.agent-empty,.agent-notice,.agent-error { margin:8px 16px; line-height:1.5; font-size:12px; }
.agent-empty { color:var(--ui-ink-faint); }.agent-notice { color:var(--ui-warn); }.agent-error { color:var(--ui-error); }
.agent-draft { border:1px solid var(--ui-line); border-radius:14px; background:var(--ui-surface); margin:4px 8px 8px; padding:6px 0; }
.agent-project-picker { display:flex; flex-direction:column; padding:2px 8px; gap:1px; }
.agent-project-picker button { width:100%; height:30px; border:0; border-radius:8px; text-align:left; background:transparent; padding:0 8px; font-size:12px; display:flex; align-items:center; overflow:hidden; }
.agent-project-picker button span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.agent-project-picker button:hover { background:var(--ui-hover); }
.agent-project-picker button[aria-pressed=true] { background:var(--ui-selected); }
.agent-sidebar-primary { display:grid; gap:3px; padding:8px 9px 7px; }
.agent-sidebar-primary button { border:0; background:transparent; color:var(--agent-ink); text-align:left; border-radius:8px; padding:9px 11px; font-size:12px; font-weight:550; }
.agent-sidebar-primary button:hover { background:var(--ui-hover); }
.agent-sidebar-primary span { display:inline-block; width:22px; color:var(--ui-ink-faint); font-size:16px; line-height:10px; vertical-align:middle; }
.agent-new-session::before { content:'✎'; display:inline-block; width:22px; color:var(--ui-ink-faint); font-size:16px; line-height:10px; vertical-align:middle; }
.agent-refresh { padding:2px 9px 8px; }
.agent-sidebar-sections { padding-bottom:14px; }
.agent-list-heading { color:var(--ui-ink-faint); padding:16px 14px 7px; font-size:10px; letter-spacing:.06em; text-transform:uppercase; }
.agent-recent-heading { margin-top:8px; border-top:1px solid var(--agent-line); }
.agent-project-row { display:flex; align-items:center; margin:1px 7px; border-radius:8px; min-height:32px; }
.agent-project-row:hover { background:var(--ui-hover); }
.agent-project-row button { border:0; background:transparent; color:var(--agent-ink); border-radius:8px; height:29px; }
.agent-project-expand { width:26px; flex:none; color:var(--ui-ink-faint)!important; transition:transform .15s; }
.agent-project-group[data-state=open] .agent-project-expand { transform:rotate(90deg); }
.agent-project-name { flex:1; min-width:0; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; text-align:left; padding:0 4px; font-weight:550!important; }
.agent-project-name::before { content:'▱'; margin-right:7px; font-size:15px; color:var(--agent-muted); }
.agent-project-name[aria-current=true] { color:var(--agent-ink); }
.agent-project-new { width:27px; flex:none; opacity:.45; font-size:18px!important; }
.agent-project-row:hover .agent-project-new,.agent-project-new:focus-visible { opacity:1; }
.agent-project-content { padding:1px 6px 4px 30px; }
.agent-session-item { border:0; border-radius:8px; background:transparent; color:var(--agent-ink); display:block; width:100%; padding:7px 8px; text-align:left; overflow:hidden; }
.agent-session-item:hover { background:var(--ui-hover); }
.agent-session-item[aria-current=true] { background:var(--ui-selected); color:var(--ui-ink); }
.agent-session-item strong { display:block; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; font-size:13px; font-weight:450; }
.agent-session-item small { display:block; font-size:10px; margin-top:2px; }
.agent-session-list { padding:2px 7px; }
.agent-draft { margin:0 8px 4px; border:0; border-radius:9px; padding:0; background:transparent; }
.agent-draft[open] { background:var(--ui-surface); border:1px solid var(--agent-line); }
.agent-draft-summary { display:flex; align-items:center; gap:8px; list-style:none; padding:7px 10px; font-size:12px; cursor:pointer; color:var(--agent-muted); }
.agent-draft-summary::-webkit-details-marker { display:none; }
.agent-draft-summary>span:nth-child(2) { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.agent-draft-summary:hover { background:var(--ui-hover); border-radius:8px; }
.agent-draft-edit { margin-left:auto; font-size:11px; color:var(--ui-ink-faint); }
@media (prefers-color-scheme:dark) {
 .agent-panel { --ui-surface:#232325; --ui-nav:#202022; --ui-sunken:#29292b; --ui-hover:#303033; --ui-selected:#36363a; --ui-line:#343438; --ui-ink:#ededee; --ui-ink-secondary:#a5a5ad; --ui-ink-faint:#81818a; --ui-error:#ff928b; }
}
.wb .agent-panel { --ui-surface:var(--ordessa-color-surface); --ui-nav:var(--ordessa-color-bg); --ui-sunken:color-mix(in srgb,var(--ordessa-color-text) 6%,var(--ordessa-color-bg)); --ui-hover:color-mix(in srgb,var(--ordessa-color-text) 4%,var(--ordessa-color-bg)); --ui-selected:color-mix(in srgb,var(--ordessa-color-text) 8%,var(--ordessa-color-bg)); --ui-line:var(--ordessa-color-border); --ui-ink:var(--ordessa-color-text); --ui-ink-secondary:var(--ordessa-color-muted); --ui-ink-faint:color-mix(in srgb,var(--ordessa-color-text) 45%,var(--ordessa-color-bg)); --ui-accent:var(--ordessa-color-accent); --ui-error:var(--ordessa-color-danger); }
@media (prefers-reduced-motion:reduce) { .agent-project-expand { transition:none; } }
`
