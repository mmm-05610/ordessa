"""`ordessa_extensions` — the executable-extensions domain (016 EXT).

Scope (specs/016-overnight-batch tasks.md EXT-1..7): hook *definitions*
(event/matcher/command-or-handler/timeout/async), the mandatory approval
chain over executable content (机制 D: 强制批准 + 来源哈希 + 版本 pin),
the shell-injection surface checklist, the eight-brand hook support table
graded from in-repo evidence, and the `assets.hooks` configuration
adapters registered through the published `harness.configuration-adapters`
point (C2).

Hard boundaries (all pinned in tests):

* pure domain — no process spawn, no HOME write, no network, no import of
  `ordessa_server`, `ordessa_harness` internals or any desktop host
  (AGENTS.md rule 3; only the published `ordessa_harness_api` and
  `server_plugin_api` vocabularies are consumed — the domain uses no
  pacthold surface at all);
* an unapproved hook definition is NEVER loaded (fail closed — EXT-3);
* observational placement only: nothing in this domain may promise that a
  hook *blocks* or *enforces* (EXT-6; the Codex MCP hook failure-does-not-
  block counterexample is classification.md §四.4).
"""
from __future__ import annotations

#: The facet id this domain owns in the harness configuration contract.
FACET_ID = "assets.hooks"

PLUGIN_ID = "ordessa.extensions"

__all__ = ["FACET_ID", "PLUGIN_ID"]
