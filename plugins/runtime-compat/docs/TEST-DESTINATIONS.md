# T009 test destination table

Evidence: `/tmp/ordessa-core-A-t010-junit.xml` = 328 IDs at 14cdb563e5 (migration baseline);
`/tmp/ordessa-core-A-t009-core.xml` = 203 IDs (G1, exit 0); `/tmp/ordessa-core-A-t009-compat.xml` = 163 IDs (G2, exit 0).
Matching: (test-file stem, test id incl. class/param suffix); module path changes are allowed exactly for the
relocated prefixes (capability / test_resource_contracts / test_runtime_composition_protocol / brand-rename half).

| old file (packages/pacthold/tests/…) | new destination | old→carried IDs |
| --- | --- | --- |
| test_brand_rename | split: kernel half `packages/pacthold/tests`, assembly half `plugins/runtime-compat/tests` | 5 → 5 |
| test_capability_authorization | `plugins/runtime-compat/tests` — moved | 8 → 8 |
| test_capability_documents | `plugins/runtime-compat/tests` — moved | 24 → 24 |
| test_capability_errors | `plugins/runtime-compat/tests` — moved | 21 → 21 |
| test_capability_fake_refusals | `plugins/runtime-compat/tests` — moved | 20 → 20 |
| test_capability_ids | `plugins/runtime-compat/tests` — moved | 30 → 30 |
| test_capability_match | `plugins/runtime-compat/tests` — moved | 10 → 10 |
| test_capability_requirements | `plugins/runtime-compat/tests` — moved | 9 → 9 |
| test_capability_selection | `plugins/runtime-compat/tests` — moved | 16 → 16 |
| test_extensions | `packages/pacthold/tests` — unchanged | 14 → 14 |
| test_plugins_cli | `packages/pacthold/tests` — unchanged | 3 → 3 |
| test_presence_verdict_lnx002 | `packages/pacthold/tests` — unchanged | 8 → 8 |
| test_public_contract | `packages/pacthold/tests` — unchanged | 34 → 34 |
| test_resource_contracts | `plugins/runtime-compat/tests` — moved | 7 → 7 |
| test_runtime_composition_protocol | `plugins/runtime-compat/tests` — moved | 4 → 4 |
| test_us1_instance_isolation | `packages/pacthold/tests` — unchanged | 6 → 6 |
| test_us1_lifecycle_negatives | `packages/pacthold/tests` — unchanged | 14 → 14 |
| test_us1_operations_idempotency | `packages/pacthold/tests` — unchanged | 6 → 6 |
| test_us1_recovery_negatives | `packages/pacthold/tests` — unchanged | 18 → 18 |
| test_us1_resource_lifecycle | `packages/pacthold/tests` — unchanged | 12 → 12 |
| test_work_core_contracts | `packages/pacthold/tests` — unchanged | 5 → 5 |
| test_work_core_finalization | `packages/pacthold/tests` — unchanged | 7 → 7 |
| test_work_core_input_dispatch | `packages/pacthold/tests` — unchanged | 17 → 17 |
| test_work_core_repository | `packages/pacthold/tests` — unchanged | 8 → 8 |
| test_work_core_resource_observations | `packages/pacthold/tests` — unchanged | 18 → 18 |
| test_work_core_responsibility | `packages/pacthold/tests` — unchanged | 4 → 4 |

Old test-tree files that did NOT carry over (dead code, 0 IDs):

| file | disposition |
| --- | --- |
| `tests/_editor_mock.py` | deleted at T009: imported non-existent `pacthold.edit`, zero references repo-wide (registered as dead code in reports/A.md T001 mapping) |

New guard files added at T009 close-out (38 IDs; every mechanism pinned with positive AND negative cases; not part of the 328):

| new file | location | IDs |
| --- | --- | --- |
| test_legacy_migration_chain | plugins/runtime-compat/tests | +6 |
| test_product_assembly | plugins/runtime-compat/tests | +7 |
| test_t009_bare_core_imports | packages/pacthold/tests/platform | +3 |
| test_t009_direction_guard | packages/pacthold/tests/platform | +6 |
| test_t009_migration_namespaces | packages/pacthold/tests/platform | +11 |
| test_t009_sql_seal | packages/pacthold/tests/platform | +5 |

TOTAL: 328 old IDs → 328 carried, missing=0; `<skipped>` tags in both new junit files: 0.
