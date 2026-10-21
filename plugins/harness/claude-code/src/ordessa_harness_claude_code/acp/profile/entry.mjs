#!/usr/bin/env node
import { establishPrivateScope } from "../../../../../../../packages/execution/agents/src/ordessa_agents/harness/configuration/acp/private_scope.mjs"
establishPrivateScope(Object.freeze({"environmentKeys": ["HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"], "managedAccountKey": "ORDESSA_CODEX_MANAGED_ACCOUNT_DIR", "supportsManagedAccount": false, "managedHomeKey": "CODEX_HOME", "clearedCredentialKeys": []}))
await import("./index.js")
