# ordessa-decision

Owned decision core (`PC-20261019-F1`): `decision-job/1` validation, the
sequential `rules -> ask -> rules` runner over injected ports, neutral `when`
predication, bounded rules engines, and summary-only durable evidence.

- No I/O, network, model SDK, secret, workflow graph or third-party runtime in the
  core. Rules engines and decision providers are injected ports.
- Job JSON is closed: unknown keys, duplicate steps, unknown result steps,
  forward facts and limits above host bounds are refused before any effect.
- Facts are only `input` and prior step outputs; a skipped step referenced by the
  result is `result_invalid`, never a fabricated value.
- A model call is permitted once per call context; provider failure is `unknown`
  and is never retried. Evidence carries digests, engine/provider identity and
  usage only — no prompt, raw response or secret.

Historical `decision_runtime` flow graph (pydantic-graph manager/contracts) is
deleted from this package; `plugins/decision/jev` migration to the final ports is
the remaining item (see the stage report), and the capability adapter waits for
the DSH-1 `ordessa.capabilities` ABI.
