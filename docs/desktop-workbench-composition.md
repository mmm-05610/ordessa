# Desktop Workbench composition: contract-first plan

Status: phases 1–2 (contract + Workbench composition implementation,
with the four review-round acceptance gaps fixed tests-first:
sidebar-less module switching clears the previous module sidebar,
single-view regions show no tab strip, openOverlay handles report every
close path truthfully and popovers close on anchor detach, error toast
layers above overlays with modal Tab containment) integrated into main
on 2026-09-26 via cherry-picks of 0bc1afafba, 16c085227d and 4575e5d6c1
from `feature/desktop-workbench-registration` (27/27 workbench tests,
146/146 desktop regression, typecheck and `test:electron` clean on the
integrated tree). Phases 3–5 (Chat package 791bdf10b4, product assembly
d6bc1ab193, review record 684bcd4f3f) remain on the branch and are not
in main; the branch carries the full phase history and follow-up
registry (Chat presentation parity, legacy conversation retirement
decision) in `docs/known-issues.md` §Desktop.

## Ownership

- `apps/desktop` owns the Electron lifecycle and generic extension host, not
  business navigation or conversation state.
- `packages/desktop-platform/contracts/workbench` owns public Workbench types.
  The current v1 `Workbench` methods remain available while the optional
  `composition` capability is introduced. A consumer requiring it must reject
  absence explicitly; it must not silently fall back to hard-coded view IDs.
- `plugins/workbench` owns registration, per-window selection, layout, tabs,
  overlays, settings placement, focus and dismissal. It never owns an ACP
  channel, prompt, approval, project or connector lifecycle.
- A future Chat package owns its module contribution, project/session sidebar,
  conversation, composer, reasoning, tool and approval presentation. Workflow
  can register a peer module without importing Chat.
- Connectors and connection services own backend communication and channel
  state. Removing a view or switching modules does not imply release/cancel.
- `products/desktop` only selects enabled extensions. It does not import their
  components or interpret their internal IDs.

## Registration surface

1. `WorkbenchModule` is one navigation item plus a `homeViewId` and optional
   `sidebarViewId`. Navigation is derived from this descriptor, not separately
   hard-coded by the Workbench. The module owns its two views and registers
   them with the existing `addView`. The home view must be a main-region view;
   the sidebar view, if present, must be a left-region view. Registration order
   may vary, but `activateModule` must check both bindings before changing
   selection. An absent or mismatched view is a visible error, not a fallback.
2. Existing `View` registration continues. Main, right and bottom support
   tabs; a single view needs no visible tab strip. Top/left region and
   full-page remain compatibility forms until their consumers migrate.
   Closing or hiding a view is UI state only. It must not call connector
   release, cancel a run or discard a pending approval.
3. `WorkbenchOverlay` has three presentations: anchored popover, modal dialog
   and page overlay. `openOverlay` returns a disposable handle and requires a
   live anchor for a popover; a missing/disconnected anchor must fail or close
   explicitly. The Workbench owns one stack, focus restoration, Escape,
   accessibility modality and narrow-window bounds. The contributor owns
   content and can request close through its component prop. No arbitrary
   z-index or independent plugin-level overlay roots.
4. `WorkbenchSettingsSection` contributes a section to Workbench settings.
   The contributor owns data and controls; the Workbench owns grouping and
   placement. A section whose contributor unloads disappears from settings.

All contribution IDs are stable and unique within their registry. Each
registration belongs to a `ResourceScope` and returns `IDisposable`. Duplicate
IDs and late writes to closed scopes fail. Removing a contributor removes its
navigation, views, overlays and settings entry. Window-local Workbench state
is distinct from shared connection/channel state.

`composition` is optional **only for the v1→v2 migration**: the baseline
implementation does not offer it. Phase 2 must implement the complete
`WorkbenchComposition` capability atomically. Phase 3 Chat must require it
and fail activation clearly when absent; optional typing is not permission
for a permanent legacy fallback. No new persisted identifiers are introduced
in phases 0–1.

## Screen structure

Use one full left sidebar rather than a permanent narrow rail. Its upper
navigation takes natural height; the active module's project/session content
fills the remainder and scrolls independently. Main is the primary tab area;
right and bottom are optional tab areas. Do not reserve blank space for
unregistered regions. The top chrome stays product-neutral. Settings and
other temporary tasks use the registered overlay system.

## Phased handoff

| Phase | Sole implementation owner | Gate before proceeding |
| --- | --- | --- |
| 0 Design | Main review session, docs only | Ownership, missing-resource behavior and counterexamples fixed here |
| 1 Contract | `contracts/workbench` only | Typecheck and legacy v1 assignability pass; no runtime claim |
| 2 Shell | `plugins/workbench` only | Empty shell, module/view binding, tabs, overlays, settings and unload counterexamples pass |
| 3 Chat | One Chat package only | Chat absent/present; no Workbench/ACP internals import; conversation state survives UI switching |
| 4 Assembly | `products/desktop` only | Manifest activates new composition; root lockfile update separately authorised if needed |
| 5 Review | Main reviewer, no implementation writes | Independent cross-package regressions, Electron smoke and visual check |

The main agent may inspect, specify, dispatch, review and run tests but must
not write implementation code. Each executor writes only its assigned package;
cross-package needs are reported to the main agent and scheduled serially.
An integration failure goes back to the owning package rather than being
patched in the review session. No push, main merge, service restart or real
model call is authorised by this plan.

## Non-negotiable counterexamples for phase 2

- Empty product: the Workbench mounts without any module or business plugin.
- Module absent: removing Chat erases its navigation/sidebar/main contribution
  but does not break a peer Workflow module.
- Missing default view: module activation rejects without selecting an
  unrelated view or showing false success.
- Duplicate ID / closed scope: registration fails; old UI does not linger.
- Hide/close/switch: no ACP release or cancel is emitted by Workbench.
- Overlay owner unload / dead popover anchor: the overlay closes and focus is
  restored to a connected safe target.
- Single tab and narrow window: no empty tab strip, clipped modal or unusable
  navigation. Tests must fail when required contributions are missing; a
  zero-match assertion is not evidence by itself.

## ZCode source boundary for the later Chat phase

The existing audit `docs/zcode-borrow-points.md` identifies reasoning and
tool-call presentation references. Re-check exact source, dependencies and
license/NOTICE provenance at the pinned upstream revision before copying a
file. Prefer design/presentation reuse; do not bring in ZCode's store, RPC or
agent state model, and do not translate ACP frames merely to satisfy a UI
component. Record any copied source and notices in `docs/ui-reuse-log.md`.
