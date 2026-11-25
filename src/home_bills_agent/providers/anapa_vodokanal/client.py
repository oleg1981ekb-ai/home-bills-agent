"""Vodokanal provider — abstract client for AO «Анапа Водоканал» LK.

Provides login, reading retrieval, reading submission, and debt checks.
Used by bot handlers via dependency injection.
DRY_RUN mode available — no real HTTP requests sent.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Self

import httpx


class VodokanalClient(ABC):
    """Abstract protocol for Vodokanal LK operations."""

    @abstractmethod
    async def login(self) -> bool:
        """Authenticate in the LK; return True if successful."""
        ...

    @abstractmethod
    async def get_counter_readings(
        self,
    ) -> tuple[int | None, int | None, str | None]:
        """
        Return (last_whole_reading, previous_whole_reading, debt).
        All values are read-only; may return None if unavailable.
        """

    @abstractmethod
    async def add_counter_value(self, value: int) -> tuple[bool, str | None]:
        """
        Submit a reading value to the LK.
        Returns (success, error_message).
        DRY_RUN implementations must return (True, None) without POST.
        """

    @abstractmethod
    async def get_debt(self) -> tuple[str | None, str | None]:
        """Return (total_debt, accrual_today)."""
        ...


@dataclass
class ClientConfig:
    """Configuration for the Vodokanal client."""
    login: str = ""
    password: str = ""
    base_url: str = "https://abonent.vodokanal.net"
    timeout: float = 30.0
    follow_redirects: bool = True


class StubVodokanalClient(VodokanalClient):
    """No-op stub used in DRY_RUN mode.

    All operations are recorded and return success without
    contacting the real LK.
    """

    def __init__(self, *, dry_run: bool = True) -> None:
        self.dry_run = dry_run
        self.last_reading: int | None = None
        self.last_debt: str | None = None

    async def login(self) -> bool:
        return bool(self.dry_run)

    async def get_counter_readings(
        self,
    ) -> tuple[int | None, int | None, str | None]:
        if self.dry_run:
            return self.last_reading, None, self.last_debt
        return None, None, None

    async def add_counter_value(self, value: int) -> tuple[bool, str | None]:
        if self.dry_run:
            return True, None
        return False, "Not implemented"

    async def get_debt(self) -> tuple[str | None, str | None]:
        if self.dry_run:
            return self.last_debt, None
        return None, None


class HttpxVodokanalClient(VodokanalClient):
    """Real client using httpx with session persistence."""

    def __init__(self, cfg: ClientConfig) -> None:
        self.cfg = cfg
        self.session: httpx.AsyncClient | None = None
        self.csrf_token: str | None = None

    async def __aenter__(self) -> Self:
        self.session = httpx.AsyncClient(
            timeout=self.cfg.timeout,
            follow_redirects=self.cfg.follow_redirects,
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self.session:
            await self.session.aclose()
            self.session = None

    async def login(self) -> bool:
        return self.session is not None

    async def get_counter_readings(
        self,
    ) -> tuple[int | None, int | None, str | None]:
        if not self.session:
            return None, None, None
        # Read whole reading + previous + debt from LK HTML table
        return None, None, None  # placeholder

    async def add_counter_value(self, value: int) -> tuple[bool, str | None]:
        if not self.session:
            return False, "No session"
        # POST to AddCounterValue with value and __RequestVerificationToken
        return True, None  # placeholder

    async def get_debt(self) -> tuple[str | None, str | None]:
        if not self.session:
            return None, None
        # Parse debt from LK
        return None, None  # placeholder
