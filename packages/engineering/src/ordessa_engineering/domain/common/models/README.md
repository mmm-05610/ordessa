# Common models

Pure shared values and local constraints: foundational values, Scope/ActorRef,
generic BlobRef and ContentSelector. BlobRef owns its content identity projection,
including exclusion of the storage locator. No I/O or caller authentication.

Business IDs/references, review targets and record identity, artifact provenance,
reviewer evidence and application version expectations have moved to their actual
owners. Constructors use the minimal diagnostics refusal. No root/group
initializer re-exports owners. See [common](../README.md) for the ownership map,
candidate status, preserved contracts and verification limits.
