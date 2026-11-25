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
            # Mock debt for DRY_RUN payment flow testing.
            # In real mode this queries the Vodokanal LK.
            return "1500.00", "1500.00"
        return None, None


class HttpxVodokanalClient(VodokanalClient):
    """Real client using httpx with session persistence.

    Uses the AO «Анапа Водоканал» LK endpoints:
    - POST {base}/Account/Login  (credentials)
    - GET  {base}/...            (readings + debt)
    - POST {base}/AddCounterValue (value + __RequestVerificationToken)
    """

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
        if not self.session:
            return False
        resp = await self.session.post(
            f"{self.cfg.base_url}/Account/Login",
            data={"login": self.cfg.login, "password": self.cfg.password},
            headers={"Accept": "text/html"},
        )
        if resp.status_code >= 400:
            return False
        self.csrf_token = resp.cookies.get("XSRF-TOKEN") or self.csrf_token
        return True

    async def get_counter_readings(
        self,
    ) -> tuple[int | None, int | None, str | None]:
        if not self.session:
            return None, None, None
        resp = await self.session.get(f"{self.cfg.base_url}/Personal/Readings")
        if resp.status_code >= 400:
            return None, None, None
        text = resp.text
        # Extract all integer-like numbers from HTML table rows.
        # Real LK markup is not known yet; parse whole + previous via regex.
        nums: list[int] = []
        for token in text.replace("\u00a0", " ").split():
            try:
                n = int(token)
                if n > 0:
                    nums.append(n)
            except ValueError:
                continue
        if not nums:
            return None, None, None
        return nums[-1], nums[-2] if len(nums) > 1 else None, None

    async def add_counter_value(self, value: int) -> tuple[bool, str | None]:
        if not self.session:
            return False, "No session"
        resp = await self.session.post(
            f"{self.cfg.base_url}/AddCounterValue",
            data={"value": str(value), "__RequestVerificationToken": self.csrf_token or ""},
        )
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}"
        return True, None

    async def get_debt(self) -> tuple[str | None, str | None]:
        if not self.session:
            return None, None
        resp = await self.session.get(f"{self.cfg.base_url}/Personal/Debt")
        if resp.status_code >= 400:
            return None, None
        debt_text = resp.text.strip()
        if not debt_text:
            return None, None
        return debt_text, None


def get_vodokanal_client(
    *, dry_run: bool, login: str, password: str, base_url: str = "https://abonent.vodokanal.net"
) -> VodokanalClient:
    """Factory: pick real or stub client based on DRY_RUN mode."""
    if dry_run:
        return StubVodokanalClient(dry_run=True)
    cfg = ClientConfig(login=login, password=password, base_url=base_url)
    client = HttpxVodokanalClient(cfg)
    # Ensure a session exists even before async context manager usage.
    client.session = httpx.AsyncClient(timeout=cfg.timeout, follow_redirects=cfg.follow_redirects)
    return client
