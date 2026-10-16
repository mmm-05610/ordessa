"""Read existing execution-linked Work history without migration or replay."""
from .history import ExecutionHistory, HistoricalRef, HistoryNotFound, parse_correlation

__all__ = ['ExecutionHistory', 'HistoricalRef', 'HistoryNotFound', 'parse_correlation']
