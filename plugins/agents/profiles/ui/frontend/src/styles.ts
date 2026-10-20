export const profileSettingsCss = `
.profile-settings-surface{max-width:900px;color:var(--ordessa-color-text,#242426);font:13px/1.5 system-ui,sans-serif}
.profile-settings-surface h2{font-size:22px;font-weight:500;margin:0}
.profile-settings-surface h3{font-size:16px;font-weight:500;margin:0 0 8px}
.profile-settings-surface p{color:var(--ordessa-color-muted,#77777e);overflow-wrap:anywhere}
.profile-settings-surface button{padding:7px 10px;border:1px solid var(--ordessa-color-border,#dedee1);border-radius:8px;background:var(--ordessa-color-bg,#fafafa);color:inherit;font:inherit;cursor:pointer}
.profile-settings-surface button:disabled{cursor:default;opacity:.55}
.profile-settings-surface :focus-visible{outline:2px solid #548fe5;outline-offset:2px}
.profile-reader-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:18px}
.profile-reader-heading p{margin:5px 0 0}
.profile-reader-list{list-style:none;margin:0;padding:0;border:1px solid var(--ordessa-color-border,#e7e7e9);border-radius:10px}
.profile-reader-list li+li{border-top:1px solid var(--ordessa-color-border,#e7e7e9)}
.profile-reader-list button{display:flex;width:100%;flex-direction:column;align-items:flex-start;gap:3px;border:0;border-radius:0;background:transparent;text-align:left}
.profile-reader-list li:first-child button{border-radius:10px 10px 0 0}
.profile-reader-list li:last-child button{border-radius:0 0 10px 10px}
.profile-reader-list button[aria-current=true]{background:var(--ordessa-color-surface,#f3f5f8)}
.profile-reader-list small{color:var(--ordessa-color-muted,#77777e);overflow-wrap:anywhere}
.profile-reader-detail{margin-top:18px;padding:16px;border:1px solid var(--ordessa-color-border,#e7e7e9);border-radius:10px;min-width:0}
.profile-reader-detail pre{max-height:50vh;overflow:auto;padding:12px;border-radius:8px;background:var(--ordessa-color-bg,#f7f7f8);white-space:pre-wrap;overflow-wrap:anywhere}
.profile-reader-boundary{margin-top:18px;font-size:12px}
@media(prefers-color-scheme:dark){.profile-reader-list button[aria-current=true]{background:var(--ordessa-color-surface,#303032)}}
`
