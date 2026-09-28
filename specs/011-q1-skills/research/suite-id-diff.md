# Q1 / T16-G22 — affected-suite per-ID / per-cause diff

Date: 2026-09-28. Tree: `codex/011-q1-skills` @ `592f01b328` (clean checkpoint).
Interpretation: `.venv/bin/python` = Python 3.12.14, all local packages installed editable.
Goal (G22): prove, **per failing test ID and per cause**, that this tree's suite
failures are the same IDs with the same causes as the published foundation
baseline (`specs/011-plugin-rollout/checkpoints/foundation.json`, publication
`8844c475bc`, impl `8229e20824` — both verified ancestors of HEAD) — with no new
reds and nothing silently "fixed".

## 0. Baseline of record — machine-readable, digest-verified

C0's `report.md` itself carries only prose/counts, **but** the JUnit XML files it
pins by SHA-256 survived in `/tmp` on this machine and were re-hashed this turn;
they match the published digests, so no throwaway-worktree re-run of the
foundation commit was needed:

| Baseline artifact | sha256 (re-measured) | Matches published record | Red IDs inside |
| --- | --- | --- | --- |
| `/tmp/ordessa-c0-server-wired-junit.xml` | `92ef39145b25…e079b9` | yes — foundation.json `commandsAndEvidence` + report.md:90 | 67 (42 fail + 25 err; 1092 passed, 10 skipped, tests=1169) |
| `/tmp/ordessa-B-t002-server-B-junit.xml` | `1102c0bda233…6d0bb` | yes — B.md:19 pin | 68 (43 fail + 25 err; tests=928) |
| `/tmp/ordessa-c0-harness-journal-junit.xml` | `7c4ec1414688…f82a5` | yes — report.md:98 | 2 (tests=371) |
| `/home/maoqh/ordessa-builds/q1-skills-evidence/skills-pytest-6df28d00.xml` | `c920d7f0fc71…9bce` | Q1 lane's own junit — see §4 caveat | 0 (315 tests; predates the profile-pin file) |
| `/tmp/q1-evidence/tree-err-ids.txt`, `iso-err-ids2.txt`, `08-in-tree-baseline.log` | — | Q1 lane per-ID pins | exactly 6 error IDs; `329 passed, 6 errors` |

## 1. Method

- Current measurements (this turn, nothing copied): each suite run with
  `-q -p no:cacheprovider --tb=line -rfE --junitxml=/tmp/q1-evidence-id/<suite>.xml`,
  true `$?` of the pytest process captured via `echo EXIT=$?` (never a `tail`
  pipeline's status).
- IDs and causes come from the JUnit XML (`classname/file` + `name`, first line
  of the `failure`/`error` message), not from prose.
- Normalization follows the discipline `tooling/id-diff.mjs` uses for JS suites
  (name-by-name kept/moved/missing diff) plus the "path / volatile-ID"
  normalization C0 describes for pytest: tree/worktree prefixes → `<TREE>`,
  `/tmp/...` → `<TMP>`, `0x…` pointers, sha256/hex digests, exec/session IDs,
  `file.py:NNN` line numbers and long digit runs masked. Parametrization
  suffixes are kept verbatim (they carry no volatile data in these suites).
  Script: `/tmp/q1-id-diff/extract.py`; extracted ledgers
  `/tmp/q1-id-diff/{baseline-wired,current-server}.json`.

This turn's JUnit digests (new evidence, recorded so a later rerun is a new diff,
not an edit of this one): `server.xml` `03fe6b44e83e…b760b`, `harness.xml`
`30ee4534bf24…48655`, `pacthold.xml` `cd16997ebfbc…968a`, `skills.xml`
`c075d2ac92ee…49d2a`.

## 2. Per-suite counts and true exit codes (this tree, measured now)

| Suite (command as specified) | collected | passed | failed | errors | skipped | TRUE exit |
| --- | --- | --- | --- | --- | --- | --- |
| `apps/server` | 1193 | 1116 | 42 | 25 | 10 | **1** (`EXIT=1`, 127.31 s) |
| `plugins/harness` | 438 (+37 subtests) | 433 | 2 | 0 | 3 | **1** (`HARNESS_EXIT=1`) |
| `packages/pacthold` | 212 | 212 | 0 | 0 | 0 | **0** (`PACTHOLD_EXIT=0`) |
| `plugins/assets/skills/tests` | 379 | 373 | 0 | 6 | 0 | **1** (`SKILLS_EXIT=1`) |

