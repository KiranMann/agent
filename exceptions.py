"""Custom exceptions for financial companion agent."""


class ValidationError(Exception):
    """Custom exception for validation errors."""

    pass


class AgentExecutionError(Exception):
    """Custom exception for agent execution errors."""

    pass


class DataRetrievalError(Exception):
    """Custom exception for when an error happens during data retrieval."""

    pass


class NoDataFoundError(Exception):
    """Custom exception for when no data is found during retrieval."""

    pass
