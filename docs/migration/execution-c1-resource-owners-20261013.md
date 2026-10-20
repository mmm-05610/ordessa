# C1 resource owner cutover — TODO (14)

The parent approved these five ownership decisions on 2026-10-13. This is a
resource-contract slice, not whole-C1 or default-product completion.

| Retired C1 resource module | Actual owner and public receiver |
| --- | --- |
| `resources/profiles.py` | Agents/Profiles: historical projection declarations and view port; management owns exact envelope parsing/validation. Public receiver `ordessa_execution_agents.profiles`. |
| `resources/credentials.py` | Agents/Harness: `CredentialRefV1` in `harness.definitions.credentials`, exported by Harness definitions. |
| `resources/workspace.py`, `resources/prompts.py` | Units: `definitions.material_delivery` resolved workspace/prompt delivery declarations. |
| `resources/secret_mounts.py` | Units: `definitions.secret_mounts` execution-scoped materialization/cleanup declarations; Environments retains its neutral `SecretMountInput`. |

All five old modules and their empty package initializer are deleted. There is
no C1 alias, forwarding module or fallback. Pi/Codex consumers are external
Harness plugins, not Agents core consumers. Agents core introduces no Units
dependency. Claude/Hermes/OpenCode history projection and the resource tests
use Profiles' actual public receiver. Codex explicitly converts native
credential locators; `CredentialRefV1` and Profiles `SecretRef` remain distinct.

Original `agent-box.*@1` contract identifiers, DTO fields, historical digest
framing and validation behavior are preserved. No data rewrite, database
migration, credential read or service restart accompanies this cutover.
Historical Profile views grant neither Profile access nor execution; native
credential locators and prepared mounts contain no credential values. Missing
workspace/prompt producers and unbound secret resolution remain unsupported;
this slice introduces no producer, authorization or alternative launch flow.
The original CredentialMaterializer declaration still differs from Codex's
actual resolve/cleanup method shape; no new production binding is claimed.

## Retained behavior and actual checks

Fresh artifact root: `/tmp/ordessa-c1-resources-current`. Fourteen public
source/metadata project snapshots contain 603 files; manifest SHA-256
`ac82af0b98c2e1fcb67234b14496aee5bf3ec374c3db6b3a56b55db2319440d7`.
Six core wheels install noneditable without C1, pass pip check and import 215
modules with C1/Apps/Interfaces/Engineering/Pacthold blocked. Four planted
boundary controls pass. A separate process imports 104 Agents modules with
Units also blocked, including a dynamic negative control. The separate C1
wheel contains none of the retired resource package or four previously
retired environment modules. All fourteen consumer wheel payloads and selected
import origins match the frozen artifacts. Consumer scenarios borrow the
core dependency closure and current interface/application migration helpers;
this is not a standalone whole-product dependency qualification.

The same resource/registration/Profile/dispatch/product-binding slice passes
55 tests from source and 55 from installed wheels, without skips. Broader
installed core regression passes 116 and runtime/provider assembly passes 31;
these scopes overlap prior receipts and must not be added to historical totals.
Failure history is retained in the artifact root, including the old pristine
journal constructor wrappers and the cold native-evidence refusal.

Original no-resend scenarios now exercise the real Unit/SQLite/Local/ACP owner:
accepted, lost, post-launch refusal/value error/preparation mislabel, preflight,
invalid session receipt and interrupted launch. They retain one durable native
attempt, exact SQLite receipt/revision and no second launch across a cold
facade. Preflight remains `notCreated`; uncertain creation remains `unknown`
or `opening`. Cold confirmed live access requires original same-channel native
proof and is explicitly refused when that proof is absent; the durable row is
unchanged. A generic Work dispatch replay endpoint is not restored.

The retired `apps/server/tests/execution/test_dispatch_composition.py` tested
the removed `pacthold.work_core` Work/Execution writer. Current production
source has no such writer import or ExecutionService construction; Units
retains the old core tables only through explicit read-only ExecutionHistory.
Its eight safety scenarios are now in Unit-owned
`tests/test_start_dispatch_retirement.py`. The unique product-port/factory
binding scenario is in the real default product's
`tests/test_host_execution_identity.py`, without the unrelated Server legacy
assembly helper. The controlled storage factory proves binding identity,
not database admission or whole-product launch. The original test source is
preserved outside the repository in the artifact root for comparison.

Modern Profiles retain dual revision CAS/history, request replay/conflict,
SQLite cold reopen, concurrent API edits, UNKNOWN request consumption, current
ACL refusal without spending keys, principal isolation and closed-context
refusal on UnitProfileAdmission and the original SqliteUnitStore.
Registration guarantees remain with their actual catalogs. Material staging
now rejects duplicate pending provider IDs and reentrant metadata registration;
metadata discovery remains detached and effect-free. Harness catalog tests
retain its actual declaration/policy/drain/retirement guarantees.

## Remaining boundary

Old CoreRegistry runtime-object/method admission, multi-category atomic
publication, installed/enabled activation fences and reserved Core surfaces
are not the Harness declaration metadata API. The parent subsequently retired their isolated old test contracts; current
Unit safety is separately required by E08/E09 and is not equivalent coverage. The two old material operation/consumption fixtures now use the actual Unit
context/catalog: source and installed each pass 49 scenarios without skips,
preserving holds and UNKNOWN semantics. Old successful-retire callback cases
now explicitly test drain refusal; final retirement remains blocked while
active/UNKNOWN Usage persists, not reported as completed retirement. The subsequent concrete error and metadata cutover has zero production C1 imports. The parent retirement decision is applied to the three legacy test groups,
including their embedded script. The entire C1 directory is now absent.
Final 21 owner wheels and noneditable core installation are byte-bound in the
linked checkpoint and C1-FINAL-ERROR-SLICE-20261013.json; public acceptance
status remains in the immutable E01—E12 checklist.
OpenShell's separate authorized recovery is recorded under the Execution
environment-api evidence; gateway health alone does not qualify its provider.
