"""Result data and mutually exclusive value/error invariant."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Generic, TypeVar
from .diagnostics import MethodError
T = TypeVar("T")

@dataclass(frozen=True)
class MethodResult(Generic[T]):
    value: T | None = None
    error: MethodError | None = None

    def __post_init__(self) -> None:
        if self.error is not None and self.value is not None:
            raise ValueError("method result cannot contain both a value and an error")

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, value: T) -> "MethodResult[T]":
        return cls(value=value)

    @classmethod
    def failure(cls, error: MethodError) -> "MethodResult[T]":
        return cls(error=error)


