# Ordessa Engineering

`packages/engineering` is the sole `ordessa-engineering` distribution. The package
owns method-managed documents and immutable revisions, changes, reviews,
approvals, submissions, and method-run orchestration on the original
EngineeringLibrary/UoW/journal. Existing distribution, import, table and data
identifiers are preserved. Opening a Library never migrates real data implicitly.

The public command/query gate is
`ordessa_engineering.application.api.EngineeringService`. Build it through
`ordessa_engineering.application.assembly.build_engineering_service(factory, ports)`
with `EngineeringPorts` selected by trusted app composition. Request callers use
`await service.execute(operation, parameters, admitted_context)` or
`await service.query(query, parameters, admitted_context)`; schemas and finite
capability descriptions come from this same service. Missing access or required
source/reviewer/confirmation ports refuse explicitly. Actor attribution and
capability descriptions do not authenticate or grant permission.

`domain` and `methods` are independent lower modules. `methods` defines, loads,
validates and compiles external policies; root `methods/` owns the concrete
DID/JEV/spec-kit/Pi workflow and acceptance rules. `application` coordinates through
its own consumer ports. `adapters` bind those ports to original persistence and
public execution owners; application/API/assembly do not import concrete adapters
or execution. Native ACP observations are captured intact; report completion is
separate from independent review and formal acceptance.

The old `application.usecases.facade` and the DID-specific `EngineeringWorkflow`
runtime and policy helpers have been removed without shims. Current Method Work
uses the original persisted rows and CAS. Historical materials/runs/step_log data
remain readable; the former runner assertions are preserved verbatim in
[historical test evidence](docs/history/legacy-runner-20261012/README.md), not counted
as passing current runtime validation. Prototype descriptions and commands are in
[the preserved former README](docs/history/README-before-public-service-20261012.md).

The independent ImplementationDispatch start_run and implementation-run
resolver are also retired. Current dispatch resolves the selected fixed MethodRun node and its explicit package_slot
inside the original UoW. Live node/control/attempt and original effect guards are required;
missing actual source/port refuses. History is never a dispatch fallback.
Work.start rechecks the source owner's ReadSet in the original write transaction
before inserting the run, alongside the existing method-control fences.

Native completed/failed results can join the same MethodRun step log and cursor; unknown
refuses advancement and is never retried. Old strong Submission.record/quarantine and its
owner route/descriptor are retired; explicitly submitted reports remain pending review.

This is still a partial product integration. Production Work/native composition,
report/acceptance sources and full reviewer/confirmation assembly remain
incomplete. The external method candidate 2.5.0 now passes public loader,
validation and compiler checks against 19 exact descriptors, with one explicit
fixture-trust warning. Those detached prototype descriptors are not registered
production sources; the candidate has no MethodRef snapshot and is not published.
Engineering accepts explicitly submitted method-required documents/reports and
checks their exact version/task/author/review bindings, not executor code or Git.

Current public API, actual limited descriptors, commands, failures, wheel evidence
and cross-owner requests are in the
[2026-10-12 handoff](../../docs/implementation/packages-convergence-20261012/engineering/CONTRACTS.md).
Use the worktree environment for source tests; root environments and historical
counts do not verify this checkout. No whole-product completion is claimed.
