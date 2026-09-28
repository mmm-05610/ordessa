# command-templates — API / seam requests

Interface gaps discovered while implementing T00–T07. None of these were faked
inside this domain (no second registry, no second ACP client, no fabricated Chat
token). Each records the caller, the target operation, the DTO shape, the
failure counterexample, and the requested owner per
`specs/011-plugin-rollout/contracts/checkpoints.md` ("依赖不构成整线停机").

Poll state at freeze: at lane start all five `codex/011-*-ready` refs were absent
and `specs/011-plugin-rollout/checkpoints/` did not exist. During the session the
**chat-api** ref was published (`54ad26c1…`, producer z2, READY) but is not an
ancestor of `main`, so nothing was consumed here. The other four
(foundation/harness-api/profile-api/permissions-api) remain absent. Every item
below stays blocked on a producer's public, importable API reaching this tree via a
fixed-SHA merge (a main-agent git step), per
`specs/011-plugin-rollout/contracts/checkpoints.md` ("依赖不构成整线停机").

---

## REQ-CT-01 — Chat scoped `addInputSource` + draft-insert action (blocks T10; gates G08–G11)
- **Status update (mid-session):** the `chat-api` checkpoint published this seam.
  Ref `54ad26c15d8480823374d85590919ba6bcca60d2` (producer z2, status READY,
  implementation `a3ec20c04653c7b9a267023751c23d7499f14d4a`) exports
  `addInputSource`, `ChatInputSource`, `ChatInputEntryAction`
  (`insert-command{text}` | `add-content{prepare}` | `invoke{execute}`),
  `ChatContentReference`, `ChatDraftState`, `ChatSubmissionSnapshot`, and
  `ChatSubmissionResult` (`accepted|refused|unknown`). It is **not an ancestor of
  `main`**, so this package cannot import it yet.
- **Remaining ask (now integration, not invention):**
  1. **Main-agent git step:** merge `54ad26c1…` at its fixed SHA into the lane, then
     run the command-templates suite against it (protocol step; not my write scope).
  2. **Confirm the literal-text edge (Z2):** the design forbids a rendered body whose
     first char is `/` being re-parsed as a native command at send
     (`input-contracts.md` / spec FR-06/FR-09). `ChatInputEntryAction.insert-command`
     carries raw `text`; I need a red/green confirmation from Z2 that inserting a
     body beginning with `/` lands as **editable literal draft text**, not a
     second command resolution — otherwise the insert must go through
     `add-content`/`invoke` + `ChatDraftState` instead. This is the one semantic
     cell I could not prove from the checkpoint alone.
- **Caller:** command-templates Chat glue (T10, a follow-on batch, not this round).
- **DTO already provided by this domain:** `render_preview` (zero-send bytes+digest),
  `prepare_insert`/`validate_insert` returning a single-use `ExpansionReceipt` that
  refuses a moved target/draft/context with `STALE_PREVIEW` — it never mutates a
  Chat draft, matching the "不得代 Chat 改草稿" rule.
- **What must NOT happen:** the glue must reuse the one Chat registry and the one
  send owner; no parallel input source, no second ACP client (none added here).
- **Requested owner:** **Z2 (Chat)** for the literal-text confirmation; merge owner
  is the main agent.

## REQ-CT-02 — Private, scoped data-root provider (blocks Server `plugin.py`; gate G01)
- **Caller:** a future `ordessa_command_templates.plugin` (Server method family).
- **Target operation:** an importable, host-provided **private** data root scoped to
  `ordessa.assets.command-templates`, so the domain never writes business tables to
  the Server core DB (`pacthold.storage.Database` currently points every plugin at
  the shared `state/agentbox.sqlite` product schema — wrong for us).
- **DTO needed:** `ServerPluginContext.data_root` today is a single host-wide root
  (`apps/server/.../plugin_host/host.py`), not per-plugin-scoped. A per-plugin
  subroot (or a scoped object store) that a plugin may create files under.
- **Failure counterexample:** initializing the domain must create only its own
  `command-templates.sqlite` and leave `server_assets` / product tables untouched.
- **Current workaround:** the domain takes an **explicit injected path**
  (`TemplateStore.for_root(private_root)`); `test_isolation` proves construction
  opens nothing until `initialize()`. The seam is still missing for production use.
- **Requested owner:** **C0 (foundation)**.

