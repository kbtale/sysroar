import contextvars
import uuid
import logging

_correlation_id_ctx = contextvars.ContextVar("correlation_id", default=None)

def get_correlation_id():
    return _correlation_id_ctx.get()

def set_correlation_id(correlation_id):
    _correlation_id_ctx.set(correlation_id)

def clear_correlation_id():
    _correlation_id_ctx.set(None)

class CorrelationIdFilter(logging.Filter):
    """
    Injects correlation_id into the log record.
    """
    def filter(self, record):
        record.correlation_id = get_correlation_id() or "system"
        return True
