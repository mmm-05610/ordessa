# Harness records

The original OperationJournal and UnitRecords implementation, distributed as
one explicit deployment-owned library. It is not a plugin, registry, daemon or
new database. Importing the package does not open storage. A deployment must
provision its original journal path and inject trusted scope, native evidence,
invocation verifier and management epoch ports. Missing authority refuses.

The two implementations move byte-for-byte from the monolith at b2e4a1ab36.
Existing SQL tables, JSON codecs, unknown fences and ticket semantics stay in
the same original SQLite journal. Deployment factories and native evidence
ports still need production integration; installation is not native readiness.
