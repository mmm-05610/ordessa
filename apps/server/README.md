# ordessa-server

The Server selects and starts one backend. HTTP/wire mechanisms live in
`packages/interfaces/transport/server`; system access routes through the public
Engineering service and selected execution owners. Independent Harness providers
keep their implementations. Kernel is retired; c1 contract retirement is still
in progress, with exact receiving-owner gaps in the current convergence handoff.

Python >=3.12 is required, matching the direct `ordessa-interfaces` dependency. Install the same checkout's packages using the [workspace commands](../../docs/reference/baseline.md), then run:

```sh
.venv-nightly/bin/python -m ordessa_server --data-root /tmp/ordessa-instance --port 0
```

The process binds loopback and reports its actual origin in the startup
handshake. During development select an isolated root explicitly; do not restart
user services or migrate user data as part of controlled tests.

Engineering is selected in this same formal product composition:

```sh
.venv-nightly/bin/python -m ordessa_server --data-root /tmp/ordessa-example-instance \
  --engineering-library /tmp/ordessa-example.sqlite --engineering-library-id example \
  --engineering-realm example --engineering-project example --engineering-create-library
```

Creation must be explicit and the library path must not exist. For a restart,
omit `--engineering-create-library`. The default machine scope is finite and
does not authenticate a human or supply missing reviewer/confirmation/acceptance
ports. CLI, MCP and Workbench consume this backend. The standalone
`ordessa_server.engineering` launcher and `build_engineering_runtime` are retired.
The current minimal commands, evidence and remaining Pi/JEV/catalog gaps are in
[the interface checkpoint](../../docs/implementation/packages-convergence-20261012/interfaces/CHECKPOINT.md).

Default authentication uses the existing protected instance bearer through one InstanceAccessAuthority. It identifies the local machine, never a human approver. Original local owner ACLs remain authoritative. Protected synchronous REST handlers hold an identity guard through their actual call; authenticated async routes require a future task-aware lease and are explicitly refused.

The Engineering access adapter uses the original Library/UoW/journal. Current real ASGI tests explicitly select a test-owned descriptor; production Engineering operation catalog/immutable receipt/project binding/CLI/confirmation are still incomplete. See [actual identity evidence](../../docs/implementation/nightly/evidence/W10/README.md) and [current status](../../docs/implementation/nightly/status.md).

```sh
.venv-nightly/bin/python -m pytest -q apps/server/tests/test_system_access_identity.py apps/server/tests/test_system_access_transport.py
```

All tests above use temporary data and synthetic tokens, with no model or native process. Broader inherited failures remain in the evidence ledger.

The default product's Unit admission is composed in
`composition/product_unit_admission.py` using the original Units SQLite store
and separate Harness/material catalogs. Root lifetime and Harness declaration
registration are separate; the old governance CoreBinding and `core.binding`
plugin port are retired. Missing configuration or reviewer authority is
unavailable, with no legacy fallback. Historical SQL/data identifiers remain.
Current scoped source/installed qualification and remaining distribution/test
limits are recorded in
`docs/implementation/ordessa-v1/evidence/kernel-retirement-product/unit-governance/HANDOFF.md`.

For the current Pi/Decision/Engineering edition, the default Harness capture
selects Pi only. Legacy workspace/skills/model-provider plugins and other
brands are not selected or required by the default Product package. Missing
original Pi owner/declaration refuses rather than creating a substitute.
Root methods' Skill assets remain in use. Current source/installed gate and
explicit unsupported boundaries:
`docs/implementation/ordessa-v1/evidence/kernel-retirement-product/first-edition/HANDOFF.md`.
