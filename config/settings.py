import os
import tempfile
from datetime import timedelta
from pathlib import Path
import environ
from celery.schedules import crontab

# Build paths inside the project like this: BASE_DIR / 'subdir'
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
# Reading .env file
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-me-stargazer')

DEBUG = env('DEBUG')

# Internal Monitoring Alerts
ADMIN_NAME = env('ADMIN_NAME', default='Admin')
ADMIN_EMAIL = env('ADMIN_EMAIL', default='admin@sysroar.com')
ADMINS = [
    (ADMIN_NAME, ADMIN_EMAIL),
]

EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='mailpit')
EMAIL_PORT = env.int('EMAIL_PORT', default=1025)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=False)
EMAIL_USE_SSL = env.bool('EMAIL_USE_SSL', default=False)
EMAIL_TIMEOUT = env.int('EMAIL_TIMEOUT', default=10)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='alerts@sysroar.local')
SERVER_EMAIL = env('SERVER_EMAIL', default=DEFAULT_FROM_EMAIL)

SYSTEM_EVENT_THRESHOLDS = {
    'FAILED_AUTHENTICATION': env.int('FAILED_AUTH_THRESHOLD', default=10),
    'WEBHOOK_DISPATCH_FAILURE': env.int('WEBHOOK_FAIL_THRESHOLD', default=5),
    'POSTGRES_TRANSACTION_ROLLBACK': env.int('DB_ROLLBACK_THRESHOLD', default=1),
    'WS_AUTH_FAILURE': env.int('WS_AUTH_FAIL_THRESHOLD', default=15),
    'WS_ERROR': env.int('WS_ERROR_THRESHOLD', default=10),
    'METRIC_PERSISTENCE_FAILURE': env.int('PERSISTENCE_FAIL_THRESHOLD', default=1),
}

REDIS_URL = env('REDIS_URL', default='redis://redis:6379/0')

from django.core.exceptions import ImproperlyConfigured
from config.security import DEFAULT_CSP_POLICY, validate_production_security

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1', 'web'])

_PROD_SECURITY_ERRORS = validate_production_security(DEBUG, SECRET_KEY, ALLOWED_HOSTS)
if _PROD_SECURITY_ERRORS:
    raise ImproperlyConfigured(' '.join(msg for _, msg in _PROD_SECURITY_ERRORS))

ADMIN_URL = env('ADMIN_URL', default='admin/').lstrip('/')
if ADMIN_URL and not ADMIN_URL.endswith('/'):
    ADMIN_URL = f'{ADMIN_URL}/'

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
CSP_POLICY = env('CSP_POLICY', default=DEFAULT_CSP_POLICY)

if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True)
    SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=True)
    SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
    CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)
    if env.bool('USE_X_FORWARDED_PROTO', default=True):
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Application definition
INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework.authtoken',
    'django_extensions',
    'channels',
    'axes',
    # Core Apps
    'accounts',
    'telemetry',
    'monitoring',
]

AUTH_USER_MODEL = 'accounts.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'config.security.SecurityHeadersMiddleware',
    'config.middleware.CorrelationIdMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.CurrentTenantMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'axes.middleware.AxesMiddleware',
]

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases
DATABASES = {
    'default': env.db('DATABASE_URL', default='postgres://sysroar_user:sysroar_password@db:5432/sysroar')
}
DATABASES['default'].setdefault('OPTIONS', {})['connect_timeout'] = env.int('DB_CONNECT_TIMEOUT', default=5)

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'accounts.authentication.TenantTokenAuthentication',
        'accounts.authentication.TenantSessionAuthentication',
    ),
    'EXCEPTION_HANDLER': 'config.exceptions.custom_exception_handler',
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': env('ANON_THROTTLE_RATE', default='60/min'),
        'user': env('USER_THROTTLE_RATE', default='120/min'),
        'login': env('LOGIN_THROTTLE_RATE', default='10/min'),
        'telemetry_ingest': env('TELEMETRY_INGEST_THROTTLE_RATE', default='60/min'),
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_PARSER_CLASSES': (
        'rest_framework.parsers.JSONParser',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    ),
}

# Redis & Channels
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [env('REDIS_URL', default='redis://redis:6379/0')],
        },
    },
}

# Celery Configuration
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='redis://redis:6379/1')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default='redis://redis:6379/2')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

CELERY_TASK_IGNORE_RESULT = True

