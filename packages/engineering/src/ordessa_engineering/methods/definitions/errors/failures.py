"""Exception carrying the method error DTO; no logging/retry/transport mapping."""
from .diagnostics import MethodError

class MethodFailure(Exception):
    def __init__(self, error: MethodError):
        super().__init__(error.message)
        self.error = error


