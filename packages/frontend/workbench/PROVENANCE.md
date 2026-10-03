# Third-party source provenance — Workbench unified sidebar

Fixed upstream: ZCode @ `29628c9acdb81b703bbd4080c207a0e7ce5e276e`
(https://github.com/zai-org/ZCode), license Apache-2.0 (see upstream `LICENSE`).
Source paths below are relative to `packages/ui/src/` of that revision.
Registration categories follow `docs/design/workbench-sidebar/plan.md` §1.

## Ported pure functions (code copied with modification)

| Upstream file · symbol | Target | Modification |
| --- | --- | --- |
| `app-shell/WorkspaceShellLayout.tsx` · `clampWorkspaceSidebarWidth` (lines 131–141) and the width-bound constants (lines 99–105) | `src/sidebar-width.ts` | Ordessa bounds: MIN 220px (upstream 264), MAX = min(360px, container×40%) (upstream ratio 0.5 with no absolute cap); floor/cap conflict resolves by lowering the floor to the cap instead of upstream's raise-the-cap, and is exposed as `constrained` so the shell keeps its collapse affordance; no localStorage persistence, no legacy-ratio migration, no pointer resize engine (react-resizable-panels owns resizing, keyboard step and Enter-collapse — upstream's `handleWorkspaceSidebarResizeKeyDown` was NOT ported). |

## Structural extraction (JSX/CSS skeleton reused, no business logic)

| Upstream file · region | What was taken | What was NOT taken |
| --- | --- | --- |
| `WorkspaceSidebar.tsx` · `aside` skeleton (lines 1252–1258: `flex h-full flex-col overflow-hidden` + middle `relative flex-1 min-h-0 overflow-hidden`; scroll region line 1357 `flex-1 min-h-0 overflow-y-auto`) | Four-segment column skeleton (fixed header/footer, `min-h-0` scroll middle) expressed as plain CSS classes in `styles.ts` | tasks/workspaces sorting, file-tree switch, stores/services, remote connection, new-task/plugin-store/automation entries, dnd-kit, i18n |
| `WorkspaceSidebarFooter.tsx` (whole file, structure only) | Idea of a stable bottom tool strip inside the sidebar column, contributing slots rendered once | account, subscription, usage, theme persistence, remote control, auth |

## Reference only (look-and-feel, no code copied)

| Upstream file | Note |
| --- | --- |
| `WorkspaceSidebar/WorkspaceSidebarCollapsedRail.tsx` | Only the principle "collapsed state keeps a visible, accessibly-named restore button". The rail itself is NOT copied; Ordessa puts the restore control in the main-region header. |
| `WorkspaceSidebar.tsx` nav row metrics | Row height ~30–32px, unified icon column, rounded selected background — reimplemented from the Ordessa design tokens in `styles.ts`. |

No ZCode npm dependency was added. No ZCode business import, string, or asset is
present in this package. Verification: grep this package for upstream identifiers.
