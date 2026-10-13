class EngineeringError(RuntimeError):
    """A stable, safe error code for invalid input or refused state changes."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