Red-ID census: server 42+25 = **67**; harness **2**; pacthold **0**; skills **6**.

## 3. apps/server — per-ID diff vs the foundation ledger

Counts vs checkpoint self-report (`42F/1092P/10S/25E`): failed/skipped/errors
match exactly (42/10/25); passed is 1116 not 1092 because this tree already
contains C0's post-checkpoint server-relay and Q5-merge rows, which C0 itself
re-recorded as `42 failed / 1116 passed / 10 skipped / 25 errors, same 67
inherited red IDs, new [], gone []` (report.md rows for `b252a1a5f4` and the Q5
merge). Collection grew 1169 → 1193 (+24 passing IDs, zero reds). The red set is
compared against the pinned baseline-of-record junit, and it matches per ID:

- **new `[]` — gone `[]`** — 67/67 identical IDs (set difference, both
  directions, on normalized `file::name`); skipped sets also identical
  (10 = 10, new [] gone []).
- **failure kinds** identical for all 67 (failure vs error, per ID).
- **causes** identical for 67/67 at exception-class level and 66/67 at
  normalized-first-line level. The single textual difference is
  `test_cancel_recall_flake_087.py::test_cancel_recall_flake_087_one_round_keeps_its_durable_facts`:
  both read `AssertionError: {… 'exitCode': 2 … native-home-gate.py': [Errno 2]
  No such file or directory`, differing only in where pytest elides the
  `<TREE>…/scripts/server-round1/native-home-gate.py` path in the stderrTail —
  exactly the "pytest shortening of the same missing native-home-gate.py path"
  C0 registered for the same ID in report.md:90. Same cause, not a new one.
