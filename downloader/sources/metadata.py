from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SourceVerificationStatus = Literal['unchecked', 'healthy', 'degraded', 'unavailable']


@dataclass(frozen=True)
class SourceCapabilities:
    search: bool = True
    info: bool = True
    download: bool = True


@dataclass(frozen=True)
class SourceVerification:
    status: SourceVerificationStatus = 'unchecked'
    checked_at: str | None = None
    latency_seconds: float | None = None
    http_status: int | None = None
    message: str | None = None

    @property
    def checked(self) -> bool:
        return self.checked_at is not None and self.status != 'unchecked'
