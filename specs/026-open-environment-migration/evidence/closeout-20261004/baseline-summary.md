# Stage 0 narrow baseline

2026-10-04 Asia/Shanghai. cwd is the 026 implementation tree. Node v22.22.1, Python 3.12.14, Vitest 4.1.10. Commands and source SHA recorded in baseline-results.json, exact output in baseline-N.log. All serial, fixture-only, no model calls.

| Command index | Collected / pass / fail / error / skip | Exit |
| --- | --- | --- |
| 0 design structure | 12 orders,129 tasks,111 cases,30 mutation samples; no implementation tests | 0 |
| 1 Agent backend | 15/15/0/0/0 | 0 |
| 2 UI components existing baseline | 77/77/0/0/0 | 0 |
| 3 Profile Chat | 93/93/0/0/0 | 0 |
| 4 model-provider Chat | 120/120/0/0/0 | 0 |

UI baseline excluded newly authored closeout tests, expressly to preserve original 77-case comparison. New regressions ran separately and failed: state 7F/4P; projection/query 6F/2P; UI storage 8F/0P (includes newly specified seam absent errors). These are new counterexamples, never inherited failures. Full Server red-ID comparison pending; no aggregate-green or real-product claim.
