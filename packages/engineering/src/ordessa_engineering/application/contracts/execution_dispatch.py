"""Demand-side native operation port; composition selects the original owner."""
from typing import Protocol

EXECUTION_DISPATCH = 'engineering.executions.dispatch'


class ExecutionDispatchPort(Protocol):
    factory: object
    access: object

    def execute(self, operation, parameters, context):
        """Return the original durable dispatch outcome; never Engineering acceptance."""
        ...
