from asgiref.local import Local
import uuid
import logging

_locals = Local()

def get_correlation_id():
    return getattr(_locals, "correlation_id", None)

def set_correlation_id(correlation_id):
    _locals.correlation_id = correlation_id

def clear_correlation_id():
    if hasattr(_locals, "correlation_id"):
        del _locals.correlation_id

class CorrelationIdFilter(logging.Filter):
    """
    Injects correlation_id into the log record.
    """
    def filter(self, record):
        record.correlation_id = get_correlation_id() or "system"
        return True
