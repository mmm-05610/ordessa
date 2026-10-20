# ordessa-harness-qwen

The actual leaf exports its SDK-only HarnessProvider and factory entrypoint.
Profile pin and `qwen.configuration/1` validation remain brand-owned; native
compilers and packaged native assets are retained. Preparation is pure and uses
only approved bound roots/command/nonsecret environment. No direct HTTP client,
Unit owner, ambient credential lookup or raw transport fallback remains.

The selected native channel remains HTTP/SSE, not ACP:
`qwen-serve-http/1`. The provider supplies a native serve LaunchPlan,
but `open_session` explicitly refuses `HTTP_BOOTSTRAP_UNAVAILABLE`. The Agent
owner must reject unsupported protocols before launch. The old ACP production
artifacts are **not** a runtime fallback. Native HTTP receive/send/control ports
are not yet implemented in the current SDK owner, so this is a concrete provider
preparation migration with an explicit unavailable interaction gap, not complete
native runtime acceptance.

Nonempty native session/message configuration, credentials and resume refuse;
no configuration fields silently disappear. Native loopback binding is explicit.
Qwen adds `serve --hostname 127.0.0.1 --no-web`; the approved bound cwd is
the daemon workspace (documented native cwd default), with no invented native
path resolution. Explicit QWEN_HOME is required. Existing compiler launch flags
are preserved, web enablement is refused, session fields are not dropped.

Original `tests/clients/test_qwen_client.py` retains all fourteen tests unchanged:
capabilities/client id; thread scope; attached identity; admission not completion;
unknown SSE/end not completion; cancel/delete; explicit permission vote; loopback;
typed error/no retry; unknown route; closed use; static description; transport type.
They target the retired HTTP client and remain unaccepted until original-owner
HTTP ports exist. Native ACP resources remain separate offline assets, not a
silent fallback. Static deployment claims now query the explicit qwen source
instead of the previous dsh cross-brand callback.

Pure `production.py`, native dialect facts, command-name data and packaged resource
lists remain offline inputs, with no import of retired host internals. Historical
deployment capability keys are local document vocabulary, not a runtime registry
or observed readiness source. Existing original tests/assertions are not removed,
skipped, or counted green. Native capability matrix now marks removed HTTP runtime
support unavailable, and all observations remain unobserved.

New tests/test_sdk_provider.py covers exact pins, immutable native plans, explicit
configuration/security refusal, SDK import boundary and no ACP fallback. This
slice ran no tests/install/build or model/network calls; integration runs serially.
