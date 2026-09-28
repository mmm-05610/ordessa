# @ordessa/plugin-permissions-chat — Chat approval region (Permissions domain)

The Permissions contribution into Chat's published API (design task T06;
FR-04/FR-08/FR-09, US2): a restricted approval region that renders the real
operation category, target, policy source and selectable scopes of a pending
approval, and offers exactly three decisions — 允许一次 / 允许受限范围 / 拒绝.

## The UI is never an authority

- A button press only sends `permissions.approvals.decide` through the
  injected `PermissionsApprovalTransport` (no fetch/IPC lives in this
  package); the card shows **待确认** until the backend reports the settled
  decision AND the native owner receipt is confirmed. There is no optimistic
  "已决定" write: the displayed state derives solely from backend facts
  (`computeApprovalCardModel` gives local UI state no path to `decided`).
- `already_recorded` renders the existing decision and closes the controls;
  `invalid`, stale-version/expired views and cross-session `ChatLocation`
  mismatches make the card non-actionable with a text reason.
- Transport error / timeout / `unknown` result: the ALLOW actions are
  disabled and only 查询/恢复 (read-only query) remains — a disconnect never
  means allow (contracts.md §C3/§C4 headless fail-closed rule).
- An `unknown` native receipt renders 待确认/unknown, never safe/allowed.
- Refusal codes render from `PERMISSIONS_REFUSAL_CODES`, the TS mirror of the
  Python `RefusalCode` enum; the equality against
  `plugins/permissions/api/src/ordessa_permissions_api/codes.py` (parsed, not
  re-typed) and against the backend wire vocabulary in
  `plugins/permissions/backend/src/ordessa_permissions_backend/plugin.py`
  (method ids + required params) is enforced by
  `tests/contract-consistency.test.ts`. Sentences name which target/action is
  limited by which layer; tool arguments and free-form backend text never
  reach the render path.
- Contributions are built with Chat's real `chatContribution()` factory and
  live in Chat's own slots (`session.auxiliary`, `content.renderers` with
  kind `ordessa.permissions.approval-request`). Chat's registry enforces
  duplicate id/contentKind refusal and scope withdrawal; closing the owning
  scope removes the region, and a re-mounted card carries no authority.
- Masked decode: `decodeApprovalPayload` is a whitelist projection — extra
  payload keys (arguments, credentials) are dropped, malformed payloads
  decode to `null` (readable fallback), never a throw.

## Settings region (T011, rewired by T015) — 「权限与审批」

`src/settings-region.ts` contributes the Permissions domain's own Settings
region through the platform's real seam —
`WorkbenchComposition.forScope(scope).addSettingsSection`
(`packages/workbench/api/workbench.ts:41`, registry at
`packages/workbench/src/model.ts:124`); the tests assert against a real
`createWorkbench(...)` registry snapshot, and scope disposal withdraws the
contribution. Since T015 every policy fact is driven by a real read-only
round-trip of the wire method **`permissions.policy.describe`** through the
injected transport (tests fake the transport with the exact closed shape;
no network). The region runs the strict decoder itself: the chosen rule for
unknown/extra/missing keys is **refuse** — the whole round-trip fails to a
local alert and partial facts are never rendered. Four content areas per
`docs/design/safety-controls/ux.md` §Settings:

- **规则来源** — derived from the describe ceiling/intent rows plus the
  distinct `policySource` strings the approval facts carry; nothing is typed
  in. The method id, param names and every response key set of the decoder
  are asserted equal to the backend source (`plugin.py` registration +
  `describe.py` constants and dict literals, parsed) by
  `tests/contract-consistency.test.ts`.
- **组织上限（只读）** — describe rows (`hardDenies`/`requireApproval`
  entries) rendered read-only; trusted rows are `aria-disabled` with the
  stated reason 「该项由组织/宿主限制」; `attemptCeilingWidening` is
  unconditionally refused with the stable `POLICY_CEILING_VIOLATION` code and
  the region exposes no ceiling-write path at all (refusal surfaced, never a
  silent downgrade; rendered facts byte-identical after an attempt). A
  ceiling whose `source` is unverified (or otherwise untrusted) is rendered
  in a separate 非可执行 disclosure list and never presented as an
  organization limit; an absent ceiling stays modelled:
  「未证实没有上限，不等于没有上限」. `ready:false` renders 「无法证明生效」
  and marks every ceiling row non-enforceable — never 「未安装」.
