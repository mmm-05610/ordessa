# Harness records

`OperationJournal` and `UnitRecords` are the single implementation of these
shared persistence mechanisms. They are part of the `ordessa-units`
distribution at `ordessa_units.records`; the former
`ordessa-harness-records` distribution and `ordessa_harness_records` import
root are retired, with no compatibility alias.

The source move came from `plugins/harness/records/src/ordessa_harness_records`
at source revision `09ea93732be426a85dfca0b3220ae53230a54a11`; the records
implementation moved byte-for-byte. The [cutover map](../../../../../../../docs/implementation/nightly/evidence/W06/records-cutover-map.json)
records original file hashes, the 39 switched consumer files and the
49-project workspace inventory. Existing table identities, JSON codecs,
unknown fences and ticket semantics were preserved. The original README is
retained byte-for-byte at
`docs/archive/pre-restructure/source/plugins/harness/records/README.md`; its
SHA-256 is `0c370a63da8716f12c789f4cd54be0a6be4cbc7f65b2090628af7e60c48d41bd`.

Importing this package does not open or provision storage and grants no
authority. The composing owner supplies the original journal path and trusted
scope, native-evidence, invocation-verifier and management-epoch ports.
Server's `state/agent-owner/operations.sqlite` and Agent Tools'
`plugins/profile/native-configuration.sqlite` are distinct composition paths;
this package does not select or merge them.

This cutover moves the records implementation only. Shared Harness contracts
and materialization remain to be migrated; the Managed Codex codec/service
split remains pending. Real native operation and cold recovery have not been
verified, so this documentation does not claim W06 completion.
