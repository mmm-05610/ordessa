# Agent UI reuse probe

An opt-in, standalone extension, not the product conversation feature. It is not
listed in `extensions/product.json` and does not change the user's enablement file.

## Run the verification

From the repository root:

```sh
npm run build
npm run build:examples
npm test
xvfb-run -a npm run test:agent-ui
```

The Electron test loads `example.agent-ui` alongside the existing foundation
extensions in a disposable user directory. It never connects to an agent or model.
The test-only launcher uses `--no-sandbox`; ordinary app launch is unchanged.

## Boundary

`store.ts` is a controlled service fixture with independent message types and
immutable snapshots. `view.tsx` converts them into assistant-ui's
`useExternalStoreRuntime` and composes its message, viewport and composer primitives.
`entry.tsx` registers one view and navigation command through existing scoped APIs.
No agent concepts were added to the host, contracts or workbench.

Reuse: @assistant-ui/react 0.15.21, MIT, fixed build/test dependency. Official
reference: https://www.assistant-ui.com/docs/runtimes/custom/external-store .
The built probe includes its license. No AI SDK or assistant-cloud service is
configured. Transitive dependencies do include assistant-cloud; package presence
does not mean a cloud connection is required or exercised here.

## What was actually tested

- External historical messages, composer send callback, two text updates.
- Pending tool call and subsequent result using a fallback renderer.
- Composer cancellation, rejection of stale generations and writes after disposal.
- Switching away and restoring messages without mixing two sessions.
- Distinct completed, cancelled and failed status mapping.
- Real Electron dynamic loading with shared React and a sandboxed renderer.

Text smoothing is disabled so the probe displays received snapshots immediately.
The fixture acknowledges cancellation synchronously and cancels a run on session
switch. Those are fixture policies, not requirements for a production adapter.
The stale-event guarantee belongs to the fixture/adapter, not assistant-ui.

## Not validated / not implemented

Real server transport and reconnect, uncertain cancellation, concurrent background
sessions, persisted history, approval interactions, reasoning blocks, attachments,
Markdown, accessibility audit, model selection and large-history performance.
This is not a newly frozen agent protocol or a production-quality conversation UI.

Recommendation: use assistant-ui privately inside the conversation extension;
keep session/connection/approval contracts independent. Do not export library
runtime types from a shared service contract. Keep unsupported edit/regenerate
callbacks absent rather than implicitly enabling capabilities.
