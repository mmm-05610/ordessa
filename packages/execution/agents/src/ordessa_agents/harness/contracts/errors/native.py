"""Closed native model composition refusal; no effect authority."""


class NativeModelLaunchRefused(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
