# Coordinator handoff

## Frozen package contents

- No root-level manifest represents the complete lifecycle. `projection/method.yaml` is the explicitly named `ordessa.gitlab-product-change.report-smoke` under `ordessa.methods/v1`; it declares `full_flow_support: unsupported` and one real required operation, `engineering.artifacts.create` (interface version 2; digest recorded in the manifest).
- `projection/workflows/report-capture.yaml`: one acyclic capture operation with registered `completed` and `rejected` outcomes. Inputs are operation slots (`artifact_kind`, `initial_payload`, `method_refs`). There are no invented waits or lifecycle operations.
- `projection/documents/product-change-report.schema.json`: full report contract with explicit `$id`; `projection/documents/product-change-report.template.md`: human entry template.
- `PROCESS.md`: full external flow specification, including dual tracks, stage entry/exit, role and approval responsibilities, skipping, blocking/resume, rework, delay/cancel, feedback, deployment/version distinctions, and source status differences.
- `SOURCES.md` and `_support/source-index.json`: source URLs, retrieval dates, observed page dates, mutable-page caveats, and observed status/version differences.
- `_support/design-traces/*.report.json`: three synthetic report examples only, including before/after rework and wait/resume history.
- `GAPS.md`: capability state by supported / partly implemented but not production-bound / missing / process-only, with repository path and symbol references.

## Exact operation and payload constraints

The projection declares `engineering.artifacts.create`, interface v2, contract digest `0bc02e9e5a17ada14fc47a3da92abd6c360247768ab0ab1debfc6ec444b213f4`; this task did not invoke it. The graph maps `artifact_kind` to `kind`, `initial_payload` to `initial`, and `method_refs` to `method_refs`. These must be supplied as slots; `config` is not input data. The expected report is a `MethodPayload` whose method reference exactly matches an entry in `method_refs`, and whose `schema_ref`/`schema_id` resolve to the method's declared report schema. The schema ID is `urn:ordessa:gitlab-product-change:report:v1`.

`completed` is only artifact-capture completion; `rejected` is capture rejection. Neither establishes report acceptance, GitLab state, approval, merge, deployment, product success, or source truth. The package contains no runtime/published-catalog evidence and does not claim full lifecycle execution.

## Verification requested from coordinator

Please run the repository compiler and payload codec checks serially against this frozen package, record their actual outputs under the coordinator-owned `_support/verification/` location, and check that all three synthetic reports validate against the schema and actual `MethodPayload` binding. Do not treat the design traces as execution evidence. Any resulting package changes should be returned to this method owner for an authorized in-scope edit, then rehashed and revalidated by the coordinator.


## 协调者最终实测

上述待验证事项现已按同一固定核心字节快照完成。详情与退出码见 [_support/verification/README.md](_support/verification/README.md)。没有发布或runtime运行；smoke直接operation入口也不满足当前Work start契约。后续设计讨论请读 [_support/verification/design-findings.md](_support/verification/design-findings.md)，小数兼容项单列，不能当全局架构缺口。
