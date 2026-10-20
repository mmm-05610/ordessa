# ordessa-harness-hermes

Independent brand package (032): the hermes native-channel facts and deploy
knowledge moved out of the retired root `pacthold.harness_kit` super-package. No
aggregate registration; the product selects brands explicitly.


## SDK cutover status (2026-10-19)

`HermesHarnessProvider` is the actual leaf entrypoint under
`ordessa.harness_providers`. It imports only the public Agent SDK, validates the
fixed Profile harness pin and produces an immutable native `acp` launch plan from
an externally approved command/environment. The original artifact declarations
prove the brand uses ACP; the provider delegates fresh session establishment only
to the original owner `ManagedProcess.open_acp_session`. It never spawns, resolves
a binary, acquires resources, answers permissions or owns a separate ledger.

Profile configuration declarations, credential materialization and resume are
explicitly unavailable. Native configuration remains externally prepared: Hermes
requires the exact home/config.yaml prepared reference, while Kilo requires the
approved nonsecret KILO_CONFIG_CONTENT with autoupdate=false and credentials as
environment references. The prepared data itself grants no access.

Legacy declaration/installation/command ports importing retired internal contracts
are removed. Hermes imperative launch/projection/composition and historical online
Profile wrapper are removed. Pure native dialect tables, packaged deployment and
build facts/resources remain; they are not an alternate runtime. Existing template,
locator and packaging test assertions are preserved. Old locator/catalog consumers
need explicit coordinated migration and are not passing SDK acceptance evidence.
No tests/builds/models were run by this leaf worker. The new targeted tests cover
SDK preparation/closure boundaries and Profile precommit validation only; actual
brand ACP L1, native CLI L2 and model behavior remain unverified.
