import logging
from typing import TYPE_CHECKING, Dict
from .email import EmailStrategy
from .webhook import WebhookStrategy

if TYPE_CHECKING:
    from monitoring.models import Server, AlertRule

logger = logging.getLogger(__name__)

class NotificationDispatcher:
    """
    Dispatcher factory that selects and executes the correct notification strategy.
    """
    STRATEGIES = {
        'EMAIL': EmailStrategy(),
        'WEBHOOK': WebhookStrategy(),
    }

    @classmethod
    def dispatch_alert(cls, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        """
        Dispatches a breach notification.
        """
        return cls._dispatch(server, rule, context, "send_alert")

    @classmethod
    def dispatch_resolution(cls, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        """
        Dispatches a resolution notification.
        """
        return cls._dispatch(server, rule, context, "send_resolution")

    @classmethod
    def _dispatch(cls, server: 'Server', rule: 'AlertRule', context: Dict, method_name: str) -> bool:
        strategy_type = rule.notification_type
        strategy = cls.STRATEGIES.get(strategy_type)
        
        if not strategy:
            logger.error(f"Unknown notification type: {strategy_type}")
            return False
            
        logger.info(f"Dispatching {strategy_type} {method_name} for rule {rule.id}")
        method = getattr(strategy, method_name)
        return method(server, rule, context)
