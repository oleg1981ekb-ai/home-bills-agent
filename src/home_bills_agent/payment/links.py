"""Payment links builder and log masking for account IDs."""
from __future__ import annotations

BASE_URL = "https://andromeda.a-3.ru/6172"


def build_payment_link(account_id: str) -> str:
    """Return payment link for the account's personal account number."""
    return f"{BASE_URL}/?PERSONAL_ACCOUNT={account_id}"


def mask_account_id(account_id: str) -> str:
    """Mask account id for logging (keep last 4)."""
    if not account_id:
        return "***"
    if len(account_id) <= 4:
        return "*" * len(account_id)
    return "***" + account_id[-4:]


def sanitize_for_logs(text: str | None) -> str:
    """Strip any potential secret patterns (tokens, cookies, passwords)."""
    if not text:
        return ""
    masked = text
    for pattern in ("token=", "cookie=", "password=", "password"):
        if pattern in masked.lower():
            idx = masked.lower().find(pattern)
            masked = masked[:idx] + "[REDACTED]"
    return masked