import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('sysroar')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()

from celery.signals import task_prerun, task_postrun, before_task_publish

@before_task_publish.connect
def before_task_publish_handler(sender=None, headers=None, body=None, **kwargs):
    from .logging_utils import get_correlation_id
    correlation_id = get_correlation_id()
    if correlation_id:
        headers["correlation_id"] = correlation_id

@task_prerun.connect
def task_prerun_handler(task_id, task, *args, **kwargs):
    from .logging_utils import set_correlation_id
    correlation_id = task.request.get("correlation_id")
    if correlation_id:
        set_correlation_id(correlation_id)

@task_postrun.connect
def task_postrun_handler(task_id, task, *args, **kwargs):
    from .logging_utils import clear_correlation_id
    clear_correlation_id()

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
