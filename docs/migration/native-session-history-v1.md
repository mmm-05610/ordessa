# Managed ACP session continuation metadata v1

The Harness plugin appends `acp.session.history.v1` events through the existing
`SessionRecords.append_turn_event` API. No execution ledger, new database, Profile
dependency, or copied configuration home is introduced. Existing table names,
layout, extension IDs and recovery transitions remain unchanged; no SQL schema
migration is required. Older binaries ignore the additional event kind.

An event contains the canonical history ID, Harness ID, project ID, native session
ID, private running-instance directory and a bounded first-message title. It is
written only after a correlated native prompt success. `session/new` alone does
not publish history. Credentials and Profile configuration are not in the event.
An interrupted first prompt without a success response is not claimed as durable
history by this implementation; native files are retained for later recovery.

`acp.sessions.list` exposes only ID/title/project/time. Listing does not launch an
Agent. Opening a history entry resolves the native target and original directory
on the backend, verifies the retained directory's private ownership and canonical
location inside this Server's `harness-instances`, then initializes a fresh process.
The frontend calls native `session/load`; only its correlated success establishes
a fresh native owner. Old execution bindings never survive restart. Loading cannot
invoke a model, create a new native session, or require the original Profile.

Unavailable directories, projects, or native load capability leave the history
entry visible and report failure. No fallback to a fresh instance or prompt replay.

## Pre-v1 conversations

Existing private directories and database rows are preserved unchanged. Previous
versions did not record the directory-to-native-session association. Backfill is
not performed by guessing from project or timestamp; old conversations are not
claimed as recovered merely because new metadata can be read after restart.
`plugins/harness/tools/import-legacy-pi-history.py DATA_ROOT` performs a read-only
inventory. `--apply` requires a stopped Desktop, acquires the existing Server data
root lock, and creates a private SQLite backup before writing metadata events.
This one-shot tool cross-checks legacy Profile registration IDs against existing
connection idempotency receipts and native Pi file headers. It imports only unique
native ID + original project-path matches with user and assistant messages.
Duplicate/missing files and uncertain associations are excluded, never guessed.
Reading the legacy optional plugin's storage is a migration-only operation; the
production history and resume pipeline does not import or require Profile.
Codex/Claude pre-v1 backfill is not implemented by this Pi-specific migration tool.
