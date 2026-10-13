"""Explicit brand-owned pure C2 configuration provider port."""
from .configuration.c2 import configuration_adapter

def configuration_adapters():
    """Return fresh C2 implementations without host discovery or effects."""
    return (configuration_adapter(),)
