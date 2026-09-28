# ordessa-harness-api

Independent, standard-library-only public contract for Harness v2 C1–C4.
The carrier injects contribution ownership; these DTOs do not authenticate
owners, apply intents, mint submission permits, or perform native I/O.

Install this wheel on its own. `RuntimeAdapter` and `ConfigurationAdapter`
are structural protocols; registration, effect validation, and operation
journaling belong to the Harness implementation. A `None` version means
unknown, never supported. `ValueSchema` is a closed JSON subset for public
payload shapes, and business plugins may perform stricter validation.

DTO constructors validate their own shape. They cannot prove that a runtime
response belongs to a prior request: the service must compare
`RuntimeConfirmed.native_session_identity` and `runtime_generation` with its
`ResumeRequest`, instance lease, and operation journal before confirming or
sending a prompt. It must also verify target/field/action claims, contribution
ownership, and secret classification against the registered descriptors.
The ordinary-value guard rejects common credential field names, but semantic
secret classification remains a service and adapter obligation.
