# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/ordessa_model_provider/__init__.py, verbatim)
"""Ordessa Model Provider domain plugin.

Owner of named provider configurations, the model catalog, bounded probes and
next-turn model selection for a Harness. Identity is the server-scoped triple
``(harnessId, providerConfigId, modelId)``; a session-level choice additionally
carries ``serverInstanceId``. State vocabulary is frozen in ``specs/002-model-
provider/data-model.md``: seven presentation states and four eligibility words.

Dependency direction (pinned by tests, spec FR-ARCH-3): this package depends
on host generic vocabulary (``ordessa_server.*``, ``pacthold``,
``server_plugin_api``) and on the optional port protocols in ``ports``. It never
imports Profile, Chat, the legacy ``ordessa_server_compat`` or host business
modules.
"""
