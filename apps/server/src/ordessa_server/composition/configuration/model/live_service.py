"""Bind native configuration to original Agent services and public brand ports.

No C4 plan/permit/Unit journal is composed here. Installation observations are
brand facts, never current Agent identity or permission to apply configuration.
"""
from ..application import AgentConfigurationReadService


def create_agent_read_service(*, source, profiles, catalog):
    return AgentConfigurationReadService(source, profiles, catalog)


def verified_installation(brand, artifact_base):
    from .bindings import model_port
    return model_port(brand).verify_installation(artifact_base)


__all__ = ['create_agent_read_service', 'verified_installation']
