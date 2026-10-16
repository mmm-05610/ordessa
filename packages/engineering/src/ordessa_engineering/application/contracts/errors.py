"""Application error contract (single owner)."""


class ApplicationError(RuntimeError):
    def __init__(self, code: str, *, retry: str = "never"):
        super().__init__(code)
        self.code = code
        self.retry = retry


__all__ = ['ApplicationError']
