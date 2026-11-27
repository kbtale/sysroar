from abc import ABC, abstractmethod
from datetime import datetime


class LogBackend(ABC):
    backend_name: str = 'none'
    enabled: bool = False

    @abstractmethod
    def query(
        self,
        company_id: str,
        server_id: str | None = None,
        q: str = '',
        level: str = '',
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 200,
    ) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def count_matching(
        self,
        company_id: str,
        server_id: str | None = None,
        q: str = '',
        level: str = '',
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict:
        raise NotImplementedError
