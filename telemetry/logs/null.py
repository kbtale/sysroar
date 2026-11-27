from datetime import datetime
from .base import LogBackend


class NullLogBackend(LogBackend):
    backend_name = 'none'
    enabled = False

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
        return []

    def count_matching(
        self,
        company_id: str,
        server_id: str | None = None,
        q: str = '',
        level: str = '',
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        return 0

    def health(self) -> dict:
        return {'enabled': False, 'backend': 'none', 'healthy': True}
