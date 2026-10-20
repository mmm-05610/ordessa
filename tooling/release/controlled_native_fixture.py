"""Retired fixture for the former AgentSubmissionService integration.

This test-only fixture depended on the deleted `pacthold.agents.submissions`
execution path and simulated a managed input owner that the default product
does not have. Keeping a synthetic native port would make the retired route
look available. Closeout probes that require it must report unavailable until
a separately authorized current owner is wired.
"""


class LegacySubmissionFixtureRetired(RuntimeError):
    """The controlled fixture has no current submission consumer."""


def __getattr__(name):
    if name in {
        "ControlledNativeFixture", "controlled_product_composition",
        "controlled_submission_policy", "test_protected_fingerprint",
    }:
        raise LegacySubmissionFixtureRetired(
            "retired: fixture targeted AgentSubmissionService; managed input is unavailable")
    raise AttributeError(name)