- Cause-family attribution matches the registered ledger (B.md §"apps/server red
  ledger — per ID (68)" families F1–F5 + `docs/known-issues.md` scope rulings):
  F1 retired `worker-entry.mjs` FileNotFoundError (accounts 2, asset_hubs 3,
  delegation 2, deployment_credentials 11, first_run_lock 3,
  harness_capability_integration 1, harness_capability_projection 2(E),
  import_asset_request_id_129 10(E) — the ledger's "all 10 IDs of that file"
  family row, placement ssh-refusal 1, server_capability_contract 1F+1E,
  sidecar_native_driver 1F+10E, subagent_harness_round_086 2E);
  F2 `agent_box_sandbox_bwrap` ModuleNotFoundError (placement 4 +
  sidecar_native_driver bundle 1); F3 `SIDECAR_CLOSED` (capability_truth_table
  2, sidecar_upstream_cause_150 code-assert 2 + ModuleNotFoundError
  `test_harness_sidecar` 1); F4 fake-peer/native-chain AssertionError with
  `<EXECID>` payload (native_bootstrap_identity_hd002 1, native_cli_hd002 2,
  cancel_recall_flake_087 1); F5 registered guards (e_inc0_block1_pins 1,
  wire_v1 unavailable-capabilities 1 — `assert False is True`, scope-missing
  item 7).

Full current red-ID list (kind F=failure E=error; cause class per §3 bullet above):

```
F tests/test_accounts.py::test_a_bound_account_materialises_reclaims_and_conflicts_typed
F tests/test_accounts.py::test_the_accounts_wire_face_creates_imports_binds_lists
F tests/test_asset_hubs.py::test_a_bound_mcp_asset_is_rendered_and_materialised_without_writeback
F tests/test_asset_hubs.py::test_assets_publish_plugin_over_the_wire_returns_a_preview
F tests/test_asset_hubs.py::test_the_assets_wire_face_publishes_binds_and_lists
F tests/test_cancel_recall_flake_087.py::test_cancel_recall_flake_087_one_round_keeps_its_durable_facts
F tests/test_capability_truth_table.py::test_the_effective_view_is_read_through_the_port_only_after_operations
F tests/test_capability_truth_table.py::test_the_effective_view_never_pre_fills_observations
F tests/test_delegation.py::test_a_granted_parent_renders_the_bridge_entry_and_zero_grants_does_not
F tests/test_delegation.py::test_the_real_bridge_process_runs_a_child_turn_end_to_end
F tests/test_deployment_credentials.py::test_a_declared_credential_is_imported_and_resolves_by_its_declared_id
F tests/test_deployment_credentials.py::test_a_declared_credential_without_a_store_is_refused
F tests/test_deployment_credentials.py::test_a_deployment_without_credentials_still_starts
F tests/test_deployment_credentials.py::test_a_malformed_declaration_is_a_typed_refusal[entry0-credentialId must be]
F tests/test_deployment_credentials.py::test_a_malformed_declaration_is_a_typed_refusal[entry1-kind is required]
F tests/test_deployment_credentials.py::test_a_malformed_declaration_is_a_typed_refusal[entry2-must be absolute]
F tests/test_deployment_credentials.py::test_a_malformed_declaration_is_a_typed_refusal[entry3-at most 64 characters]
F tests/test_deployment_credentials.py::test_a_restart_with_the_same_deployment_does_not_duplicate_or_reread
F tests/test_deployment_credentials.py::test_an_unreadable_source_fails_the_start_rather_than_the_harness
F tests/test_deployment_credentials.py::test_duplicate_ids_and_an_oversized_section_are_refused
F tests/test_deployment_credentials.py::test_the_document_may_not_carry_the_secret_itself
F tests/test_e_inc0_block1_pins.py::test_sidecar_backend_contains_no_business_ledger_read
F tests/test_first_run_lock.py::test_the_guard_keeps_one_first_run_inside_the_window_at_a_time
F tests/test_first_run_lock.py::test_two_profiles_first_runs_do_not_overlap_through_the_server
F tests/test_first_run_lock.py::test_without_the_gate_the_same_first_runs_overlap
F tests/test_harness_capability_integration.py::test_a_deployment_may_only_declare_canonical_boolean_abilities
E tests/test_harness_capability_projection.py::test_an_acp_harness_and_a_native_driver_project_the_same_capabilities
E tests/test_harness_capability_projection.py::test_an_undeclared_native_ability_cannot_raise_the_product_capability
E tests/test_import_asset_request_id_129.py::test_a_different_key_for_the_same_bytes_is_a_new_request_not_a_replay
E tests/test_import_asset_request_id_129.py::test_a_replayed_import_leaves_exactly_one_idempotency_row_and_one_asset
E tests/test_import_asset_request_id_129.py::test_a_request_without_the_key_is_refused_by_the_shape_before_any_write
E tests/test_import_asset_request_id_129.py::test_a_retry_of_accounts_create_still_makes_exactly_one_account
E tests/test_import_asset_request_id_129.py::test_a_retry_of_one_import_replays_and_writes_the_asset_once
E tests/test_import_asset_request_id_129.py::test_counter_example_the_pre_129_handler_writes_twice_and_moves_the_locator
E tests/test_import_asset_request_id_129.py::test_one_key_cannot_import_into_two_different_accounts
E tests/test_import_asset_request_id_129.py::test_the_conflict_family_matches_the_sibling_that_uses_the_same_layer
E tests/test_import_asset_request_id_129.py::test_the_report_carries_the_three_method_comparison
E tests/test_import_asset_request_id_129.py::test_the_same_key_with_a_changed_file_is_a_conflict_request
F tests/test_native_bootstrap_identity_hd002.py::test_native_first_send_completes_with_reviewed_fake_acp_peer
F tests/test_native_cli_hd002.py::test_native_cli_project_cwd_first_send_and_followup[False]
F tests/test_native_cli_hd002.py::test_native_cli_project_cwd_first_send_and_followup[True]
F tests/test_placement.py::test_a_local_workspace_runs_through_the_local_channel
F tests/test_placement.py::test_a_wsl_turn_still_routes_to_the_worker_from_a_windows_host
F tests/test_placement.py::test_the_placement_picks_the_channel_through_the_product_path
F tests/test_placement.py::test_the_ssh_placement_is_refused_without_its_connector
F tests/test_placement.py::test_the_ssh_placement_runs_on_its_own_connector
F tests/test_server_capability_contract.py::test_deployment_seat_accepts_the_canonical_spelling
E tests/test_server_capability_contract.py::test_real_acp_and_driver_routes_share_one_canonical_view
E tests/test_sidecar_native_driver.py::test_a_driver_exit_is_reported_as_a_failed_fact
E tests/test_sidecar_native_driver.py::test_a_driver_module_outside_the_bundle_deployment_area_is_refused
E tests/test_sidecar_native_driver.py::test_a_driver_module_that_is_not_a_bundled_absolute_module_is_refused[../../../../etc/passwd]
E tests/test_sidecar_native_driver.py::test_a_driver_module_that_is_not_a_bundled_absolute_module_is_refused[/runtime/view/agentbox-sidecar/deployment/fixture-native/driver.js]
E tests/test_sidecar_native_driver.py::test_a_driver_module_that_is_not_a_bundled_absolute_module_is_refused[agentbox-sidecar/deployment/fixture-native/driver.mjs]
E tests/test_sidecar_native_driver.py::test_a_driver_module_without_a_driver_entrypoint_is_refused
E tests/test_sidecar_native_driver.py::test_a_driver_without_every_contract_method_is_refused
E tests/test_sidecar_native_driver.py::test_port_turns_neutral_driver_deltas_into_product_facts
E tests/test_sidecar_native_driver.py::test_registering_without_a_driver_still_uses_the_acp_registration
E tests/test_sidecar_native_driver.py::test_sidecar_routes_generic_operations_to_a_declared_native_driver
F tests/test_sidecar_native_driver.py::test_deployment_carries_a_declared_driver_module_into_the_reviewed_bundle
F tests/test_sidecar_native_driver.py::test_the_bundle_carries_the_driver_seam_module
F tests/test_sidecar_upstream_cause_150.py::test_a_launch_fault_and_a_session_fault_get_different_codes
F tests/test_sidecar_upstream_cause_150.py::test_a_long_and_path_bearing_cause_stays_bounded_and_out_of_the_code
F tests/test_sidecar_upstream_cause_150.py::test_an_accepted_turn_whose_adapter_cannot_start_reports_that_cause_to_the_client
F tests/test_sidecar_upstream_cause_150.py::test_the_cause_reaches_the_turn_record_and_its_event
E tests/test_subagent_harness_round_086.py::test_a_granted_claude_parent_on_the_production_deployment_carries_the_bridge
E tests/test_subagent_harness_round_086.py::test_a_profile_with_no_outgoing_grant_carries_no_bridge_entry
F tests/test_wire_v1.py::test_unavailable_capabilities_carry_a_reason
```

**Nothing was silently fixed on the 68→67 path either.** Diff of the current 67
against the frozen T002 68-ID set: `new []`, `gone [exactly one]` —
`test_wire_error_family_101.py::test_no_wire_error_is_constructed_with_a_non_family_first_argument`,
the one retirement B.md:546/572 registers **by name and cause** (S3 moved the
`SERVER_NATIVE_IDENTITY_INVALID` construction out of the host; the guard's named
defect ceased to exist; "the lane's current red baseline is now 67"). That
happened in lane B upstream of the foundation checkpoint, not in Q1.

## 4. Q1-owned suite — plugins/assets/skills (the 6 profile pins)

Current run: `373 passed, 6 errors`, exit 1 — reproduces the Q1 report §evidence
row verbatim, and the 6 IDs are **exactly** the registered pins
(`/tmp/q1-evidence/tree-err-ids.txt` and `iso-err-ids2.txt`, byte-identical
lists; pass-count lineage 329 → 373 = the +44 harness-api tests added by
`4c7d749a69`):

```
E plugins/assets/skills/tests/test_profile_facet_contribution.py::test_registration_uses_the_published_facet_api_only
E plugins/assets/skills/tests/test_profile_facet_contribution.py::test_provider_compile_declares_zero_config_intents
E plugins/assets/skills/tests/test_profile_facet_contribution.py::test_real_resolve_round_trip
E plugins/assets/skills/tests/test_profile_facet_contribution.py::test_profile_layer_is_read_only_no_writes_behind_the_back
E plugins/assets/skills/tests/test_profile_facet_contribution.py::test_absent_profile_refuses_with_a_type
E plugins/assets/skills/tests/test_profile_facet_contribution.py::test_harness_port_absence_keeps_their_typed_block
```

- Cause unchanged and upstream, verified at symbol level this turn: all six are
  fixture-setup errors (`failed on setup with "Failed: profile-api is not
  importable in this tree — upstream gap: … AgentBoxProfileV1 …"`).
  `plugins/profile/src/ordessa_profile/plugin.py:17` (and
  `plugins/profile/tests/test_plugin_registration_v2.py:8`) still do
  `from pacthold.resource_contracts import AgentBoxProfileV1`, while
  `.venv/bin/python -c "import pacthold.resource_contracts as m; print('AgentBoxProfileV1' in dir(m))"`
  prints `False` — the foundation emptied the module; the symbol now lives at
  `pacthold_runtime_compat.resource_contracts.agent_box_profile_v1`. Q1 may not
  edit `plugins/profile` → registered as §R-Q1-1 in `api-requests.md`; the pins
  stay red for Z1's `profile-api -r2`.
- **No Q1 assertion deleted or skipped**: grep over all
  `plugins/assets/skills/tests/*.py` finds zero `pytest.skip`,
  `pytest.mark.skip`, `xfail` occurrences; the only `_skip` token is
  `test_harness_intent_boundaries.py::_skip()`, which is a misnomed
  raise-asserting placeholder (it constructs `MountContent` inside
  `pytest.raises(ContractError)` — it never skips anything). The pins fail
  loudly via `pytest.fail` in the fixture, they are not softened to skips.
- Honest caveat: the durable junit labelled `skills-pytest-6df28d00.xml`
  (315 tests, 0 red) **predates** `test_profile_facet_contribution.py` — its
  label does not carry the 6-pin state; the per-ID pins for those come from the
  Q1 lane's `/tmp/q1-evidence/tree-err-ids.txt` / `iso-err-ids2.txt` ledgers and
  this turn's `skills.xml`. No ID was invented for the baseline.

## 5. plugins/harness and packages/pacthold

- harness: current red = the same **2** IDs as every published C0 harness run
  (`tests/install/test_acp_schema_drift_target.py::test_the_acp_schema_a_closure_carries_satisfies_the_adapter_that_needs_it`,
  `::test_a_root_override_of_the_schema_does_not_violate_a_declaration_in_the_closure`);
  `new []`, `gone []`; the full multi-line AssertionError payloads are
  byte-identical after path/pointer normalization — both still naming
  "`@automatalabs/pi-acp` declares `@agentclientprotocol/sdk@1.4.0` but the lock
  resolves 1.3.0" / "overrides forces …1.3.0", the Pi ACP SDK lock drift
  registered in `docs/known-issues.md` §Backend row 2 and foundation.json
  limitations. Skips identical (3 = 3). Pass-count drift 366→433 is C0/Q1
  harness growth; zero red IDs added.
- pacthold: `212 passed`, exit 0 — reproduces the checkpoint row exactly
  (212/0/exit 0); JUnit census confirms 0 failures, 0 errors, 0 skips, 212
  tests. No red set to diff.
- (`tests/acp_orchestration`'s 18 inherited reds are registered in
  `docs/known-issues.md`/foundation.json but are outside the four suites this
  G22 slice was scoped to; not re-run this turn.)

## §Verdict

**The tree reproduces the published foundation ledger per ID.** apps/server:
67/67 red IDs identical, same kinds, same registered causes (1 prose-level
normalization residue = the pre-registered `test_cancel_recall_flake_087` path
shortening), new `[]`, gone `[]`; 68→67 lineage is the one named, registered S3
retirement upstream of the checkpoint, not a Q1 edit. plugins/harness: 2/2
identical IDs, byte-identical lock-drift causes. packages/pacthold: 212 green,
exit 0. plugins/assets/skills: exactly the 6 registered profile-pin errors,
same upstream `AgentBoxProfileV1`-moved-out-of-`pacthold.resource_contracts`
cause, zero skips/xfails added or present.

**Therefore Q1 (Skills v2) introduced no new red IDs in these suites and
retired none quietly.** The only contradictions to be honest about are counting
artifacts, not red-set ones: passed/collected totals exceed the checkpoint's
1092/366 because post-checkpoint C0 and Q1 merges added passing tests (+24
server, +67 harness, +44 skills), and Q1's own `skills-pytest-6df28d00.xml`
label predates the 6-pin run it is cited next to. Neither changes any failing
ID or cause.
