"""Shared bridges owned by the agents mechanism.

A bridge adapts another owner's runtime objects to the agents SDK contracts
without importing that owner. The concrete owner stays a composition decision
of the caller, which injects the owner-specific pieces it alone may know.
"""
