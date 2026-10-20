# Existing account-only Desktop root initialization

2026-10-02: a prior independent Codex login created `~/.ordessa/accounts/codex`
before Desktop startup. It did not initialize the shared Server ownership marker.
Desktop's existing-directory reuse correctly does not claim unmarked directories;
Server consequently refused this root with `DATA_ROOT_UNOWNED`.

Fresh Desktop roots already receive the existing `.agentbox-server-root` marker
with unchanged content `agentbox-server-r1\n`. No path, identifier, database
schema, credential storage, or account scope changes in this correction.

For a **known Ordessa directory only**, after the user explicitly authorizes its
initialization and quits Desktop, the development maintenance command is:

```sh
node products/desktop/initialize-existing-data-root.mjs --confirm-existing-ordessa-root /home/maoqh/.ordessa
```

This writes only the missing ownership marker (exclusive create, 0600). It does
not copy credentials, change existing permissions, remove data, migrate databases,
or remove locks. It rejects live Desktop locks, any Server lock needing separate
review, symlinked roots/ancestors/marker/locks, other-user or shared-writable roots,
and incorrect existing markers. Ordinary startup never calls this operation.
An existing valid marker is preserved. Never use this to bypass ownership checks
on a foreign or historical database directory.

The user authorized initialization of `/home/maoqh/.ordessa` with “do it”. Its
pre-initialization top level contained accounts, logs, backups, secrets, state,
and `.keep`; no Server database or Server lock was present. Existing contents
remain in place; no new temporary product data root is used.
