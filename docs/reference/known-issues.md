# Known issues for the bounded development checkpoint

This file registers the Foundation-owned issue added to this independent
development branch. The existing nightly known-issues document and its prior
entries remain unchanged in the implementation worktree. They are not imported
by this bounded file selection.


## Engineering79: cross-connection effect-cut test remains unqualified (2026-10-13)

Owner: Engineering; reproduction node:
`test_dispatch_effect_cut.py::test_different_connection_revoke_commits_after_admitted_bytes_before_model_wait`.

The owner source full run reached its 300-second bound; the single-node run also
reached its 20-second bound. Both failed/timeout receipts are preserved. A
private stdlib diagnostic reported EPERM (errno1), callback-ready1, and callback
execution after pipe rescue. That observation does not qualify the production
loop or the admitted-bytes/revocation cut; no production loop was modified to
force a pass. Engineering79's overlapping affected, cut and candidate checks
and its installed byte/origin checks must not be reported as full-system or
model validation.

Current owner record:
`docs/implementation/packages-convergence-20261012/engineering/post78-integration/QUALIFICATION79.json`
and `FINAL79-HANDOFF.md`; frozen manifest SHA-256
`05171e6bae9023f7eacd3ea7bc8f994b52bdf89458379c71ecd3286e0a470a36`.
Next: reproduce the exact node in an approved isolated check environment and
separate test-environment restrictions from production behavior before closing
this issue. No model replay, credential, service or security-setting change is
authorized by this record.
