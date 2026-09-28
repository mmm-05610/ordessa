# Data-root layout note — Core's own store file

Added 2026-09-27 by the specs/010 B lane at commit `1210a6edbf` (T014-S1c).
Per AGENTS rule 5, on-disk layout changes are recorded here. **No identifier was
renamed and no existing file or table was altered**; this note describes an
additive change, so no user-data conversion is implied and none was performed.

## What a Server data root contains now

| Path under the data root | Owner | Contents |
| --- | --- | --- |
| `state/agentbox.sqlite` | legacy chain + product tables (`pacthold_runtime_compat`, sealed `schema_versions` namespace `agent_box_legacy`, product schema marker `agentbox_product_schema` at `PRODUCT_SCHEMA_VERSION = 21`) | unchanged from before the convergence |
| `state/core.sqlite` | the C1 instance store (`pacthold.public.CoreStore`) | **new file**, created lazily on first Core use |

The pre-convergence single-file arrangement had the host reaching Core
internals through a global connection
(`bootstrap/runtime.py` `from pacthold.work_core import db`), which is what
T014-S1c removed. `CoreStore` is constructed as `CoreStore(path)` and owns its
own `sqlite3.connect(path, timeout=10.0, check_same_thread=False)` with no
connection-injection seam, so sharing one file between the legacy chain and Core
would mean two OS-level connections to the same database protected only by
sqlite's busy timeout on the default journal — the host's in-process
`write_lock` would no longer serialise Core's writes.

## Why a second file rather than a shared one

The rejected topology is **demonstrated**, not merely declined, by
`apps/server/tests/platform/test_platform_core_instance.py::test_shared_file_topology_counterexample_double_applies_a_write`,
which forces a legacy read-check-write under `db.write_lock` to interleave with a
second `CoreStore` connection on the same file and observes two rows for one
logical application. The chosen topology is pinned by
`test_composition_core_file_is_its_own_and_never_the_legacy_file`, which also
shows the legacy tables are not reachable from the Core file.

## Consequences for readers and backups

- A data root is now two databases plus the existing run-data files. Anything
  that copies, checks or restores a data root must include `state/core.sqlite`
  to be complete; a copy that only takes `agentbox.sqlite` no longer captures
  the whole Server.
- `AGENT_BOX_HOME` / the legacy home path is unchanged, and
  `test_stage_a_server.py::test_core_uses_the_server_owned_database_file`
  continues to assert that the legacy binding is the Server-owned file rather
  than a foreign home.
- Old data roots keep working without migration: the Core file is created on
  demand by the composition that needs it.
