"""Existing descriptor/definition validation failures awaiting their real owners."""

class CoreError(RuntimeError):
    """Base class for every typed Pacthold core-contract failure."""


class CoreDTOError(CoreError, ValueError):
    """A C1 DTO was constructed with values that violate its contract.

    Also a ``ValueError``: the work_core registry precedent validated ids at
    construction with plain ``ValueError``; the C1 layer keeps that catch
    surface while adding an importable typed class.
    """


class InvalidProviderIdError(CoreDTOError):
    """A provider id failed the component-id rule (work_core.registry parity)."""
