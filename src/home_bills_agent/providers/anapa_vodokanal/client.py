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

    Uses the AO «Анапа Водоканал» LK endpoints per SPEC §3:
    - POST {base}/fl/Account/Login (credentials, __RequestVerificationToken)
    - GET  {base}/fl/UserPage?account=...  (main page: debt, readings, CSRF token)
    - POST {base}/fl/UserPage/AddCounterValue (submit reading)
    """

    def __init__(self, cfg: ClientConfig, account_id: str = "", counter_code: str = "") -> None:
        self.cfg = cfg
        self.account_id = account_id
        self.counter_code = counter_code
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

    def _extract_csrf_from_html(self, html: str) -> str | None:
        """Extract __RequestVerificationToken from hidden form field."""
        marker = '__RequestVerificationToken"'
        idx = html.find(marker)
        if idx == -1:
            marker = "__RequestVerificationToken"
            idx = html.find(marker)
        if idx == -1:
            return None
        seg = html[idx:]
        for sep in ('value="', 'value=\''):
            parts = seg.split(sep, 1)
            if len(parts) > 1:
                val = parts[1].split(sep[-1], 1)[0]
                if val:
                    return val
        return None

    async def _ensure_csrf(self) -> str | None:
        """Ensure we have a CSRF token by fetching the main page if needed."""
        if self.csrf_token:
            return self.csrf_token
        if not self.session or not self.account_id:
            return None
        resp = await self.session.get(
            f"{self.cfg.base_url}/fl/UserPage",
            params={"account": self.account_id},
            headers={"Accept": "text/html"},
        )
        if resp.status_code >= 400:
            return None
        token = self._extract_csrf_from_html(resp.text)
        if token:
            self.csrf_token = token
        return token

    async def login(self) -> bool:
        if not self.session:
            return False

        # First, fetch the login page to get CSRF token
        resp = await self.session.get(
            f"{self.cfg.base_url}/fl/Account/Login",
            headers={"Accept": "text/html"},
        )
        csrf = self._extract_csrf_from_html(resp.text)
        if csrf:
            self.csrf_token = csrf

        # Submit credentials
        resp = await self.session.post(
            f"{self.cfg.base_url}/fl/Account/Login",
            data={
                "__RequestVerificationToken": self.csrf_token or "",
                "Login": self.cfg.login,
                "Password": self.cfg.password,
                "RememberMe": "false",
            },
            headers={"Accept": "text/html"},
        )
        if resp.status_code >= 400:
            return False

        # Try to get a fresh CSRF from UserPage after login
        if self.account_id:
            await self._ensure_csrf()
        return True

    async def get_counter_readings(
        self,
    ) -> tuple[int | None, int | None, str | None]:
        """Return (last_whole_reading, previous_whole_reading, debt)."""
        if not self.session or not self.account_id:
            return None, None, None
        resp = await self.session.get(
            f"{self.cfg.base_url}/fl/UserPage",
            params={"account": self.account_id},
            headers={"Accept": "text/html"},
        )
        if resp.status_code >= 400:
            return None, None, None
        text = resp.text
        # Extract CSRF token for subsequent requests
        token = self._extract_csrf_from_html(text)
        if token:
            self.csrf_token = token

        # Parse whole-number readings from HTML table
        nums: list[int] = []
        for token_str in text.replace("\u00a0", " ").split():
            try:
                n = int(token_str)
                if n > 0:
                    nums.append(n)
            except ValueError:
                continue

        last = nums[-1] if nums else None
        prev = nums[-2] if len(nums) > 1 else None
        debt = self._parse_debt_from_text(text)
        return last, prev, debt

    async def add_counter_value(self, value: int) -> tuple[bool, str | None]:
        """Submit a reading value to the LK."""
        if not self.session or not self.account_id:
            return False, "No session"

        # Ensure CSRF token
        await self._ensure_csrf()

        resp = await self.session.post(
            f"{self.cfg.base_url}/fl/UserPage/AddCounterValue",
            data={
                "__RequestVerificationToken": self.csrf_token or "",
                "idDb": "1",
                "Code": self.counter_code or "",
                "LastValue": "",
                "NewValue": str(value),
            },
            headers={
                "Accept": "text/html",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}"
        return True, None

    async def get_debt(self) -> tuple[str | None, str | None]:
        """Return (total_debt, accrual_today). Debt is parsed from UserPage."""
        if not self.session or not self.account_id:
            return None, None
        resp = await self.session.get(
            f"{self.cfg.base_url}/fl/UserPage",
            params={"account": self.account_id},
            headers={"Accept": "text/html"},
        )
        if resp.status_code >= 400:
            return None, None
        debt_value = self._parse_debt_from_text(resp.text)
        return debt_value, None

    def _parse_debt_from_text(self, text: str) -> str | None:
        cleaned = text.replace("\u00a0", " ").strip()
        if not cleaned:
            return None
        tokens = cleaned.split()
        for token in reversed(tokens):
            try:
                v = float(token)
                if v > 0:
                    return f"{v:.2f}"
            except ValueError:
                continue
        return None


def get_vodokanal_client(
    *,
    dry_run: bool,
    login: str,
    password: str,
    base_url: str = "https://abonent.vodokanal.net",
    account_id: str = "",
    counter_code: str = "",
) -> VodokanalClient:
    """Factory: pick real or stub client based on DRY_RUN mode."""
    if dry_run:
        return StubVodokanalClient(dry_run=True)
    cfg = ClientConfig(login=login, password=password, base_url=base_url)
    client = HttpxVodokanalClient(
        cfg,
        account_id=account_id,
        counter_code=counter_code,
    )
    client.session = httpx.AsyncClient(timeout=cfg.timeout, follow_redirects=cfg.follow_redirects)
    return client
