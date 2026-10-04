"""Agent-owned declarations supplied explicitly by product assembly."""
from pacthold.public import CoreContributionSet
from dataclasses import dataclass

@dataclass(frozen=True)
class AgentConfigurationIntent:
    contract_id = 'agent.configuration-intent@1'

@dataclass(frozen=True)
class AgentConfigurationObservation:
    contract_id = 'agent.configuration-observation@1'

def configuration_contributions():
    return CoreContributionSet(contracts=(AgentConfigurationIntent, AgentConfigurationObservation))
