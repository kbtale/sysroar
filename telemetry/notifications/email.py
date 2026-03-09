import logging
from typing import TYPE_CHECKING, Dict
from django.core.mail import send_mail
from django.conf import settings
from .base import NotificationStrategy

if TYPE_CHECKING:
    from monitoring.models import Server, AlertRule

logger = logging.getLogger(__name__)

class EmailStrategy(NotificationStrategy):
    """
    SMTP Email notification strategy.
    """
    def send_alert(self, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        subject = f"[SysRoar] Alert: {rule.metric_type.upper()} threshold reached on {server.name}"
        message = (
            f"Server: {server.name} ({server.ip_address})\n"
            f"Metric: {rule.metric_type.upper()}\n"
            f"Condition: > {rule.threshold_value}\n"
            f"Current Value: {context.get('value')}\n"
            f"Timestamp: {context.get('timestamp')}\n\n"
            "Please check the dashboard for more details."
        )
        return self._send(rule.notification_target, subject, message)

    def send_resolution(self, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        subject = f"[SysRoar] RESOLVED: {rule.metric_type.upper()} on {server.name}"
        message = (
            f"Server {server.name} has returned to a healthy state.\n"
            f"Metric: {rule.metric_type.upper()} is now below the threshold of {rule.threshold_value}.\n"
            f"Timestamp: {context.get('timestamp')}\n"
        )
        return self._send(rule.notification_target, subject, message)

    def _send(self, recipient: str, subject: str, message: str) -> bool:
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [recipient],
                fail_silently=False,
            )
            logger.info(f"Email notification sent to {recipient}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email notification to {recipient}: {str(e)}")
            return False
