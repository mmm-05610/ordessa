# Ordessa Desktop CP candidate

This branch is an isolated HD-002 candidate based on FC integration commit `d14ac6e0e6`. It preserves the original FC and F0–F3 trees. It has not been merged into `main` and is not ready for user review.

## Installed product

`products/desktop/extensions.json` is the product admission list. Its eight extensions are foundation contracts, Agent contracts, commands, workbench, connections, sessions, the Ordessa Server connector, and conversation. The connector authenticates to one local Server instance before registration. Its token stays in Electron's native process; the renderer receives a non-secret instance identity.

The candidate excludes the old direct Pi and Codex desktop connectors, the empty Settings provider, and the empty interactions extension. Conversation still renders Server-backed approval cards. The source for excluded prototypes remains in the original FC and executor branch history.

`tooling/workspace/build-all.mjs` builds only admitted extensions and checks their `@extensions/` dependency closure. It clears the previous extension output first. `products/desktop/extensions.lock.json` records SHA-256 digests of that clean output; the runtime uses `extensions.json` as its enabled list. User `extensions.json` is a complete override and is never rewritten by the host.

## Local verification

```sh
npm ci
npm run typecheck
npm test
npm run build
npm run test:agent-shell
npm run test:electron
```

The shell test uses a loopback fake that answers authenticated `server.hello` without creating a session or contacting a model. It checks both a visible failure when the host handoff is missing and registration of the sole Server connector when a valid handoff exists. A real Server and native Agent are outside that test.

## Remaining acceptance

The candidate still needs a paired Desktop and native Server run with the same origin, token locator, and Server identity; a valid project; first send returning the real session ID; continuation in that session; and the agreed application gates. No real model request has been made by the candidate assembly work. Keep the CP ready decision with the HD-002 central record under `control/missions/HD-002`.

The previous modular host and direct connector development guide remains available in Git history at `d14ac6e0e6:README.md`.
