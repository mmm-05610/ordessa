# Pi Profile bridge (additive developer asset)

Pinned upstream: `@automatalabs/pi-acp@0.5.0`, embedding
`@earendil-works/pi-coding-agent@0.84.2`. `server.mjs` follows the upstream
`dist/server.js` registration (Apache-2.0); standard requests, steering,
loaded-turn, session state, configuration changes and disposal are delegated
to upstream implementations, not reimplemented.

Build with the existing locked source and `--profile-bridge`. The default
builder output and upstream `dist/index.js` stay unchanged. The enhanced
entry is `dist/ordessa-profile.mjs`; all added modules are included in
the full-tree digest. Do not launch this variant as the default installed
adapter or loosen installed-source verification to accept it implicitly.

The session owner must allocate a canonical, private, user-owned directory
and pass `ORDESSA_PI_INSTANCE_DIR` before launch. Startup refuses missing,
shared or symlinked directories. Pi auth, model definitions, default settings
and session files use that instance directory. No login/configuration files
are copied from global Pi state. This is instance isolation, not a sandbox;
project-local configuration is still upstream Pi behavior. Separate sessions
requiring independent defaults must use separate instances/directories.

The additive provider variant accepts `_ordessa/channel/configuration/prepare`
before a dedicated instance's first `session/new`. The model-provider resource
catalogue supplies bounded model IDs; Harness registers them via Pi's locked
`ModelRuntime.registerProvider` and imports the key with `setRuntimeApiKey`.
Keys are opaque runtime values, never Pi's executable configuration strings.
Registration refresh is explicitly offline. No model definition file or key is
persisted (upstream may create an empty `auth.json` while locking its storage).
Prepare reserves once, retains Unknown on failure, and queries never repeat an
effect. After native creation, selected model and route are independently read
back. This is creation evidence, not a Profile receipt. Profile C4 additionally
requires exact live owner/generation and unchanged credential binding.

`probe-initial-provider.py` checks two real private adapter processes with
synthetic keys and a loopback provider that refuses inference. It proves the
adapter only; root-installed product Profile/wire verification is separate.

`initialize._meta.ordessaConfiguration` advertises version 1.
`_ordessa/session/configuration` accepts only `{sessionId}` and returns:

```json
{"sessionId":"native-id","generation":"opaque-instance-id","busy":false,"configOptions":[]}
```

Options are read from the upstream live session's `configOptions()`, not
echoed from a requested Profile. The generation identifies that actual live
object and changes if the object is replaced; it is not a configuration
revision or an authorization grant. Unknown/closed/disposed sessions refuse.
The query does not load sessions, change configuration or invoke a model.

Model options additionally carry `_meta.ordessaModel` only when a unique
upstream `availableModels` entry establishes exact provider, model, native API
and base URL. This closed projection contains no credential/header material;
credential-bearing URLs and ambiguous/missing facts are omitted. Previously
carried reserved metadata is removed before fresh observation. It permits
selection of an already available matching model, not installation of a new
provider, credential application or arbitrary parameters.

`--owner-rpc --owner-operations --owner-live-model` additionally exercises the
real C2 carrier, C4 journal and Pi executor with two synthetic local models.
It checks receipt, independent query, idempotent replay and no materialized
files, sending zero prompts. Its channel ledger remains a fixture and the
asset is developer-built; it is NOT a production Profile application receipt.

Verification: `node --test packaging/pi-profile/*.test.mjs` and
`python packaging/pi-profile/probe-nomodel.py /absolute/enhanced-artifact`.
The latter runs real Pi with an isolated HOME and explicitly synthetic API
key (not a real credential), creates a session, changes thinking level,
queries independent readback, checks isolated settings/global sentinel,
closes the session and confirms process exit. It sends zero prompts.

Remaining production integration: trusted installation/launch of this exact
variant, canonical ACP owner binding, explicit configuration-action grants,
activation receipt/readback, and Profile's submit boundary. These are not
proved by this standalone probe. Codex/Claude restart/resume/provider changes
are also outside its evidence.

For the backend readback seam, use the integration interpreter and add
`--owner-rpc` to the probe. It runs the real `_Channel` observation/query
implementation against real Pi, checks that owner replies do not reach the
client relay, and refuses evidence after native close. The channel's ledger
fields are fixtures: this proves the control read, not the full Server product
composition or canonical Profile session registration. The opaque native
generation must not be passed as the integer C4 `ApplicationTarget` generation
without a separately owned mapping/fence.
