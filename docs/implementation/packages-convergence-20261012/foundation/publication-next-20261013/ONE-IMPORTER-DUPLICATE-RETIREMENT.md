# One dormant importer duplicate retired

The exact old path is
`plugins/harness/src/ordessa_harness/importers/models.py`.
Its receiving path is
`packages/execution/agents/src/ordessa_execution_agents/harness/configuration/importers/models.py`.
Both are775 bytes with SHA-256
`0f494ff3b52e7af6863df7621a185aae97756c9cdc090e2559c020eb2ae80bdb`.
The receiving file is already in the published Execution capture and its bytes
match the pinned installed payload. The new Agents dependency-repaired wheel
retains the same120 runtime payloads.

The old file contains only frozen `ImportCandidate` / `ImportPreview` data
classes and `ImportPreview.public()` implemented with the unchanged `asdict`.
The importer is explicitly unwired and unregistered. The bounded production
source audit found no retired aggregate-root imports or consumer of these DTOs.
No original DTO test was found, and no test is deleted. Subagents' similarly
named DTO/tests cover a different implementation and are not credited here.
Removing the byte-identical dormant duplicate does not require a new test that
mirrors the retained implementation.

The Execution owner's frozen deletion request already lists this exact old
path and SHA. Foundation additionally verified the actual publication
predecessor's old and receiving blobs, installed receiving bytes, declarations
and consumer/test disposition. This is a one-file source deletion, not a claim
that the old aggregate, SDK, package root or formal runtime is fully retired.

The other552 proposed Harness old-path deletions remain unapplied. The75 old
Pacthold,61 runtime-compat and67 server-compat paths remain separate receiving
work. Whole-package entry/root retirement must handle the old registry and
native-evidence assertions, packaging and actual release-test consumers; an
empty-root deletion alone would not establish that submodules are unreachable.
No owner source is rewritten, no data is removed, and no model, installation,
test, service or permission operation is performed by this retirement.
