from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from monitoring.models import Server, AlertRule

class NotificationStrategy(ABC):
    """
    Abstract base class for notification strategies.
    """
    @abstractmethod
    def send_alert(self, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        """
        Sends an alert notification when a threshold is breached.
        """
        pass

    @abstractmethod
    def send_resolution(self, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        """
        Sends a resolution notification when a server returns to a healthy state.
        """
        pass
