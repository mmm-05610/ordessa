"""Exact ChangeSet business outcomes; unexpected programming errors still raise."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from .errors import DomainError

T = TypeVar("T")
E = TypeVar("E", bound=DomainError)


@dataclass(frozen=True)
class Result(Generic[T, E]):
    """A success value (including None) or the original stable DomainError.

    This value does not catch exceptions, serialize output, or confer authority.
    Callers must inspect ok/error rather than the object's truthiness.
    """

    value: T | None = None
    error: E | None = None

    def __post_init__(self) -> None:
        if self.error is not None:
            if type(self.error) is not DomainError:
                raise TypeError("Result failure requires DomainError")
            if self.value is not None:
                raise ValueError("Result cannot contain both value and error")

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, value: T) -> Result[T, E]:
        return cls(value=value)

    @classmethod
    def failure(cls, error: E) -> Result[T, E]:
        if type(error) is not DomainError:
            raise TypeError("Result failure requires DomainError")
        return cls(error=error)

    def __bool__(self) -> bool:
        raise TypeError("Inspect Result.ok or Result.error explicitly")
