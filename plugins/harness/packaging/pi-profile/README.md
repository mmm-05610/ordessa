# Pi Profile bridge (additive developer asset)

Pinned upstream: `@automatalabs/pi-acp@0.5.0`, embedding
`@earendil-works/pi-coding-agent@0.84.2`. `server.mjs` follows the upstream
`dist/server.js` registration (Apache-2.0); standard requests, steering,
loaded-turn, session state, configuration changes and disposal are delegated
to upstream implementations, not reimplemented.

Build with the existing locked source and `--profile-bridge`. The default
builder output and upstream `dist/index.js` stay unchanged. The enhanced
entry is `dist/ordessa-profile.mjs`; all three added modules are included in
the full-tree digest. Do not launch this variant as the default installed
adapter or loosen installed-source verification to accept it implicitly.

The session owner must allocate a canonical, private, user-owned directory
and pass `ORDESSA_PI_INSTANCE_DIR` before launch. Startup refuses missing,
shared or symlinked directories. Pi auth, model definitions, default settings
and session files use that instance directory. No login/configuration files
are copied from global Pi state. This is instance isolation, not a sandbox;
project-local configuration is still upstream Pi behavior. Separate sessions
requiring independent defaults must use separate instances/directories.

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
