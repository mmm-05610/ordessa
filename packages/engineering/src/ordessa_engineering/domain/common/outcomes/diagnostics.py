"""Minimal constructor/decoder refusals; no business enum, models or complete error."""

class ReferenceError(ValueError):
    """Preserve code/str/args while leaving full domain errors to business boundaries."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
