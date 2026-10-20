"""Public command-name declarations owned by this independent brand.

No probe, plugin loading, credential access or runtime guarantee is performed.
"""


def command_candidates() -> tuple[str, tuple[str, ...]]:
    """Return this brand's historical command candidates, including Windows names."""
    return ('claude-code', ('claude', 'claude-agent-acp', 'claude-agent-acp.cmd'))
