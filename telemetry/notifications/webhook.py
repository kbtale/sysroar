import logging
from typing import TYPE_CHECKING, Dict
import requests
from .base import NotificationStrategy

if TYPE_CHECKING:
    from monitoring.models import Server, AlertRule

logger = logging.getLogger(__name__)

class WebhookStrategy(NotificationStrategy):
    """
    Custom Webhook notification strategy.
    """
    def send_alert(self, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        return self._dispatch(server, rule, context, "alert_triggered")

    def send_resolution(self, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        return self._dispatch(server, rule, context, "alert_resolved")

    def _dispatch(self, server: 'Server', rule: 'AlertRule', context: Dict, event_type: str) -> bool:
        payload = {
            "event": event_type,
            "server_id": str(server.id),
            "hostname": server.name,
            "ip_address": server.ip_address,
            "rule": {
                "id": str(rule.id),
                "metric": rule.metric_type,
                "threshold": float(rule.threshold_value),
            },
            "metric_value": float(context.get('value', 0)),
            "timestamp": context.get('timestamp'),
        }
        
        try:
            response = requests.post(
                rule.notification_target,
                json=payload,
                timeout=5
            )
            response.raise_for_status()
            logger.info(f"Webhook {event_type} sent to {rule.notification_target}")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to send webhook to {rule.notification_target}: {str(e)}")
            return False
