# Decision Runtime

This is the independent `decision-runtime` Python distribution. It provides
host-neutral Decision DTOs, codecs, bounded execution, evidence ports/storage,
with provider ports. Jev is the independent plugins/decision/jev distribution; the core has no concrete provider, SDK dependency or provider extra. The runtime requires Python 3.10 or newer because
its pinned `pydantic-graph==2.54.0` dependency has the same minimum.

Pacthold's base distribution retains its Python 3.9 minimum. Installing
`pacthold[decision]` requires Python 3.10 or newer because that extra installs
this distribution. The extra intentionally has no environment marker: Python
3.9 must receive a resolver incompatibility instead of silently omitting the
Decision dependency. Ordinary Pacthold installation remains independent of
this runtime.

The deterministic material-screening and DID source-mapping examples exercise
different typed inputs, rules, graph flows, and refusal/clarification outcomes.
They validate plumbing only, not domain quality, compliance, user approval, or
live model behavior.

## Independence

The package imports nothing from `pacthold`, `ordessa_engineering`,
`ordessa_execution_agents` or any host. A host depends on this package, never the
reverse. `pacthold[decision]` and engineering's review path are *consumers*.

The wire/value format is `decision-json/1` (`CODEC_VERSION`). `canonical()` /
`digest()` bytes and the packaged JSON vectors are the frozen format; they are
never rewritten to make a change compile.

## The four groups

This is the whole package; each group has one responsibility and one owner:
**definitions → validation → runtime → evidence** (import direction only, no
cycle). `decision_runtime.__all__` is an explicit frozen contract (see
`tests/contracts/test_public_surface.py`, which also keeps a counter-example that
the former stdlib/typing export leak cannot return). `json_schema` is a
**schema-declaration/build tool** that generates the packaged
`definitions/*.schema.json`; the runtime does not call it to execute a decision.

| Group | Owns | Add here when… |
| --- | --- | --- |
| `definitions` | Immutable `decision/1` DTOs (`models.py`), ports (`ports.py`), the `decision-json/1` value codec (`values.py`), the error contracts (`errors.py`), and JSON-schema **declaration/build** generation (`schemas.py:json_schema`). | You add a field/type, a host-injected port, a value-format rule, an error contract, or a declaration. Format and declaration only — no IO, no host, no runtime behaviour. |
| `validation` | Input decode/check **actions**: `construct` (bounded DTO construction) and `decode_request` (request decode). | You add a decode/check action. The value *mechanism* stays in `definitions.values`, so `definitions` never depends on `validation`. |
| `runtime` | Bounded execution: `run_decision`, `read_result`, `TrustedFlow`, `flow_digest`, `reviewed_code_digest`, `RunContext`, `NodeServices`, `immutable_queries`, and the runtime failure re-exports. | You add or change execution/limit/flow behaviour. Calls/limits live beside the runner; failure *contracts* stay in `definitions.errors`. |
| `evidence` | Summary-only evidence encoding (`codec.py`) and the offline sinks/reader (`stores/memory.py`, `stores/filesystem.py`). | You add an evidence sink/reader or an encoding rule. Never a second recording authority. |

## Call entry, request and output

Entry point is one function:

```python
from decision_runtime import run_decision, read_result, TrustedFlow, RunContext, RunLimits
result = await run_decision(request, flow=..., services=..., limits=RunLimits(...))
readback = await read_result(result.run_id, services=...)
```

- **Request in**: a `DecisionRequest` (a `definitions.models` DTO, itself
  `decision-json/1`). Host-supplied data arrives through the injected ports
  (`DecisionProvider`, `ObservationPort`, `EvidenceSink`, …) — the runtime never
  reaches out on its own.
- **Output out**: a `DecisionResult` DTO plus encoded evidence. Evidence rows are
  **summary-only**: fixed safe keys (`run_id`, `call_id`, `*_digest`, `usage`,
  `code`, `status`, …) and hashes; unknown keys are dropped and prompt/body/
  header/token/secret-shaped values are refused (`evidence/codec.py`).

## Errors and unknown evidence

- `ContractError` — closed DTO/codec refusal (bad shape/type/value at the
  boundary). Carries a fixed code, never a payload.
- `RuntimeFailure` family (`BudgetExhausted`, `EvidenceUnknown`,
  `ExplicitCancellation`, and the base) — the public runtime failure contract.
- **Unknown is a first-class result, not a crash**: if the provider or sink
  cannot be trusted to have recorded exactly one entry, the run reports
  `EvidenceUnknown` (readback status `unknown`) instead of claiming success.
  Durability ACKs are re-checked against the exact expected sequence/digest and
  must be `durable` in real mode.

## Examples

`examples/two_domain_runtime.py` is a runnable, host-free entry point: it builds
two distinct typed domains (material screening, DID source review) over the same
neutral request/runtime/evidence API and prints a JSON row per case. It is the
smoke used by the acceptance test:

```
python examples/two_domain_runtime.py
```

## Tests

```
python -m pytest packages/execution/decision/tests
```

The two `tests/acceptance/*` cases are env-gated: `test_release` needs
`DECISION_ACCEPTANCE_ARTIFACT_ROOT` pointing at an artifact dir holding the built
wheel and a decision-only `runtime-env/`; `test_two_domain_runtime` requires
`pacthold` to be absent. Run the whole suite in a decision-only venv (see the
closeout evidence) for the full green.
