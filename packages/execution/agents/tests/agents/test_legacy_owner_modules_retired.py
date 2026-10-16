"""The former Agent/Profile execution owners are not importable aliases."""
from __future__ import annotations

import importlib.util


RETIRED_MODULES = (
    "pacthold.agents.profile_services",
    "pacthold.agents.facets",
    "pacthold.agents.sessions_overlay",
    "pacthold.agents.submissions",
    "pacthold.agents.submissions.capture",
    "pacthold.agents.submissions.journal",
    "pacthold.agents.submissions.owners",
    "pacthold.agents.submissions.service",
    "pacthold.agents.configuration.observation",
    "pacthold.agents.configuration.policy",
    "pacthold.agents.configuration.profile_contracts",
    "pacthold.agents.configuration.profile_errors",
    "pacthold.agents.configuration.profile_ids",
    "pacthold.agents.configuration.profile_sensitive",
    "pacthold.agents.configuration.profile_service",
    "pacthold.agents.configuration.resolution",
    "pacthold.agents.configuration.journal",
    "pacthold.agents.configuration.harness_port_adapter",
)


def test_retired_owner_modules_have_no_importable_module_or_alias():
    for module in RETIRED_MODULES:
        try:
            spec = importlib.util.find_spec(module)
        except ModuleNotFoundError:
            spec = None
        assert spec is None, module
