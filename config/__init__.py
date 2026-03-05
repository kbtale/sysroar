from .celery import app as celery_app
from . import checks  # noqa: F401 — registers Django system checks

__all__ = ('celery_app',)
