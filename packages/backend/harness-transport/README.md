# Harness transport

Shared framing and owned subprocess I/O, without family protocol interpretation,
provider discovery, credentials or a daemon. This is a provider dependency;
Agent Tools does not import or distribute it.

AU003 reuses the reviewed ProcessChannel and managed NDJSONTransport. The former
came from products/agent-tools native_clients/_transport.py at 77a1d8a92c; the
latter from ordessa_harness/server_acp/transport.py at the same checkpoint.
Existing consumer tests are retained. Product copies are transitional sources
until AU004 removes/excludes them; no new runtime registration uses both routes.

A managed connection requires the actual transport writer lease. That lease is
an I/O barrier, not invocation authorization: a provider must verify trusted
platform authority, current activation/epoch, exact capture and operation claim
before each effect. Missing authorization refuses connection. A disconnected
connection does not stop the Unit. Process creation/termination remain owned
provider operations; no global configuration or user process is adopted.

C tests use scripted Python peer processes. They are real pipe/process evidence
for transport behavior, not proof of upstream Harness compatibility or tasks.