## REQ-CT-03 — Authenticated principal injection into wire handlers (blocks wire family; gates G12/G20)
- **Caller:** `commandTemplates.*` method handlers.
- **Target operation:** every wire handler must receive the authenticated
  principal from the host's auth context, not from client params (FR-11). No
  published mechanism exists in this tree to inject a principal into a
  `ServerMethodDescriptor` handler.
- **DTO needed:** a per-request principal/server-identity the host supplies.
- **Failure counterexample:** a client-forged `projectId`/`principal` must be
  refused with `UNAUTHORIZED_TARGET`.
- **Current workaround:** `CommandTemplateService` takes `principal` as an explicit
  argument and enforces ownership; a cross-owner read is refused (test in
  `test_api_validation`), never silently emptied.
- **Requested owner:** **C0 (foundation)**.

## REQ-CT-04 — Authorized project port for `project-ref` parameters (blocks project-ref render; gates G05/G12)
- **Caller:** `expansion.renderer.render(...)` when a parameter has kind `project-ref`.
- **Target operation:** resolve an opaque project reference to an explicit display
  value + stable id, scoped to the authorized principal (data-model.md "只能经授权
  项目端口解析"). The Workspace domain already exposes a `workspace.service` port
  (`plugins/workspace`), but it is not consumable without the foundation checkpoint,
  and its shape for a template render is not yet frozen.
- **DTO needed:** a `resolve(principal, reference) -> ProjectRef | None` port.
- **Failure counterexamples (already implemented in-domain):** a forged absolute /
  drive / UNC / traversal path is refused with `PARAMETER_INVALID` before the port;
  an unauthorized reference resolves to `None` → `PROJECT_REF_UNRESOLVED`; when no
  port is wired, render refuses with `PROJECT_REF_UNRESOLVED` (never a guessed path)
  — see `test_expansion` `test_project_ref_*`.
- **Requested owner:** **C0 (foundation)** wiring the Workspace service as a
  template-consumable port.

## REQ-CT-05 — Single-send ACP submit path for expanded draft (blocks T11; gates G10/G17)
- **Caller:** Chat submit (existing ACP owner), not this domain.
- **Target operation:** the expanded draft is committed through the **existing**
  Chat send path so a controlled Pi/Codex/Claude peer receives the exact rendered
  bytes with message role **user**. This domain must not open a second ACP client or
  execute anything (harness-adapters.md).
- **DTO needed:** the Chat→ACP submit contract reporting accepted/refused/unknown
  with the frozen draft bytes, from `chat-api`/`harness-api`.
- **Failure counterexample:** the shown preview text and the real ACP payload must
  match by digest; a template body must not be re-parsed as a command at send.
- **Requested owner:** **Z2 (Chat)** + **C0 (harness-api)**.
- **Status:** L4 (real model) not authorized → left **untested**, not claimed.

## REQ-CT-06 — Profile facet `assets.command-templates` seam (blocks T08; gates G12–G14)
- **Caller:** Profile editor contribution; three-state `inherit | enable(revision) |
  disable` over this domain's template ids, referencing only approved revisions.
- **Target operation:** Profile v2 `FacetDescriptor` + edit contribution; the facet
  must not store bodies (only references) and removing the facet hides the editor
  without deleting domain data (G14).
- **Failure counterexample:** an unapproved/absent facet revision must return "cannot
  apply", never push unknown fields; leaving Profile must not stop the content store.
- **Current workaround:** `assignments.resolver` already accepts a `profile` layer and
  a Profile-revision-scoped target, and `set_assignment` refuses to write a profile
  scope directly through this domain (routes it to the Profile facet owner).
- **Requested owner:** **Z1 (profile-api)**.

---

### Items NOT blocked (completed in-domain this round)
T00/T01/T02 (this baseline), T03 (standalone package + DTO/typed errors/schema +
frontend `contracts/`), T04 (immutable revisions, `contentDigest`, approval gating,
archive-preserves-history, CAS `expectedVersion`, idempotent `operationKey` with
same-key/different-payload refusal, publish-does-not-move-pinned), T05 (closed
`{{name}}` parser/renderer, escapes, non-recursion, type/range/length bounds,
byte-stable digest, golden corpus, project-ref port + forged-path refusal), T06
(layered deterministic resolution with explicit enable/disable override and honest
absence reasons, same-slug/different-id conflict detection without silent drop,
`template:<name>` namespace not claiming a bare route, forced org-policy top
priority), T07 (read-only native import preview/commit with lossless-only mapping,
dynamic-include/exec/permission-field refusal, original bytes never written, no
HOME/project scan).
