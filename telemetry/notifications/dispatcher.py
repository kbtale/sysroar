import logging
from typing import TYPE_CHECKING, Dict
from .email import EmailStrategy
from .providers import (
    DiscordStrategy,
    GotifyStrategy,
    NtfyStrategy,
    OpsgenieStrategy,
    PagerDutyStrategy,
    SlackStrategy,
    TeamsStrategy,
    TelegramStrategy,
)
from .webhook import WebhookStrategy

if TYPE_CHECKING:
    from monitoring.models import AlertRule, Server

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    STRATEGIES = {
        'EMAIL': EmailStrategy(),
        'WEBHOOK': WebhookStrategy(),
        'SLACK': SlackStrategy(),
        'DISCORD': DiscordStrategy(),
        'TEAMS': TeamsStrategy(),
        'TELEGRAM': TelegramStrategy(),
        'PAGERDUTY': PagerDutyStrategy(),
        'OPSGENIE': OpsgenieStrategy(),
        'NTFY': NtfyStrategy(),
        'GOTIFY': GotifyStrategy(),
    }

    @classmethod
    def dispatch_alert(cls, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        return cls._dispatch(server, rule, context, 'send_alert')

    @classmethod
    def dispatch_resolution(cls, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        return cls._dispatch(server, rule, context, 'send_resolution')

    @classmethod
    def _dispatch(cls, server: 'Server', rule: 'AlertRule', context: Dict, method_name: str) -> bool:
        strategy_type = rule.notification_type
        strategy = cls.STRATEGIES.get(strategy_type)
        if not strategy:
            logger.error(f'Unknown notification type: {strategy_type}')
            return False
        logger.info(f'Dispatching {strategy_type} {method_name} for rule {rule.id}')
        method = getattr(strategy, method_name)
        return method(server, rule, context)
