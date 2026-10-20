# ordessa-harness-opencode

The actual leaf exports its SDK-only HarnessProvider and factory entrypoint.
Profile pin and `opencode.configuration/1` validation remain brand-owned; native
compilers and packaged native assets are retained. Preparation is pure and uses
only approved bound roots/command/nonsecret environment. No direct HTTP client,
Unit owner, ambient credential lookup or raw transport fallback remains.

The selected native channel remains HTTP/SSE, not ACP:
`opencode-http/1`. The provider supplies a native serve LaunchPlan,
but `open_session` explicitly refuses `HTTP_BOOTSTRAP_UNAVAILABLE`. The Agent
owner must reject unsupported protocols before launch. The old ACP production
artifacts are **not** a runtime fallback. Native HTTP receive/send/control ports
are not yet implemented in the current SDK owner, so this is a concrete provider
preparation migration with an explicit unavailable interaction gap, not complete
native runtime acceptance.

Nonempty native session/message configuration, credentials and resume refuse;
no configuration fields silently disappear. Native loopback binding is explicit.
OpenCode adds `serve --hostname 127.0.0.1 --port 0` (actual assigned port
requires original-owner discovery); disables auto-update/model-fetch/LSP download.
Old Profile/continuation resolver, projection, installation and registration
adapters depended on retired harness internals/API and are physically removed.
The data-only historical `OpenCodeContinuationV1` contract remains readable;
it cannot resolve, resume or authorize a new instance.

Original `tests/clients/test_opencode_client.py` retains all nine HTTP L1 tests
unchanged, including receipt versus completion, unknown SSE data/disconnect,
abort, async acceptance, loopback refusal, typed errors/no retry, and closed-use.
Original three locator tests remain unchanged and currently target removed live
resolvers. They require migration to historical-only readers; no skips or aliases
were added. Production-template tests still consume old captured-catalog fixtures
and are not new SDK runtime proof.

Pure `production.py`, native dialect facts, command-name data and packaged resource
lists remain offline inputs, with no import of retired host internals. Historical
deployment capability keys are local document vocabulary, not a runtime registry
or observed readiness source. Existing original tests/assertions are not removed,
skipped, or counted green. Native capability matrix now marks removed HTTP runtime
support unavailable, and all observations remain unobserved.

New tests/test_sdk_provider.py covers exact pins, immutable native plans, explicit
configuration/security refusal, SDK import boundary and no ACP fallback. This
slice ran no tests/install/build or model/network calls; integration runs serially.
