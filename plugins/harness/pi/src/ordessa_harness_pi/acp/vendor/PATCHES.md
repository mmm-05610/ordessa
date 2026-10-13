# Pi ACP history vendor — source and patch record

The source authority is `SOURCE.json`: harness-remote v3.0.2 at commit
`21ce6db49af708c4c7c3f96ef6a50f62dced8dab`, under Apache-2.0. Its recorded
license is retained in `LICENSE`.

`pi-session-history.js` and `backward-line-scan.js` are the exact already
reviewed upstream files recorded by their SHA-256 values in `SOURCE.json`.
The second file is included in this Pi vendor directory so the independent Pi
wheel carries the history loader's complete Node dependency closure. Its
source matches the existing shared upstream copy in the Agents vendor. This
is a distribution-local copy of the same upstream module, not a second
implementation or a behavioral fork.

The previous patch that imported the scanner from the Agents checkout source
has been removed; `pi-session-history.js` again has its upstream relative
import. No upstream source was downloaded or independently reverified for
this change. The file contents were compared with the already retained source
and the recorded hashes only.
