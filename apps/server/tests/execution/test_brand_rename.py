"""Brand pins owned by the compatibility assembly after docs/implementation/specifications/010 T009.

The kernel half of this file stays in ``packages/pacthold/tests``; the
contract-id pin moved with the contract package itself: the contract ids
are protocol, not display names, and their historical ``agent-box.*``
spelling is preserved byte-for-byte in this distribution.
"""
from __future__ import annotations

from pathlib import Path

import ordessa_skills.resource_contracts as _skill_contracts
import ordessa_agents.harness.definitions.harness_capabilities as _capabilities


def test_the_contract_ids_keep_their_historical_spelling():
    # The contract ids are protocol, not display names.
    skills_contract = (
        Path(_skill_contracts.__file__).resolve()
    ).read_text(encoding="utf-8")
    assert "agent-box.skill@1" in skills_contract