CELERY_BEAT_SCHEDULE = {
    'evaluate-alert-rules-every-30s': {
        'task': 'monitoring.evaluate_alert_rules',
        'schedule': 30.0,
    },
    'retry-pending-outbox-every-60s': {
        'task': 'monitoring.retry_pending_outbox',
        'schedule': 60.0,
    },
    'flush-heartbeats-every-30s': {
        'task': 'monitoring.flush_heartbeats',
        'schedule': 30.0,
    },
    'check-heartbeats-every-30s': {
        'task': 'monitoring.check_heartbeats',
        'schedule': 30.0,
    },
    'check-system-health-15m': {
        'task': 'monitoring.check_system_health',
        'schedule': crontab(minute='*/15'),
    },
    'nightly-purge-system-events': {
        'task': 'monitoring.purge_old_system_events',
        'schedule': crontab(minute=30, hour=2),
    },
}

TELEMETRY_STREAM_KEY = env('TELEMETRY_STREAM_KEY', default='sysroar:telemetry:stream')
TELEMETRY_DLQ_STREAM_KEY = env('TELEMETRY_DLQ_STREAM_KEY', default='sysroar:telemetry:dlq')
TELEMETRY_CONSUMER_GROUP = env('TELEMETRY_CONSUMER_GROUP', default='sysroar-ingest')
TELEMETRY_STREAM_MAXLEN = env.int('TELEMETRY_STREAM_MAXLEN', default=100000)
TELEMETRY_DLQ_MAXLEN = env.int('TELEMETRY_DLQ_MAXLEN', default=10000)
TELEMETRY_MAX_DELIVERIES = env.int('TELEMETRY_MAX_DELIVERIES', default=5)
TELEMETRY_MAX_BATCH_SIZE = env.int('TELEMETRY_MAX_BATCH_SIZE', default=500)
TELEMETRY_MAX_COMPRESSED_BYTES = env.int('TELEMETRY_MAX_COMPRESSED_BYTES', default=1024 * 1024)
TELEMETRY_MAX_DECOMPRESSED_BYTES = env.int('TELEMETRY_MAX_DECOMPRESSED_BYTES', default=5 * 1024 * 1024)

TELEMETRY_RETENTION_DAYS = env.int('TELEMETRY_RETENTION_DAYS', default=14)

CELERY_BEAT_SCHEDULE_FILENAME = env(
    'CELERY_BEAT_SCHEDULE_FILENAME',
    default=os.path.join(tempfile.gettempdir(), 'sysroar-celerybeat-schedule'),
)

# CORS & CSRF
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
    'http://localhost:3000', 
    'http://127.0.0.1:3000',
    'http://localhost:5173',
    'http://localhost:5174',
    'http://127.0.0.1:5173',
    'http://127.0.0.1:5174',
])
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[
    'http://localhost:3000', 
    'http://127.0.0.1:3000',
    'http://localhost:5173',
    'http://localhost:5174',
    'http://127.0.0.1:5173',
    'http://127.0.0.1:5174',
])

# Redis Cache & Sessions
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env('REDIS_URL', default='redis://redis:6379/0'),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = env.int('SESSION_COOKIE_AGE', default=60 * 60 * 24 * 7)
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'

from config.logging_utils import build_logging_config

LOG_BACKEND = env('LOG_BACKEND', default='none').lower()
LOGSTASH_HOST = env('LOGSTASH_HOST', default='logstash')
LOGSTASH_PORT = env.int('LOGSTASH_PORT', default=5044)
LOG_LEVEL = env('LOG_LEVEL', default='INFO').upper()

LOGGING = build_logging_config(
    log_backend=LOG_BACKEND,
    logstash_host=LOGSTASH_HOST,
    logstash_port=LOGSTASH_PORT,
    log_level=LOG_LEVEL,
)

METRICS_AUTH_TOKEN = env('METRICS_AUTH_TOKEN', default='')
READY_MAX_STREAM_LAG = env.int('READY_MAX_STREAM_LAG', default=10000)
OPEN_REGISTRATION = env.bool('OPEN_REGISTRATION', default=False)
FRONTEND_URL = env('FRONTEND_URL', default='http://localhost:5173')
FAILED_AUTH_DEDUP_WINDOW_SECONDS = env.int('FAILED_AUTH_DEDUP_WINDOW_SECONDS', default=60)
FAILED_AUTH_SAMPLE_EVERY = env.int('FAILED_AUTH_SAMPLE_EVERY', default=50)
AXES_HANDLER = 'axes.handlers.cache.AxesCacheHandler'
AXES_CACHE = 'default'
AXES_FAILURE_LIMIT = env.int('AXES_FAILURE_LIMIT', default=5)
AXES_COOLOFF_TIME = timedelta(minutes=env.int('AXES_COOLOFF_MINUTES', default=15))
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]
AXES_LOCKOUT_CALLABLE = 'accounts.views.axes_lockout_response'
AXES_VERBOSE = False
SENTRY_DSN = env('SENTRY_DSN', default='')
SENTRY_TRACES_SAMPLE_RATE = env.float('SENTRY_TRACES_SAMPLE_RATE', default=0.0)

if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,
    )
