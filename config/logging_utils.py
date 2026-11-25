import logging
import logging.handlers
from asgiref.local import Local

_locals = Local()


def get_correlation_id():
    return getattr(_locals, 'correlation_id', None)


def set_correlation_id(correlation_id):
    _locals.correlation_id = correlation_id


def clear_correlation_id():
    if hasattr(_locals, 'correlation_id'):
        del _locals.correlation_id


class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        record.correlation_id = get_correlation_id() or 'system'
        return True


class JsonTcpLogHandler(logging.handlers.SocketHandler):
    def makeSocket(self, timeout=2.0):
        return super().makeSocket(timeout=timeout)

    def makePickle(self, record):
        return (self.format(record) + '\n').encode('utf-8')


def build_logging_config(
    log_backend='none',
    logstash_host='logstash',
    logstash_port=5044,
    log_level='INFO',
):
    handlers = {
        'console': {
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
            'formatter': 'json',
            'filters': ['correlation_id'],
        },
    }
    root_handlers = ['console']

    if (log_backend or 'none').lower() == 'elasticsearch':
        handlers['logstash'] = {
            'level': 'DEBUG',
            'class': 'config.logging_utils.JsonTcpLogHandler',
            'host': logstash_host,
            'port': logstash_port,
            'formatter': 'json',
            'filters': ['correlation_id'],
        }
        root_handlers.append('logstash')

    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'json': {
                '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
                'format': '%(asctime)s %(levelname)s %(name)s %(message)s %(correlation_id)s',
            },
        },
        'filters': {
            'correlation_id': {
                '()': 'config.logging_utils.CorrelationIdFilter',
            },
        },
        'handlers': handlers,
        'root': {
            'handlers': root_handlers,
            'level': log_level,
        },
    }