- **用户默认意图** — describe intent rows; `desiredMode` is the closed
  `{brand, name}` pair and is only ever rendered as `brand:name` with the
  「不做跨品牌等价」 disclaimer — never translated into a cross-brand label,
  and a bare string or key-mangled pair is refused by the decoder.
  `needsReview` findings surface as 「待复核…不放行」 rows carrying their
  reason with **no interactive control at all** — the region exposes no path
  to allow, approve or clear them (`region-registry` and describe round-trip
  tests assert the surface).
- **审批历史过滤** — approval payloads are host-contributed (see the
  registered gap below) and still run through the `decodeApprovalPayload`
  whitelist before display; filters (status / decision / session) are a pure
  projection over decoded facts and can never add rows. The only writable
  local state is that display filter — a forged write selects nothing and
  rewrites no fact.

State machine: describe answer `no-provider` ⇒ the section is never
registered (no broken placeholder); `error`, a rejected transport call or an
undecodable payload ⇒ a registered local `[role=alert]` error whose wording
never speaks of installation; `ok` + strict decode ⇒ facts above. Awaiting a
real composition run: jsdom-level DOM/ARIA assertions only (focus, roles,
labels, disabled-with-reason); no screen-reader or Electron smoke pass.

**Registered read gap (honest, remaining):** the backend registers
`decide`/`query`/`policy.describe`; describe's closed answer carries policy
facts (ceilings/intents/needsReview) but **no approval rows** — the
「审批历史」 data still arrives through the host-contributed
`PermissionsApprovalFactsSource` (the same payloads the Chat content
renderer receives), not an invented list method. Product composition binds
the transport and this source to the live Server wire; that binding is
integration work outside this package.

## Chat input-area mode entry (T013) — refusal path, built honestly

`src/mode-entry.ts` contributes a short per-brand mode entry through Chat's
real `composer.toolbar` slot (ux.md §Chat). It lists **only** what an injected
`PermissionsModeCapabilitySource` attests for the exact pin
(`harnessId + nativeVersion`); the brand name never keys anything — with no
attestation the entry renders nothing (proven: identical empty output for a
`claude-code` pin and an unknown pin). This tree provides no per-pin mode
capability read surface (the backend has no such wire method;
`api/brand.py BRAND_NATIVE_MODES` is a static per-brand vocabulary and the
adapters only *refuse* loosening modes) and no mode **write** channel, so the
shipped path is the refusal one: an attested list (when a future host supplies
one) is displayed bound to its pin, and selecting it records a local draft
that explicitly 「未声称已生效」. No menu is invented; no popover or second
conversation container is added.

## Package-local checks

```
npx vitest run                      # 93 tests, exit 0
npx tsc -p tsconfig.json --noEmit   # exit 0
```

## Still unproven (honest register)

- No real desktop composition run: the entry (`src/entry.ts`) registers
  nothing; the actual activation — resolving `ChatContributionsToken`,
  binding `ApprovalCardKey`/`ApprovalRegionKey` to Chat's outlet, building the
  host `PermissionsDescribeTransport` against the live Server wire and the
  `PermissionsApprovalFactsSource` from contributed approval payloads — is
  integration work outside this batch.
- No real backend or native peer was contacted; every outcome branch was
  driven by the in-memory fake transport serving the closed describe shape.
- Keyboard/ARIA behavior is asserted at the DOM attribute level under jsdom;
  a screen-reader or Electron smoke pass has not been run.
- The mode-entry `PermissionsModeCapabilitySource` still has no live supplier
  (the backend exposes no per-pin mode-capability read method), so that path
  keeps `src/entry.ts` side-effect free and proven against injected fakes only.
