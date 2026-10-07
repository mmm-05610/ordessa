"""Transitional storage and implementations for the unmigrated Harness group.

Independent AgentUnit providers live in sibling packages. Importing this
package for its existing journal must not eagerly import brand implementations.
"""


def create_plugin():
    from .plugin import create_plugin as factory
    return factory()

__all__ = ["create_plugin"]
