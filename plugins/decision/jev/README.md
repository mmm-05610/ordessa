# Jev Decision provider

The sole Jev adapter is this independent ordessa-decision-jev distribution, imported as ordessa_decision_jev. It depends on the public ordessa_decision contracts and pinned official TypeSafe SDK0.7.2. Host assembly injects configuration and a secret resolver; tests use fake transport only. There is no retired ordessa_decision.providers.jev alias or fallback.

OpenCode Zen is a model provider usable through this adapter; it does not select an OpenCode Harness. The preparation's bounded free HTTP probe does not establish SDK/product wiring or decision quality. Default settings remain explicit historical TypeSafe configuration; Zen requires verified host-selected configuration, no implicit backend/paid switch. No production credential or new persistent access is configured here. Laya remains NOT_ENABLED without an implementation.

Run .venv-nightly/bin/python -m pytest -q plugins/decision/jev/tests from the worktree. Wheel isolation and current acceptance are recorded in docs/implementation/nightly/evidence/W08; do not infer them from this directory's existence.

Validation `jev-protocol/2` recognizes one bounded provider correspondence:
at the exact `https://opencode.ai/inference/systemone` base, requesting and receiving
`jev-1.13-free` may satisfy an explicitly selected `jev-1.13.0` response pin.
[OpenCode](https://opencode.ai/v2/docs/console/models/) documents that free Jev
1.13 route and [TypeSafe](https://docs.typesafe.ai/models) documents the versioned
Jev 1.13 ID. A historical response echoed the free route ID; this finite
comparison does not prove underlying weights or decision quality. Native JSON
and SDK model fields must still match exactly, and receipts retain the actual
`resolved_model`. Other endpoints, request aliases, unexpected response models
and mismatched SDK fields remain refused. The validation version changes the
settings fingerprint; old version 1 settings are not accepted as version 2.

The SDK appends `/v1/systemone` to this base. The host-selected OpenCode route
therefore resolves to `https://opencode.ai/inference/systemone/v1/systemone`,
as documented by OpenCode on 2026-10-17. Changing the base changes the settings
fingerprint; no old-route retry or fallback is provided.
The corrected route has local SDK construction coverage and successful real
synthetic responses. Those diagnostics do not establish a formal review.

HTTP 400/422 diagnostics may retain at most 16 allowlisted validation codes
and canonical public field paths. Dynamic state keys, question/option IDs,
messages, inputs, contexts, headers and raw bodies are never projected.
Finite provider codes also recognize the service's nested `detail.error_type`;
only exact allowlisted values are retained.

`JevProviderSettings.long_context` is an explicit request setting, defaulting to
`False`. It accepts only a boolean. When true, the adapter sets the fixed SDK
header `TypeSafe-Danger-Zone-Long-Context: true`; task/question input cannot set
or override it. False preserves the previous settings digest and omits this new
field from its digest input. True includes it, requiring a matching new permit
and retaining the new settings digest in the normal provider receipt. Existing
positional parameters retain their order.

[TypeSafe](https://docs.typesafe.ai/models#long-context) documents 262k tokens
with this header, with slower and potentially less accurate decisions. That
source does not establish OpenCode gateway support. The prototype must verify
the selected OpenCode route with an independent full-question diagnostic before
using the setting in a formal eight-question Work. No material, review rule,
model, credential, endpoint or acceptance requirement changes with this option.

On 2026-10-17, the selected OpenCode route returned HTTP 400 for the independent
full-question long-context trial. Effective gateway support remains unverified;
no formal eight-question review or package generation was admitted by that
trial. TypeSafe source documentation is not gateway qualification.

A subsequent five-request synthetic differential passed small, nested and
128 KiB input cases. A 330000-byte input returned `max_tokens_exceeded`, both
without and with the fixed long-context header; their wire bodies were identical.
This confirms a context rejection for that synthetic input, not the token count
or cause of every historical full-DID rejection. Effective larger-context support
on the selected gateway remains blocked. Diagnostics stopped after this matrix;
no DID truncation, review-policy change or backend fallback was introduced.
