# GitLab Product Development Flow method package

This directory contains a full external process specification and an explicitly limited smoke projection for recording a report as an Artifact. No compilable manifest here represents or drives the complete lifecycle. The sole manifest is isolated under [`projection/`](projection/) and calls only `engineering.artifacts.create`; it does not execute, route, or advance GitLab work. See [PROCESS.md](PROCESS.md) for the complete external process, [COVERAGE.md](COVERAGE.md) for stage-by-stage boundaries, and [GAPS.md](GAPS.md) for exact capability evidence.

`projection/method.yaml` binds the report schema, template, and capture workflow by resource digest. It is named `ordessa.gitlab-product-change.report-smoke` and declares `full_flow_support: unsupported`. The machine schema ID is `urn:ordessa:gitlab-product-change:report:v1`. A caller must supply `artifact_kind`, a schema-bound `initial_payload`, and the exact matching `method_refs` as operation input slots. The graph does not enforce a literal artifact kind or autonomously build the payload. The artifact's `completed` outcome indicates only that capture completed.

`_support/design-traces/` contains three synthetic, non-runtime report examples for success, rework/wait/resume, and rejection/postponement. They illustrate report values; they are neither engine traces nor verification evidence. Source observations and mutable-page/version notes are in [SOURCES.md](SOURCES.md) and [_support/source-index.json](_support/source-index.json).

`projection/method.yaml` is marked `design_only`. This package does not assert catalog publication, runtime execution, GitLab authentication, external claim verification, or production activation. All examples are synthetic. For exact remaining boundaries, consult [HANDOFF.md](HANDOFF.md) and [GAPS.md](GAPS.md).


协调者已完成同一核心快照的无网络检查：单次登记smoke加载/校验/编译通过，五类不支持/非法反例真实拒绝；报告schema与实际payload/input mapping通过。此投影不能直接按当前Work入口启动，完整流程仍unsupported。证据见 [_support/verification/README.md](_support/verification/README.md) 和 [设计缺口](_support/verification/design-findings.md)。
