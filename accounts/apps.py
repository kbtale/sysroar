import importlib
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        importlib.import_module('accounts.signals')
        importlib.import_module('accounts.schema')
