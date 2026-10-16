# Harness consumers: verified migration slice

Checkpoint: 2026-10-12 17:21 UTC; later qualifications have separately dated receipts.
This is a development checkpoint. Full C1 retirement and product acceptance remain incomplete.

The 81-file inventory's 141 old Harness/provider import groups now use the real
`ordessa_execution_agents.harness.definitions` owner. The Sol's four tooling probes
were parsed only; no live-model probe ran. Two executors explicitly configured as
`gpt-6-luna` changed nonoverlapping plugin areas. Eleven plugin distributions now
declare the actual Execution dependency and Python >=3.12. SDK/resource compatibility
dependencies remain only where other, explicitly recorded old contracts still have callers.

The repository AST scan parsed 2,190 Python files, excluding old C1 itself and build
outputs, with zero old Harness/provider imports. All 141 groups resolved through an
isolated installed owner with zero missing symbols or old-definition aliases. Interfaces
physically deleted the old Harness/agents families. The refreshed C1 artifact also lacks
both families without an import guard. No forwarding module was introduced.

## Qualified scopes

| Scope | Source | Noneditable installed | Limits |
| --- | --- | --- | --- |
| MCP Harness/controlled integration | 74 passed | 74 passed | Temporary local HTTP fixture; no models |
| Extensions | 101 passed | 101 passed | Original package suite |
| Permissions adapters | 132 passed | 132 passed | Original package suite |
| LSP adapters | 30 passed | 30 passed | Original package suite |
| Subagents | 863 passed | 863 passed | Original package suite, real import isolation |
| Prompts API/Harness adapters | 52 passed | 52 passed | Persistent-resource Environment test outside this scope |
| Skills Harness/boundary/apply scope | 93 passed | 93 passed | Other resource/runtime contracts remain |
| Runtime Preferences core | Full attempt: 146 passed, 5 failed | Selected core: 145 passed | Production/default C4 setup remains unqualified |
| Model Provider capability/lookup | Harness attempt: 57 passed, 36 failed before one guard fix | Selected capability: 33 passed | 35 old-composition cases unresolved; full suite timed out at 120s |
| Memory (full package suite) | 132 passed, 1 historical skip | 132 passed, 1 historical skip | `test_provisioning.py` retains the absent first-hand vendor-checkout skip |
| Sandbox adapters | 100 passed, 25 failed | Not full-qualified | 24 legacy-composition preconditions and one missing py.typed marker |

Counts overlap across source/installed runs and selected scopes; they are not additive.
Memory's single skip is the absent prior first-hand upstream checkout. The full source
and installed suites passed; the installed run used InstalledOwnerGuard to prevent
checkout imports. No new skip, assertion deletion or fake
capability was used. Installation validation corrected its own absent-child
import semantics; original Subagents absence/negative cases then passed unchanged.

Thirty-two frozen diagnostic wheels have 1,132 installed runtime members with zero byte
differences, including the refreshed Memory wheel. The eleven owned plugin source trees
match their frozen sources. Pip check passes. Other owners continue editing; this set is not final product distribution proof.

## Remaining concrete handoffs

See [CROSS-OWNER-REQUESTS.md](CROSS-OWNER-REQUESTS.md): Execution packaging must supply the
actual type marker; Interfaces must specify the real assembly path for original configuration
integration tests, preserving their effect/refusal/unknown/rollback assertions. Prompts needs
the actual persistent-reference/DataArea owner, not a renamed central SDK. Memory's approved
repository-marker guard passes the full source and installed package suites, with one
historical checkout skip each.

Exact commands, captured exit codes and controlled test logs remain local in this handoff
directory. Publication excludes private host paths, raw/internal logs and account-operation
receipts. A sanitized public checkpoint must not imply these local diagnostics were release gates.
