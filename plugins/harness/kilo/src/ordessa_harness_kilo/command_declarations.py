"""Public command-name declarations owned by this independent brand.

No probe, plugin loading, credential access or runtime guarantee is performed.
"""
from ordessa_execution_agents.harness.definitions.command_discovery import CommandCandidate


def command_candidates() -> CommandCandidate:
    """Return this brand's historical command candidates, including Windows names."""
    return ('kilo', ('kilo', 'kilo.exe'))
